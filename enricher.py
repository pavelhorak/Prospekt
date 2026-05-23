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

import json
from pathlib import Path

import yaml

from llm import Anthropic, APIError


# JSON Schema enforced by claude --json-schema. Loose by design — the model
# is free to skip fields it can't research, but the top-level shape is fixed.
ENRICHMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "direct_competitors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "url": {"type": ["string", "null"]},
                    "founded_year": {"type": ["integer", "null"]},
                    "pricing": {"type": ["object", "null"]},
                    "estimated_revenue": {"type": ["string", "null"]},
                    "team_size": {"type": ["integer", "string", "null"]},
                    "funding": {"type": ["string", "null"]},
                    "source": {"type": ["string", "null"]},
                },
                "required": ["name"],
            },
        },
        "competitor_weaknesses": {"type": ["object", "null"]},
        "market_size_estimate": {"type": ["object", "null"]},
        "search_demand": {"type": ["object", "null"]},
        "funding_activity": {"type": ["array", "object", "null"]},
        "regulatory_context": {"type": ["string", "null"]},
        "distribution_channels": {"type": ["object", "array", "null"]},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "title": {"type": ["string", "null"]},
                },
                "required": ["url"],
            },
        },
    },
    "required": ["direct_competitors"],
}


def enrich_clusters(config: dict, rdir: Path) -> None:
    ecfg = config.get("enrichment") or {}
    prompt_file = ecfg.get("prompt_file", "prompts/enrichment.md")
    triggers = ecfg.get("triggers") or {}
    model = ecfg.get("model") or (config.get("tagging") or {}).get("model", "claude-sonnet-4-6")
    temperature = float(ecfg.get("temperature", 0.3))
    max_searches = int(ecfg.get("max_searches", 5))
    max_tokens = int(ecfg.get("max_tokens", 6000))
    max_clusters = int(ecfg.get("max_clusters", 10))  # hard cap on per-run enrichment volume

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
    # Rank triggered clusters by primary_signal_count desc — densest evidence first.
    triggered.sort(key=lambda c: -(c.get("metrics") or {}).get("primary_signal_count", 0))
    fresh = [c for c in triggered if c["cluster_id"] not in already]
    pending = fresh[:max_clusters]

    print(
        f"  {len(all_clusters)} clusters; {len(triggered)} pass triggers; "
        f"{len(triggered) - len(fresh)} already enriched; "
        f"taking top {len(pending)} (cap = {max_clusters})"
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
        "Return ONLY valid JSON matching the enforced schema — no prose, "
        "no markdown fences. For every URL you cite, include {url, title} "
        "in the `citations` array. If a field is genuinely unknown after a "
        "reasonable search, set it to null."
    )

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": user_msg}],
            json_schema=ENRICHMENT_SCHEMA,
        )
    except APIError as e:
        return {
            "cluster_id": cluster["cluster_id"],
            "enrichment_status": "api_error",
            "error": f"{type(e).__name__}: {e}",
            "enrichment_model": model,
        }

    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
    try:
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("non-dict top-level")
    except Exception as e:
        return {
            "cluster_id": cluster["cluster_id"],
            "enrichment_status": "parse_error",
            "parse_error": str(e),
            "raw_response": text[:3000],
            "enrichment_model": model,
        }

    parsed["cluster_id"] = cluster["cluster_id"]
    parsed["enrichment_status"] = "ok"
    parsed.setdefault("citations", [])
    parsed["enrichment_model"] = model
    return parsed


def _load(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f) or {}
