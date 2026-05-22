"""Stage 4 enricher — uses Claude with the web_search tool to research
market data per cluster.

Frozen engine surface (DESIGN.md §3). The agent tunes pipeline.yaml's
enrichment.triggers, enrichment.model, and prompts/enrichment.md.

The 8 enrichment data points per SPECIFICATION.md Stage 4:
  direct_competitors, competitor_pricing, competitor_weaknesses,
  market_size_estimate, search_demand, funding_activity,
  regulatory_context, distribution_channels

Cluster filtering: a cluster only advances when its metrics pass the
enrichment.triggers thresholds AND its label isn't INCOHERENT/PARSE_ERROR.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from llm import Anthropic, APIError


_YAML_FENCE = re.compile(r"```(?:yaml)?\s*\n(.*?)```", re.DOTALL)


def enrich_clusters(config: dict, rdir: Path) -> None:
    ecfg = config.get("enrichment") or {}
    prompt_file = ecfg.get("prompt_file", "prompts/enrichment.md")
    triggers = ecfg.get("triggers") or {}
    model = ecfg.get("model") or (config.get("tagging") or {}).get("model", "claude-sonnet-4-6")
    temperature = float(ecfg.get("temperature", 0.3))
    max_searches = int(ecfg.get("max_searches", 5))
    max_tokens = int(ecfg.get("max_tokens", 6000))

    clusters_dir = rdir / "clusters"
    if not clusters_dir.exists():
        print("  no clusters; run `prospect run --stages cluster` first")
        return

    enrichments_dir = rdir / "enrichments"
    enrichments_dir.mkdir(parents=True, exist_ok=True)
    already = {p.stem for p in enrichments_dir.glob("clust_*.yaml")}

    cluster_files = sorted(clusters_dir.glob("clust_*.yaml"))
    all_clusters = [_load(p) for p in cluster_files]
    triggered = [c for c in all_clusters if _passes_triggers(c, triggers)]
    pending = [c for c in triggered if c["cluster_id"] not in already]

    print(
        f"  {len(all_clusters)} clusters; {len(triggered)} pass triggers; "
        f"{len(pending)} pending (skipping {len(triggered) - len(pending)} already enriched)"
    )
    if not pending:
        return

    prompt_template = Path(prompt_file).read_text()
    client = Anthropic()

    for c in pending:
        label = (c.get("cluster_label") or "")[:80]
        print(f"  enriching {c['cluster_id']}: {label}")
        record = _research_cluster(
            client, model, temperature, max_searches, max_tokens, prompt_template, c
        )
        with (enrichments_dir / f"{c['cluster_id']}.yaml").open("w") as f:
            yaml.safe_dump(record, f, sort_keys=False, allow_unicode=True)


def _passes_triggers(cluster: dict, triggers: dict) -> bool:
    label = cluster.get("cluster_label")
    if label in ("INCOHERENT", "PARSE_ERROR", "ERROR"):
        return False
    metrics = cluster.get("metrics") or {}
    if metrics.get("primary_signal_count", 0) < int(triggers.get("min_signal_count", 0)):
        return False
    if metrics.get("source_diversity", 0) < int(triggers.get("min_source_diversity", 0)):
        return False
    if metrics.get("workaround_count", 0) < int(triggers.get("min_workaround_count", 0)):
        return False
    median_intensity_required = int(triggers.get("min_median_intensity", 0))
    if median_intensity_required:
        # intensity_mean is the closest thing we compute; fall back to 0 if absent
        if (metrics.get("intensity_mean") or 0) < median_intensity_required:
            return False
    return True


def _research_cluster(
    client, model, temperature, max_searches, max_tokens, prompt_template, cluster
):
    metrics = cluster.get("metrics") or {}
    competitors_seen = sorted((metrics.get("competitor_mentions") or {}).keys())[:10]
    summary = (cluster.get("cluster_summary") or "").strip()
    summary_indented = "\n".join("  " + line for line in summary.splitlines())

    user_msg = (
        prompt_template
        + "\n\n---\n\n## Cluster to enrich\n\n"
        + f"cluster_id: {cluster['cluster_id']}\n"
        + f"cluster_label: {cluster.get('cluster_label')}\n"
        + f"cluster_summary: |\n{summary_indented}\n"
        + f"primary_signal_count: {metrics.get('primary_signal_count', 0)}\n"
        + f"source_diversity: {metrics.get('source_diversity', 0)}\n"
        + f"sources: {metrics.get('sources', [])}\n"
        + f"temporal_trend: {metrics.get('temporal_trend', 'unknown')}\n"
    )
    if competitors_seen:
        user_msg += f"competitors_seen_in_signals: {competitors_seen}\n"
    if "intensity_mean" in metrics:
        user_msg += f"intensity_mean: {metrics['intensity_mean']}\n"
    user_msg += (
        "\nUse the WebSearch tool freely to fill the enrichment fields. "
        f"Aim for at most {max_searches} searches total. "
        "Cite the URL you found each fact at in the output's `source:` fields. "
        "If a field is genuinely unknown after a reasonable search, set it to null with a note explaining why."
    )

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": user_msg}],
        )
    except APIError as e:
        return {
            "cluster_id": cluster["cluster_id"],
            "enrichment_status": "api_error",
            "error": f"{type(e).__name__}: {e}",
            "enrichment_model": model,
        }

    text_parts: list[str] = []
    citations: list[dict] = []
    for block in resp.content:
        if getattr(block, "type", None) == "text":
            text_parts.append(block.text)
            # Anthropic web_search attaches citation objects when grounded.
            for cit in getattr(block, "citations", None) or []:
                url = getattr(cit, "url", None) or (cit.get("url") if isinstance(cit, dict) else None)
                title = getattr(cit, "title", None) or (cit.get("title") if isinstance(cit, dict) else None)
                if url:
                    citations.append({"url": url, "title": title})
    text = "\n".join(text_parts).strip()

    m = _YAML_FENCE.search(text)
    body = m.group(1) if m else text
    try:
        parsed = yaml.safe_load(body)
        if not isinstance(parsed, dict):
            raise ValueError("non-dict")
    except Exception as e:
        return {
            "cluster_id": cluster["cluster_id"],
            "enrichment_status": "parse_error",
            "parse_error": str(e),
            "raw_response": text[:3000],
            "citations": citations,
            "enrichment_model": model,
        }

    parsed["cluster_id"] = cluster["cluster_id"]
    parsed["enrichment_status"] = "ok"
    parsed.setdefault("citations", citations)
    parsed["enrichment_model"] = model
    return parsed


def _load(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f) or {}
