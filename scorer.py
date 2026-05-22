"""Stage 5 scorer — 7-criterion scoring per cluster via Claude.

Frozen engine surface (DESIGN.md §3). The agent tunes pipeline.yaml's
scoring.weights, scoring.kill_criteria, and prompts/scoring.md.

Reads cluster files + enrichment files; for each cluster with enrichment,
builds a context prompt and asks Claude to score the 7 criteria with
evidence chains and confidence levels. Applies the configured weights to
produce weighted_total. Applies kill_criteria to mark unviable clusters.

Emits scores/{cluster_id}.yaml per cluster + scores/ranking.yaml.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from llm import Anthropic, APIError


_YAML_FENCE = re.compile(r"```(?:yaml)?\s*\n(.*?)```", re.DOTALL)

CRITERIA = [
    "market_demand", "distribution", "competition", "founder_market_fit",
    "solo_feasibility", "revenue_path", "defensibility",
]


def score_clusters(config: dict, rdir: Path) -> None:
    scfg = config.get("scoring") or {}
    prompt_file = scfg.get("prompt_file", "prompts/scoring.md")
    weights = scfg.get("weights") or {}
    kill_criteria = scfg.get("kill_criteria") or {}
    model = scfg.get("model") or (config.get("tagging") or {}).get("model", "claude-sonnet-4-6")
    temperature = float(scfg.get("temperature", 0.2))
    max_tokens = int(scfg.get("max_tokens", 4096))

    w_sum = sum(weights.values())
    if abs(w_sum - 1.0) > 0.01:
        print(f"  warning: scoring.weights sum to {w_sum:.3f}, not 1.0; weighted_total will be off-scale")

    clusters_dir = rdir / "clusters"
    enrich_dir = rdir / "enrichments"
    scores_dir = rdir / "scores"
    scores_dir.mkdir(parents=True, exist_ok=True)

    if not clusters_dir.exists():
        print("  no clusters; run --stages cluster first")
        return

    cluster_files = sorted(clusters_dir.glob("clust_*.yaml"))
    clusters = [_load(p) for p in cluster_files]

    enrichments: dict[str, dict] = {}
    if enrich_dir.exists():
        for p in enrich_dir.glob("clust_*.yaml"):
            e = _load(p)
            if isinstance(e, dict) and e.get("cluster_id") and e.get("enrichment_status") == "ok":
                enrichments[e["cluster_id"]] = e

    candidate_clusters = [c for c in clusters if c["cluster_id"] in enrichments]
    if not candidate_clusters:
        print("  no clusters with successful enrichment; run --stages enrich first")
        return

    already = {p.stem for p in scores_dir.glob("clust_*.yaml")}
    pending = [c for c in candidate_clusters if c["cluster_id"] not in already]
    print(
        f"  {len(candidate_clusters)} enriched clusters; "
        f"{len(pending)} pending to score "
        f"(skipping {len(candidate_clusters) - len(pending)} already scored)"
    )

    prompt_template = Path(prompt_file).read_text()
    client = Anthropic()

    for c in pending:
        cid = c["cluster_id"]
        record = _score_one(
            client, model, temperature, max_tokens,
            prompt_template, c, enrichments[cid], weights, kill_criteria,
        )
        with (scores_dir / f"{cid}.yaml").open("w") as f:
            yaml.safe_dump(record, f, sort_keys=False, allow_unicode=True)
        print(
            f"    {cid}: total={record.get('weighted_total','?')} "
            f"status={record.get('status','?')}"
            + (f" (killed: {', '.join(record.get('kill_reasons', []))})" if record.get("status") == "killed" else "")
        )

    _write_ranking(scores_dir, rdir.name, weights)


def _score_one(client, model, temperature, max_tokens, prompt_template,
               cluster, enrichment, weights, kill_criteria) -> dict:
    cid = cluster["cluster_id"]
    metrics = cluster.get("metrics") or {}
    summary = (cluster.get("cluster_summary") or "").strip()
    summary_indented = "\n".join("  " + line for line in summary.splitlines())

    # Trim enrichment to keep prompt manageable
    competitors = enrichment.get("direct_competitors") or []
    if isinstance(competitors, list):
        competitors = competitors[:5]

    context = {
        "direct_competitors": competitors,
        "competitor_pricing": enrichment.get("competitor_pricing"),
        "competitor_weaknesses": enrichment.get("competitor_weaknesses"),
        "market_size_estimate": enrichment.get("market_size_estimate"),
        "search_demand": enrichment.get("search_demand"),
        "funding_activity": enrichment.get("funding_activity"),
        "regulatory_context": enrichment.get("regulatory_context"),
        "distribution_channels": enrichment.get("distribution_channels"),
    }
    context = {k: v for k, v in context.items() if v}

    user_msg = (
        prompt_template
        + "\n\n---\n\n## Cluster to score\n\n"
        + f"cluster_id: {cid}\n"
        + f"cluster_label: {cluster.get('cluster_label')}\n"
        + f"cluster_summary: |\n{summary_indented}\n\n"
        + "### Stage-3 signal metrics\n\n"
        + f"primary_signal_count: {metrics.get('primary_signal_count', 0)}\n"
        + f"total_signal_count: {metrics.get('total_signal_count', 0)}\n"
        + f"source_diversity: {metrics.get('source_diversity', 0)}\n"
        + f"context_diversity: {metrics.get('context_diversity', 0)}\n"
        + f"workaround_count: {metrics.get('workaround_count', 0)}\n"
        + f"spend_evidence_count: {metrics.get('spend_evidence_count', 0)}\n"
        + f"intensity_mean: {metrics.get('intensity_mean')}\n"
        + f"temporal_trend: {metrics.get('temporal_trend')}\n"
        + f"competitor_mentions: {list((metrics.get('competitor_mentions') or {}).keys())[:10]}\n\n"
        + "### Stage-4 enrichment\n\n"
        + yaml.safe_dump(context, sort_keys=False, default_flow_style=False, allow_unicode=True)
    )

    try:
        resp = client.messages.create(
            model=model, max_tokens=max_tokens, temperature=temperature,
            messages=[{"role": "user", "content": user_msg}],
        )
    except APIError as e:
        return {"cluster_id": cid, "cluster_label": cluster.get("cluster_label"),
                "status": "api_error", "error": str(e), "scoring_model": model}

    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    m = _YAML_FENCE.search(text)
    body = m.group(1) if m else text
    try:
        parsed = yaml.safe_load(body)
        if not isinstance(parsed, dict):
            raise ValueError("non-dict")
    except Exception as e:
        return {"cluster_id": cid, "cluster_label": cluster.get("cluster_label"),
                "status": "parse_error", "parse_error": str(e),
                "raw_response": text[:2000], "scoring_model": model}

    scores = parsed.get("scores") or {}
    weighted_total = 0.0
    for crit in CRITERIA:
        s = scores.get(crit)
        if isinstance(s, dict):
            v = s.get("value")
            if isinstance(v, (int, float)):
                weighted_total += float(v) * float(weights.get(crit, 0))

    kill_reasons = _check_kill(cluster, scores, kill_criteria)
    return {
        "cluster_id": cid,
        "cluster_label": cluster.get("cluster_label"),
        "scores": scores,
        "weighted_total": round(weighted_total, 3),
        "status": "killed" if kill_reasons else "scored",
        "kill_reasons": kill_reasons,
        "scoring_model": model,
    }


def _check_kill(cluster: dict, scores: dict, kill_criteria: dict) -> list[str]:
    reasons: list[str] = []
    metrics = cluster.get("metrics") or {}
    if "min_signal_count" in kill_criteria:
        if metrics.get("primary_signal_count", 0) < int(kill_criteria["min_signal_count"]):
            reasons.append(f"primary_signal_count {metrics.get('primary_signal_count', 0)} < {kill_criteria['min_signal_count']}")
    if "min_source_diversity" in kill_criteria:
        if metrics.get("source_diversity", 0) < int(kill_criteria["min_source_diversity"]):
            reasons.append(f"source_diversity {metrics.get('source_diversity', 0)} < {kill_criteria['min_source_diversity']}")
    if "min_feasibility" in kill_criteria:
        fs = scores.get("solo_feasibility")
        v = fs.get("value") if isinstance(fs, dict) else None
        if isinstance(v, (int, float)) and v < int(kill_criteria["min_feasibility"]):
            reasons.append(f"solo_feasibility {v} < {kill_criteria['min_feasibility']}")
    return reasons


def _write_ranking(scores_dir: Path, run_id: str, weights: dict) -> None:
    records = [_load(p) for p in sorted(scores_dir.glob("clust_*.yaml"))]
    records = [r for r in records if isinstance(r, dict)]
    records.sort(key=lambda r: -(r.get("weighted_total") or 0.0))

    ranking = {
        "run_id": run_id,
        "weights": weights,
        "scored_count": sum(1 for r in records if r.get("status") == "scored"),
        "killed_count": sum(1 for r in records if r.get("status") == "killed"),
        "error_count": sum(1 for r in records if r.get("status") in ("api_error", "parse_error")),
        "clusters": [
            {
                "cluster_id": r["cluster_id"],
                "cluster_label": r.get("cluster_label"),
                "weighted_total": r.get("weighted_total"),
                "status": r.get("status"),
                "kill_reasons": r.get("kill_reasons") or [],
            }
            for r in records
        ],
    }
    with (scores_dir / "ranking.yaml").open("w") as f:
        yaml.safe_dump(ranking, f, sort_keys=False, allow_unicode=True)


def _load(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f) or {}
