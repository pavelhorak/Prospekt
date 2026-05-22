"""cmd_eval — compute pipeline_score against a run directory (DESIGN.md §4).

Walks runs/{rid}/ for signals, tags, clusters, enrichments. Computes each
component score using the pure math functions in prospect.py. Cold-context
audits (workaround_precision, spend_precision, coherence_score) are run
only when ANTHROPIC_API_KEY is set; otherwise the components are computed
without them and metrics.yaml records `audits_skipped: true`.

Score / model components default to 0.0 since stage_score and stage_model
aren't wired yet — honest representation of an incomplete pipeline.

Writes:
- runs/{rid}/metrics.yaml
- calibration/history.yaml (appended)
- results.tsv (appended)
"""

from __future__ import annotations

import datetime as _dt
import os
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

import prospect as P


def evaluate_run(rid: str, root: Path, run_audits: bool = True) -> dict:
    rdir = root / "runs" / rid
    if not rdir.exists():
        raise RuntimeError(f"run not found: {rid}")

    config = yaml.safe_load((root / "pipeline.yaml").read_text()) if (root / "pipeline.yaml").exists() else {}
    audit_cfg = config.get("audit") or {}

    # --- Stage 1: Ingest -----------------------------------------------------
    signals = _load_dir(rdir / "signals", glob_="*/sig_*.yaml")
    ingest_stats = _ingest_stats(signals)
    iq = P.ingest_quality(ingest_stats) if signals else 0.0

    # --- Stage 2: Tag --------------------------------------------------------
    tags = _load_dir(rdir / "tags", glob_="sig_*.yaml")
    tag_stats: dict[str, Any] | None = None
    audits_attempted = False
    audits_ok = False
    if tags:
        tag_stats = _tag_stats(tags)
        wp: float | None = None
        sp: float | None = None
        if run_audits and os.environ.get("ANTHROPIC_API_KEY"):
            audits_attempted = True
            try:
                from auditor import audit_tag_precision
                wp = audit_tag_precision(tags, signals, "has_workaround", audit_cfg)
                sp = audit_tag_precision(tags, signals, "has_spend", audit_cfg)
                audits_ok = True
            except Exception as e:
                print(f"  tag audits failed: {e}; using 0.0 placeholders")
        tag_stats["workaround_precision"] = wp if wp is not None else 0.0
        tag_stats["spend_precision"] = sp if sp is not None else 0.0
        # intensity_histogram → intensity_distribution_health is computed inside tag_quality
        tag_stats_for_metric = dict(tag_stats)
        # tag_quality expects "intensity_histogram"
        tq = P.tag_quality(tag_stats_for_metric)
    else:
        tq = 0.0

    # --- Stage 3: Cluster ----------------------------------------------------
    clusters = _load_dir(rdir / "clusters", glob_="clust_*.yaml")
    cluster_index = _load_yaml(rdir / "clusters" / "index.yaml") if (rdir / "clusters" / "index.yaml").exists() else None
    cluster_stats: dict[str, Any] | None = None
    if clusters:
        cluster_stats = _cluster_stats(clusters, cluster_index, signals)
        coh: float | None = None
        if run_audits and os.environ.get("ANTHROPIC_API_KEY"):
            try:
                from auditor import audit_cluster_coherence
                coh = audit_cluster_coherence(clusters, signals, audit_cfg)
                audits_attempted = True
                audits_ok = True
            except Exception as e:
                print(f"  cluster coherence audit failed: {e}; using 0.0 placeholder")
        cluster_stats["coherence_score"] = coh if coh is not None else 0.0
        cq = P.cluster_quality(cluster_stats)
    else:
        cq = 0.0

    # --- Stage 4: Enrich -----------------------------------------------------
    enrichments = _load_dir(rdir / "enrichments", glob_="clust_*.yaml")
    enrich_stats = _enrich_stats(enrichments) if enrichments else None
    eq = P.enrichment_quality(enrich_stats) if enrich_stats else 0.0

    # --- Stage 5: Score ------------------------------------------------------
    score_files = _load_dir(rdir / "scores", glob_="clust_*.yaml")
    score_stats = _score_stats(score_files) if score_files else None
    sq = P.score_quality(score_stats) if score_stats else 0.0

    # --- Stage 6: Model ------------------------------------------------------
    model_files = _load_dir(rdir / "models", glob_="clust_*.yaml")
    model_stats = _model_stats(model_files) if model_files else None
    mq = P.model_quality(model_stats) if model_stats else 0.0

    # --- Backtest multiplier -------------------------------------------------
    bt_status = _load_yaml(root / "calibration" / "backtest_status.yaml") if (root / "calibration" / "backtest_status.yaml").exists() else None
    if bt_status and bt_status.get("last_backtest_passed") is True:
        latest_results = bt_status.get("latest_results")
        bt_mult = P.backtest_multiplier(latest_results) if latest_results else 1.0
    else:
        bt_mult = 1.0  # neutral — no backtest yet

    components = {
        "ingest_quality": iq,
        "tag_quality": tq,
        "cluster_quality": cq,
        "enrichment_quality": eq,
        "score_quality": sq,
        "model_quality": mq,
    }
    score = P.pipeline_score(components, bt_mult)

    metrics = {
        "run_id": rid,
        "computed_at": _ts(),
        "pipeline_score": round(score, 4),
        "components": {k: round(v, 4) for k, v in components.items()},
        "backtest_multiplier": round(bt_mult, 4),
        "stage_details": {
            "ingest": ingest_stats if signals else {"status": "no_signals"},
            "tag": tag_stats if tag_stats else {"status": "no_tags"},
            "cluster": cluster_stats if cluster_stats else {"status": "no_clusters"},
            "enrich": enrich_stats if enrich_stats else {"status": "no_enrichments"},
            "score": score_stats if score_stats else {"status": "no_scores"},
            "model": model_stats if model_stats else {"status": "no_models"},
        },
        "audits": {
            "attempted": audits_attempted,
            "succeeded": audits_ok,
            "skipped_reason": (
                None if audits_attempted else
                "ANTHROPIC_API_KEY not set" if not os.environ.get("ANTHROPIC_API_KEY") else
                "no tags/clusters to audit"
            ),
        },
    }

    with (rdir / "metrics.yaml").open("w") as f:
        yaml.safe_dump(metrics, f, sort_keys=False, allow_unicode=True)

    # Append to calibration/history.yaml
    hist_path = root / "calibration" / "history.yaml"
    history = _load_yaml(hist_path) or {"runs": []}
    history.setdefault("runs", []).append({
        "run_id": rid,
        "pipeline_score": metrics["pipeline_score"],
        "components": metrics["components"],
        "computed_at": metrics["computed_at"],
        "config_hash": _config_hash(config),
    })
    with hist_path.open("w") as f:
        yaml.safe_dump(history, f, sort_keys=False)

    # Append to results.tsv
    tsv = root / "results.tsv"
    if not tsv.exists():
        tsv.write_text("commit\tpipeline_score\ttag_quality\tcluster_quality\tbacktest_mult\tstatus\tdescription\n")
    commit = _git_commit(root)
    with tsv.open("a") as f:
        f.write(
            f"{commit}\t{metrics['pipeline_score']:.4f}\t"
            f"{components['tag_quality']:.4f}\t{components['cluster_quality']:.4f}\t"
            f"{bt_mult:.4f}\teval\trun_id={rid}\n"
        )

    return metrics


# ---------------------------------------------------------------------------
# Per-stage stat builders
# ---------------------------------------------------------------------------

def _ingest_stats(signals: list[dict]) -> dict:
    if not signals:
        return {
            "volume": 0, "coverage": 0, "schema_completeness": 0.0,
            "fraction_within_12_months": 0.0, "fraction_duplicated": 0.0,
        }
    platforms = {s.get("source_platform") for s in signals if s.get("source_platform")}
    required = ["raw_text", "source_url", "source_platform", "date_posted"]
    full = sum(1 for s in signals if all(s.get(k) for k in required))

    today = _dt.date.today()
    twelve_months_ago = today - _dt.timedelta(days=365)
    recent = 0
    dated = 0
    for s in signals:
        d = s.get("date_posted")
        if not d:
            continue
        try:
            dp = _dt.date.fromisoformat(d)
            dated += 1
            if dp >= twelve_months_ago:
                recent += 1
        except (ValueError, TypeError):
            continue
    urls = [s.get("source_url") for s in signals if s.get("source_url")]
    dup = len(urls) - len(set(urls))

    return {
        "volume": len(signals),
        "coverage": len(platforms),
        "schema_completeness": round(full / len(signals), 3),
        "fraction_within_12_months": round(recent / dated, 3) if dated else 0.0,
        "fraction_duplicated": round(dup / len(urls), 3) if urls else 0.0,
        "platforms": sorted(platforms),
        "signals_with_date": dated,
    }


def _tag_stats(tags: list[dict]) -> dict:
    pain_types: list[str] = []
    intensities: list[int] = []
    for t in tags:
        td = t.get("tags") or {}
        pt = td.get("pain_type")
        if isinstance(pt, dict):
            v = pt.get("value")
            if v:
                pain_types.append(str(v))
        pi = td.get("pain_intensity")
        if isinstance(pi, dict):
            v = pi.get("value")
            if isinstance(v, (int, float)):
                intensities.append(int(v))
    tag_coverage = (
        sum(1 for p in pain_types if p and p != "unknown") / len(pain_types)
        if pain_types else 0.0
    )
    return {
        "n_tagged": len(tags),
        "tag_coverage": round(tag_coverage, 3),
        "intensity_histogram": dict(Counter(intensities)),
    }


def _cluster_stats(clusters: list[dict], index: dict | None, signals: list[dict]) -> dict:
    n_clusters = len(clusters)
    sizes = [(c.get("metrics") or {}).get("primary_signal_count", 0) for c in clusters]
    orphan_rate = float((index or {}).get("orphan_rate") or 0.0)

    top10 = sorted(
        clusters,
        key=lambda c: -(c.get("metrics") or {}).get("primary_signal_count", 0),
    )[:10]
    if top10:
        cp = sum(
            1 for c in top10
            if (c.get("metrics") or {}).get("context_diversity", 0) > 2
        ) / len(top10)
    else:
        cp = 0.0

    membership_count: Counter = Counter()
    for c in clusters:
        for sid in c.get("all_signal_ids", []):
            membership_count[sid] += 1
    multi = sum(1 for n in membership_count.values() if n > 1)
    n_signals = len(signals) or sum(sizes)
    overlap_rate = (multi / n_signals) if n_signals else 0.0

    return {
        "n_clusters": n_clusters,
        "cluster_count": n_clusters,
        "sizes": sizes,
        "orphan_rate": round(orphan_rate, 3),
        "cross_platform_rate": round(cp, 3),
        "overlap_rate": round(overlap_rate, 3),
    }


_CRITERIA = [
    "market_demand", "distribution", "competition", "founder_market_fit",
    "solo_feasibility", "revenue_path", "defensibility",
]


def _score_stats(score_records: list[dict]) -> dict:
    scored = [r for r in score_records if r.get("status") == "scored"]
    all_values: list[int] = []
    linked = 0
    total_criteria = 0
    for r in scored:
        scores = r.get("scores") or {}
        for crit in _CRITERIA:
            s = scores.get(crit)
            if not isinstance(s, dict):
                continue
            total_criteria += 1
            v = s.get("value")
            if isinstance(v, (int, float)):
                all_values.append(int(v))
            ev = s.get("evidence")
            if ev:  # any non-empty evidence (list, dict, or str)
                linked += 1
    evidence_linkage = (linked / total_criteria) if total_criteria else 0.0

    # range_utilization = entropy of the 1–5 value distribution / max entropy
    import math
    if all_values:
        hist = Counter(all_values)
        n = len(all_values)
        probs = [hist.get(k, 0) / n for k in (1, 2, 3, 4, 5)]
        entropy = -sum(p * math.log2(p) for p in probs if p > 0)
        range_util = entropy / math.log2(5)
    else:
        range_util = 0.0

    # confidence_coverage = % high-confidence in top-3 clusters' criterion scores
    scored_sorted = sorted(scored, key=lambda r: -(r.get("weighted_total") or 0))[:3]
    top_total = 0
    top_high = 0
    for r in scored_sorted:
        for crit in _CRITERIA:
            s = (r.get("scores") or {}).get(crit)
            if not isinstance(s, dict):
                continue
            top_total += 1
            if (s.get("confidence") or "").lower() == "high":
                top_high += 1
    confidence_coverage = (top_high / top_total) if top_total else 0.0

    return {
        "n_records": len(score_records),
        "n_scored": len(scored),
        "n_killed": sum(1 for r in score_records if r.get("status") == "killed"),
        "evidence_linkage": round(evidence_linkage, 3),
        "range_utilization": round(range_util, 3),
        "confidence_coverage": round(confidence_coverage, 3),
        "top_3_weighted_totals": [r.get("weighted_total") for r in scored_sorted],
    }


def _model_stats(model_records: list[dict]) -> dict:
    if not model_records:
        return {}
    # input_traceability: % inputs with a `sources.<key>` entry
    trace_num = 0
    trace_den = 0
    spreads: list[float] = []
    conservative_viable = 0
    sensitivity_found = 0
    for r in model_records:
        inputs = r.get("inputs") or {}
        sources = (inputs.get("sources") or {})
        for k in inputs:
            if k == "sources":
                continue
            trace_den += 1
            if k in sources:
                trace_num += 1
        scenarios = r.get("scenarios") or {}
        opt = (scenarios.get("optimistic") or {}).get("final_mrr") or 0
        cons = (scenarios.get("conservative") or {}).get("final_mrr") or 0
        if cons > 0:
            spreads.append(opt / cons)
        if (scenarios.get("conservative") or {}).get("viable"):
            conservative_viable += 1
        if (r.get("sensitivity") or {}).get("killing_input"):
            sensitivity_found += 1
    input_traceability = (trace_num / trace_den) if trace_den else 0.0
    avg_spread = sum(spreads) / len(spreads) if spreads else 0.0
    # scenario_spread used by P.model_quality directly
    return {
        "n_modeled": len(model_records),
        "input_traceability": round(input_traceability, 3),
        "scenario_spread": round(avg_spread, 2),
        "conservative_viable": conservative_viable == len(model_records) and len(model_records) > 0,
        "sensitivity_identified": sensitivity_found == len(model_records) and len(model_records) > 0,
        "conservative_viable_count": conservative_viable,
        "sensitivity_identified_count": sensitivity_found,
    }


_ENRICH_FIELDS = [
    "direct_competitors",
    "competitor_pricing",
    "competitor_weaknesses",
    "market_size_estimate",
    "search_demand",
    "funding_activity",
    "regulatory_context",
    "distribution_channels",
]


def _enrich_stats(enrichments: list[dict]) -> dict:
    n = len(enrichments)
    completeness: list[int] = []
    has_competitors_ge3: list[int] = []
    has_pricing: list[int] = []
    ok = 0
    for e in enrichments:
        if e.get("enrichment_status") == "ok":
            ok += 1
        filled = sum(1 for f in _ENRICH_FIELDS if e.get(f) not in (None, [], {}, ""))
        completeness.append(filled)
        comps = e.get("direct_competitors") or []
        if isinstance(comps, list):
            has_competitors_ge3.append(1 if len(comps) >= 3 else 0)
            has_pricing.append(
                1 if any(isinstance(c, dict) and c.get("pricing") for c in comps) else 0
            )
        else:
            has_competitors_ge3.append(0)
            has_pricing.append(0)
    return {
        "n_enriched": n,
        "n_ok": ok,
        "avg_completeness": round(sum(completeness) / max(n, 1), 2),
        "competitor_discovery_rate": round(sum(has_competitors_ge3) / max(n, 1), 3),
        "pricing_availability": round(sum(has_pricing) / max(n, 1), 3),
        "data_recency_score": 1.0,  # all just-fetched; refine when timestamps land
    }


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _load_yaml(path: Path):
    if not path.exists():
        return None
    with path.open() as f:
        return yaml.safe_load(f)


def _load_dir(directory: Path, glob_: str) -> list[dict]:
    if not directory.exists():
        return []
    out = []
    for p in sorted(directory.glob(glob_)):
        try:
            with p.open() as f:
                doc = yaml.safe_load(f)
                if isinstance(doc, dict):
                    out.append(doc)
        except Exception:
            continue
    return out


def _git_commit(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root, stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "uncommitted"


def _config_hash(config: dict) -> str:
    import hashlib
    h = hashlib.sha256(yaml.safe_dump(config, sort_keys=True).encode()).hexdigest()
    return h[:12]


def _ts() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
