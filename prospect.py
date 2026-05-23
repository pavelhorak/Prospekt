"""Prospect — pipeline engine.

Turns internet pain signals into ranked business opportunities.
Frozen in this file:
  * the six pipeline stages (ingest, tag, cluster, enrich, score, model),
  * the composite-metric weights and formulas (DESIGN.md §4),
  * the CLI surface.
The autoresearch loop tunes pipeline.yaml and prompts/, never this file.
See DESIGN.md §3 and §6.3 for the rationale.

Scaffold status: I/O conventions, directory layout, and the pure-math
metric functions are implemented. Stages that require an LLM or external
APIs are stubbed and raise NotImplementedError.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import math
import pathlib
import sys
import uuid
from typing import Any, Callable

import yaml

# ---------------------------------------------------------------------------
# Frozen composite-metric weights (DESIGN.md §4).
# Changing these requires a human-edited bump and a calibration re-baseline,
# because longitudinal comparisons of pipeline_score depend on them.
# ---------------------------------------------------------------------------

PIPELINE_SCORE_WEIGHTS: dict[str, float] = {
    "ingest_quality":     0.15,
    "tag_quality":        0.20,
    "cluster_quality":    0.25,
    "enrichment_quality": 0.15,
    "score_quality":      0.15,
    "model_quality":      0.10,
}
assert abs(sum(PIPELINE_SCORE_WEIGHTS.values()) - 1.0) < 1e-9, (
    "PIPELINE_SCORE_WEIGHTS must sum to 1.0"
)

ROOT = pathlib.Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# IDs and paths
# ---------------------------------------------------------------------------

def utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def new_run_id() -> str:
    return utcnow().strftime("%Y-%m-%dT%H-%M-%S")


def new_signal_id() -> str:
    return "sig_" + uuid.uuid4().hex[:12]


def run_dir(run_id: str) -> pathlib.Path:
    return ROOT / "runs" / run_id


def latest_run_id() -> str | None:
    runs = sorted(p.name for p in (ROOT / "runs").iterdir() if p.is_dir())
    return runs[-1] if runs else None


# ---------------------------------------------------------------------------
# YAML I/O
# ---------------------------------------------------------------------------

def read_yaml(path: pathlib.Path) -> Any:
    with path.open() as f:
        return yaml.safe_load(f)


def write_yaml(path: pathlib.Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


# ---------------------------------------------------------------------------
# Pure metric functions (DESIGN.md §4).
# These are testable without any external dependencies.
# ---------------------------------------------------------------------------

def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def freshness_score(fraction_within_12_months: float) -> float:
    f = fraction_within_12_months
    if 0.5 <= f <= 0.7:
        return 1.0
    if f < 0.5:
        return f / 0.5
    return max(0.0, 1.0 - (f - 0.7) / 0.3)


def duplication_score(fraction_duplicated: float) -> float:
    d = fraction_duplicated
    if d <= 0.05:
        return 1.0
    if d <= 0.15:
        return 1.0 - (d - 0.05) / 0.10
    return 0.0


def ingest_quality(s: dict) -> float:
    return mean([
        min(s["coverage"] / 10, 1.0),
        min(s["volume"] / 500, 1.0),
        s["schema_completeness"],
        freshness_score(s["fraction_within_12_months"]),
        duplication_score(s["fraction_duplicated"]),
    ])


def intensity_distribution_health(histogram: dict[int, int]) -> float:
    """Normalized entropy of a 1–5 pain-intensity histogram."""
    total = sum(histogram.values())
    if total == 0:
        return 0.0
    probs = [histogram.get(k, 0) / total for k in (1, 2, 3, 4, 5)]
    entropy = -sum(p * math.log2(p) for p in probs if p > 0)
    return entropy / math.log2(5)  # max entropy across 5 bins


def cluster_count_health(count: int) -> float:
    if 15 <= count <= 50:
        return 1.0
    if count < 5 or count > 100:
        return 0.0
    if count < 15:
        return (count - 5) / 10
    return max(0.0, 1.0 - (count - 50) / 50)


def size_distribution_health(sizes: list[int]) -> float:
    """Maps Gini coefficient of cluster sizes onto a power-law-target score."""
    g = gini(sizes)
    if 0.4 <= g <= 0.7:
        return 1.0
    if g < 0.4:
        return g / 0.4
    return max(0.0, 1.0 - (g - 0.7) / 0.3)


def gini(xs: list[int]) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    n = len(xs)
    cum = sum((i + 1) * x for i, x in enumerate(xs))
    s = sum(xs)
    if s == 0:
        return 0.0
    return (2 * cum) / (n * s) - (n + 1) / n


def overlap_health(overlap_rate: float) -> float:
    """5–20% cross-cluster overlap is ideal."""
    if 0.05 <= overlap_rate <= 0.20:
        return 1.0
    if overlap_rate < 0.05:
        return overlap_rate / 0.05
    return max(0.0, 1.0 - (overlap_rate - 0.20) / 0.30)


def tag_quality(s: dict) -> float:
    return mean([
        s["tag_coverage"],
        intensity_distribution_health(s["intensity_histogram"]),
        s["workaround_precision"],   # from auditor; see DESIGN §4
        s["spend_precision"],        # from auditor; see DESIGN §4
    ])


def cluster_quality(s: dict) -> float:
    return mean([
        s["coherence_score"],        # from auditor
        1.0 - clamp(s["orphan_rate"], 0.0, 0.4),
        cluster_count_health(s["cluster_count"]),
        size_distribution_health(s["sizes"]),
        s["cross_platform_rate"],
        overlap_health(s["overlap_rate"]),
    ])


def enrichment_quality(s: dict) -> float:
    return mean([
        s["avg_completeness"] / 8,
        s["competitor_discovery_rate"],
        s["pricing_availability"],
        s["data_recency_score"],
    ])


def score_quality(s: dict) -> float:
    return mean([
        s["evidence_linkage"],
        s["range_utilization"],
        s["confidence_coverage"],
    ])


def model_quality(s: dict) -> float:
    spread = s["scenario_spread"]
    spread_health = 1.0 if 2.0 <= spread <= 5.0 else 0.0
    return mean([
        s["input_traceability"],
        spread_health,
        1.0 if s["conservative_viable"] else 0.0,
        1.0 if s["sensitivity_identified"] else 0.0,
    ])


def backtest_multiplier(b: dict | None) -> float:
    if not b:
        return 1.0
    return 0.5 + (
        0.20 * clamp(b["separation"] / 2.0, 0, 1)
        + 0.30 * b["top3_precision"]
        + 0.25 * b["bottom3_precision"]
        + 0.15 * b["kill_sensitivity"]
        + 0.10 * b["signal_presence"]
    )


def pipeline_score(components: dict, mult: float = 1.0) -> float:
    return mult * sum(components[k] * w for k, w in PIPELINE_SCORE_WEIGHTS.items())


# ---------------------------------------------------------------------------
# Pipeline stages (DESIGN.md §7).
# Each stage reads from previous-stage output in the run directory and writes
# to its own subdir. The contract is documented inline; LLM/network logic is
# stubbed pending Stage-specific implementations.
# ---------------------------------------------------------------------------

def _walk_prior_source_urls() -> set[str]:
    """Read source_url from every signal in every prior run for dedup."""
    urls: set[str] = set()
    runs = ROOT / "runs"
    if not runs.exists():
        return urls
    for sig_file in runs.glob("*/signals/*/sig_*.yaml"):
        try:
            d = read_yaml(sig_file)
            if isinstance(d, dict) and "source_url" in d:
                urls.add(d["source_url"])
        except Exception:
            continue
    return urls


def stage_ingest(config: dict, rid: str) -> None:
    """Collect signals from each configured source.

    Skips URLs already present in any prior runs/*/signals/*.yaml.
    Writes one YAML per signal under runs/{rid}/signals/{platform}/
    plus runs/{rid}/signals/index.yaml.
    """
    from dataclasses import asdict
    from adapters import ADAPTERS

    sources = (config.get("ingest") or {}).get("sources") or {}
    if not sources:
        print("  no sources configured")
        return

    seen_urls = _walk_prior_source_urls()
    rdir = run_dir(rid)
    counts: dict[str, int] = {}

    for name, cfg in sources.items():
        if name not in ADAPTERS:
            print(f"  skip: no adapter for '{name}'")
            continue
        print(f"  fetching {name}...")
        n = 0
        for sig in ADAPTERS[name](cfg or {}, seen_urls):
            out = rdir / "signals" / name / f"{sig.signal_id}.yaml"
            write_yaml(out, asdict(sig))
            n += 1
        counts[name] = n
        print(f"    {name}: {n} new signals")

    write_yaml(rdir / "signals" / "index.yaml", {
        "run_id": rid,
        "collected_at": utcnow().isoformat(timespec="seconds").replace("+00:00", "Z"),
        "total": sum(counts.values()),
        "by_source": counts,
    })


def stage_tag(config: dict, rid: str) -> None:
    """Tag signals via Claude using prompts/tagging.md.

    See tagger.py for batching, resume-from-tagged, and parse logic.
    Requires ANTHROPIC_API_KEY in env.
    """
    from tagger import tag_signals
    tag_signals(config, run_dir(rid))


def stage_cluster(config: dict, rid: str) -> None:
    """Embed → HDBSCAN → merge → LLM-label → cross-assign → metrics.

    See DESIGN.md §7 Stage 3 for the contract. Known failure modes:

    - Style-based clustering. Text embeddings often separate by register
      (G2 prose vs Reddit rant vs Upwork spec) before topic. Mitigation:
      consider BAAI/bge-large-en-v1.5 over all-MiniLM-L6-v2; calibrate
      via the cold-context coherence auditor.
    - Long-tail starvation. min_cluster_size=3 buries niche pains that
      are often the most defensible solo-founder opportunities.
      Mitigation: optional second pass at min_cluster_size=2 on the
      orphan pool, emitted as a separate long_tail cluster set.
    - Label hallucination. LLM is biased toward producing a confident
      label even for incoherent groups. The INCOHERENT escape hatch in
      prompts/clustering.md helps; for clusters with coherence_score
      < 0.6 the recommended response is re-cluster-members-and-replace.
    - Cross-assignment runaway. Without the membership cap (see contract)
      popular clusters absorb semantically-nearby signals, inflating
      signal_count past honest demand evidence.
    - Embedding-model swap silently invalidates longitudinal comparisons.
      Always record embedding_model in metrics.yaml; flag changes in the
      improvement chart.
    """
    from clusterer import cluster_signals
    cluster_signals(config, run_dir(rid))


def stage_enrich(config: dict, rid: str) -> None:
    """Enrich triggered clusters via Claude + web_search.

    See enricher.py. Requires ANTHROPIC_API_KEY.
    """
    from enricher import enrich_clusters
    enrich_clusters(config, run_dir(rid))


def stage_score(config: dict, rid: str) -> None:
    """7-criterion scoring of enriched clusters via Claude."""
    from scorer import score_clusters
    score_clusters(config, run_dir(rid))


def stage_model(config: dict, rid: str) -> None:
    """3-scenario MRR projection for top-N scored clusters (pure Python)."""
    from modeler import model_clusters
    model_clusters(config, run_dir(rid))


STAGES: dict[str, Callable[[dict, str], None]] = {
    "ingest":  stage_ingest,
    "tag":     stage_tag,
    "cluster": stage_cluster,
    "enrich":  stage_enrich,
    "score":   stage_score,
    "model":   stage_model,
}


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

def cmd_init(_args: argparse.Namespace) -> None:
    """Bootstrap the on-disk layout. Idempotent."""
    for d in (
        "runs",
        "backtests/cases", "backtests/runs", "backtests/results",
        "forward_tests",
        "calibration",
        "prompts",
    ):
        (ROOT / d).mkdir(parents=True, exist_ok=True)
        keep = ROOT / d / ".gitkeep"
        if not any((ROOT / d).iterdir()):
            keep.touch()

    cal = ROOT / "calibration"
    if not (cal / "history.yaml").exists():
        write_yaml(cal / "history.yaml", {"runs": []})
    if not (cal / "backtest_status.yaml").exists():
        write_yaml(cal / "backtest_status.yaml", {
            "last_backtest_id": None,
            "last_backtest_age_days": None,
            "last_backtest_passed": None,
        })
    if not (cal / "source_quality.yaml").exists():
        write_yaml(cal / "source_quality.yaml", {"sources": {}})
    if not (cal / "bias_log.yaml").exists():
        write_yaml(cal / "bias_log.yaml", {"entries": [], "per_criterion_bias": {}})
    if not (cal / "weight_history.yaml").exists():
        write_yaml(cal / "weight_history.yaml", {"changes": []})

    tsv = ROOT / "results.tsv"
    if not tsv.exists():
        tsv.write_text(
            "commit\tpipeline_score\ttag_quality\tcluster_quality\t"
            "backtest_mult\tstatus\tdescription\n"
        )

    print(f"prospect: layout ready at {ROOT}")


def _ts() -> str:
    return utcnow().isoformat(timespec="seconds").replace("+00:00", "Z")


def cmd_run(args: argparse.Namespace) -> None:
    config = read_yaml(ROOT / "pipeline.yaml")
    rid = args.run_id or new_run_id()
    rdir = run_dir(rid)
    rdir.mkdir(parents=True, exist_ok=True)
    run_record: dict = {
        "run_id": rid,
        "started_at": _ts(),
        "config_snapshot": config,
        "stages_run": [],
        "status": "in_progress",
    }
    write_yaml(rdir / "run.yaml", run_record)

    stages = args.stages.split(",") if args.stages else list(STAGES)
    for s in stages:
        if s not in STAGES:
            sys.exit(f"unknown stage: {s}")

    try:
        for s in stages:
            print(f"[{rid}] {s}")
            STAGES[s](config, rid)
            run_record["stages_run"].append(s)
            write_yaml(rdir / "run.yaml", run_record)
    except Exception as e:
        run_record["status"] = "failed"
        idx = len(run_record["stages_run"])
        run_record["failed_stage"] = stages[idx] if idx < len(stages) else "?"
        run_record["error"] = f"{type(e).__name__}: {e}"
        run_record["finished_at"] = _ts()
        write_yaml(rdir / "run.yaml", run_record)
        raise

    run_record["status"] = "completed"
    run_record["finished_at"] = _ts()
    write_yaml(rdir / "run.yaml", run_record)

    if args.eval:
        cmd_eval(argparse.Namespace(run_id=rid))


def cmd_eval(args: argparse.Namespace) -> None:
    """Compute pipeline_score for a run."""
    from evaluator import evaluate_run
    rid = getattr(args, "run_id", None) or latest_run_id()
    if not rid:
        sys.exit("no runs found; run `prospect run` first")
    run_audits = not getattr(args, "no_audits", False)
    metrics = evaluate_run(rid, ROOT, run_audits=run_audits)
    print(f"\nrun {rid}: pipeline_score = {metrics['pipeline_score']:.4f}")
    for k, v in metrics["components"].items():
        print(f"  {k:22s} {v:.4f}")
    print(f"  backtest_multiplier    {metrics['backtest_multiplier']:.4f}")


def cmd_chart(_args: argparse.Namespace) -> None:
    raise NotImplementedError("cmd_chart: render ASCII improvement chart")


def cmd_history(_args: argparse.Namespace) -> None:
    tsv = ROOT / "results.tsv"
    if not tsv.exists():
        sys.exit("results.tsv missing — run `prospect init` first")
    print(tsv.read_text(), end="")


def cmd_ranking(args: argparse.Namespace) -> None:
    """Show the ranked cluster table for a run — the 'outcome' view."""
    rid = getattr(args, "run_id", None) or latest_run_id()
    if not rid:
        sys.exit("no runs found")
    rdir = run_dir(rid)

    clusters = _load_all(rdir / "clusters", "clust_*.yaml")
    if not clusters:
        sys.exit(f"no clusters in {rid}")

    enrich = {e["cluster_id"]: e for e in _load_all(rdir / "enrichments", "clust_*.yaml") if "cluster_id" in e}
    scores = {s["cluster_id"]: s for s in _load_all(rdir / "scores", "clust_*.yaml") if "cluster_id" in s}
    models = {m["cluster_id"]: m for m in _load_all(rdir / "models", "clust_*.yaml") if "cluster_id" in m}

    rows = []
    for c in clusters:
        cid = c["cluster_id"]
        label = c.get("cluster_label") or ""
        if label in ("INCOHERENT", "ERROR", "PARSE_ERROR"):
            continue
        m = c.get("metrics") or {}
        e = enrich.get(cid)
        s = scores.get(cid)
        rows.append({
            "cid": cid,
            "label": label,
            "sigs": m.get("primary_signal_count", 0),
            "srcs": m.get("source_diversity", 0),
            "WAs": m.get("workaround_count", 0),
            "int": m.get("intensity_mean"),
            "enrich": (e or {}).get("enrichment_status") or "—",
            "score": (s or {}).get("weighted_total"),
            "modeled": "✓" if cid in models else "—",
        })

    # Sort: scored > enriched-ok > by primary_signal_count desc
    def key(r):
        sc = r["score"] if r["score"] is not None else -1
        en = 1 if r["enrich"] == "ok" else 0
        return (-sc, -en, -r["sigs"])
    rows.sort(key=key)

    rid_short = rid
    print(f"\nRANKED OPPORTUNITIES — run {rid_short}\n")
    print(f"{'cluster':<11}{'sigs':>6}{'srcs':>6}{'WAs':>5}{'int':>6}  {'enriched':<13}{'score':>7}  {'mdl':<4}label")
    print("-" * 110)
    for r in rows:
        intensity = f"{r['int']:.2f}" if r['int'] else "  — "
        score_str = f"{r['score']:.2f}" if r['score'] is not None else "  — "
        print(f"{r['cid']:<11}{r['sigs']:>6}{r['srcs']:>6}{r['WAs']:>5}{intensity:>6}  {r['enrich']:<13}{score_str:>7}  {r['modeled']:<4}{r['label'][:60]}")

    # Footer summary
    n_all = len(clusters)
    n_coherent = len(rows)
    n_enr_ok = sum(1 for v in enrich.values() if v.get("enrichment_status") == "ok")
    n_enr_err = sum(1 for v in enrich.values() if v.get("enrichment_status") not in (None, "ok"))
    n_scored = sum(1 for s in scores.values() if s.get("status") == "scored")
    metrics_yaml = _load_yaml_if_exists(rdir / "metrics.yaml") or {}
    score_value = metrics_yaml.get("pipeline_score")
    print(f"\n  total {n_all}  coherent {n_coherent}  enriched_ok {n_enr_ok}  enrich_err {n_enr_err}  scored {n_scored}  modeled {len(models)}")
    if score_value is not None:
        print(f"  pipeline_score: {score_value:.4f}")
    print()


def cmd_trace(args: argparse.Namespace) -> None:
    """Show full evidence chain for one cluster: signals → enrichment → score → model."""
    cid = args.cluster_id
    rid = getattr(args, "run_id", None) or latest_run_id()
    if not rid:
        sys.exit("no runs found")
    rdir = run_dir(rid)

    cluster_file = rdir / "clusters" / f"{cid}.yaml"
    if not cluster_file.exists():
        sys.exit(f"{cid} not found in {rid}")
    cluster = read_yaml(cluster_file)
    m = cluster.get("metrics") or {}

    print(f"\n{cid}  —  {cluster.get('cluster_label')}")
    print(f"fingerprint: {cluster.get('cluster_fingerprint')}")
    summary = (cluster.get("cluster_summary") or "").strip()
    if summary:
        print("\n" + summary + "\n")
    print(f"primary={m.get('primary_signal_count')}  total={m.get('total_signal_count')}  "
          f"sources={m.get('sources')}  intensity_mean={m.get('intensity_mean')}")
    print(f"workaround_count={m.get('workaround_count')}  spend_evidence_count={m.get('spend_evidence_count')}  "
          f"temporal_trend={m.get('temporal_trend')}")

    enrich_file = rdir / "enrichments" / f"{cid}.yaml"
    if enrich_file.exists():
        e = read_yaml(enrich_file)
        print(f"\n— enrichment ({e.get('enrichment_status')}) —")
        comps = e.get("direct_competitors") or []
        if isinstance(comps, list) and comps:
            print(f"competitors ({len(comps)}):")
            for c in comps[:5]:
                if isinstance(c, dict):
                    print(f"  - {c.get('name')}  ({c.get('founded_year','?')}, {c.get('funding','?')[:50] if c.get('funding') else '?'})")
        if e.get("market_size_estimate"):
            print(f"market_size: {e['market_size_estimate']}")
        cits = e.get("citations") or []
        if cits:
            print(f"citations: {len(cits)}")

    score_file = rdir / "scores" / f"{cid}.yaml"
    if score_file.exists():
        s = read_yaml(score_file)
        print(f"\n— scoring (status={s.get('status')}) —")
        if s.get("weighted_total") is not None:
            print(f"weighted_total: {s['weighted_total']}")
        for crit, sc in (s.get("scores") or {}).items():
            if isinstance(sc, dict):
                v = sc.get("value")
                conf = sc.get("confidence")
                print(f"  {crit:<20} {v}  ({conf})")

    model_file = rdir / "models" / f"{cid}.yaml"
    if model_file.exists():
        mod = read_yaml(model_file)
        print(f"\n— model —")
        for name, sc in (mod.get("scenarios") or {}).items():
            print(f"  {name:<14} m2target={sc.get('months_to_target')}  steady={sc.get('steady_state_mrr')}  viable={sc.get('viable')}")
    print()


def _load_all(directory: pathlib.Path, glob_: str) -> list[dict]:
    if not directory.exists():
        return []
    out = []
    for p in sorted(directory.glob(glob_)):
        try:
            with p.open() as f:
                d = yaml.safe_load(f)
            if isinstance(d, dict):
                out.append(d)
        except Exception:
            continue
    return out


def _load_yaml_if_exists(path: pathlib.Path):
    if not path.exists():
        return None
    with path.open() as f:
        return yaml.safe_load(f)


_NOT_YET = lambda name: lambda _a: (_ for _ in ()).throw(
    NotImplementedError(f"cmd_{name}: not yet wired")
)


COMMANDS: dict[str, Callable[[argparse.Namespace], None]] = {
    "init":         cmd_init,
    "run":          cmd_run,
    "eval":         cmd_eval,
    "chart":        cmd_chart,
    "history":      cmd_history,
    "ranking":      cmd_ranking,
    "trace":        cmd_trace,
    # stubbed:
    "loop":         _NOT_YET("loop"),
    "signals":      _NOT_YET("signals"),
    "clusters":     _NOT_YET("clusters"),
    "cluster":      _NOT_YET("cluster"),
    "backtest":     _NOT_YET("backtest"),
    "forward-test": _NOT_YET("forward-test"),
    "calibrate":    _NOT_YET("calibrate"),
    "source-quality": _NOT_YET("source-quality"),
    "diff":         _NOT_YET("diff"),
}


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="prospect")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create directory layout")

    run_p = sub.add_parser("run", help="execute pipeline stages")
    run_p.add_argument("--stages", help="comma-separated stage subset")
    run_p.add_argument("--run-id", dest="run_id")
    run_p.add_argument("--eval", action="store_true")

    eval_p = sub.add_parser("eval", help="compute metrics for a run")
    eval_p.add_argument("--run-id", dest="run_id", help="defaults to latest")
    eval_p.add_argument("--no-audits", action="store_true",
                        help="skip cold-context auditors (no API calls)")
    sub.add_parser("chart", help="render improvement chart")
    sub.add_parser("history", help="print results.tsv")

    rank_p = sub.add_parser("ranking", help="ranked cluster outcome for a run")
    rank_p.add_argument("--run-id", dest="run_id", help="defaults to latest")

    trace_p = sub.add_parser("trace", help="show evidence chain for one cluster")
    trace_p.add_argument("cluster_id")
    trace_p.add_argument("--run-id", dest="run_id", help="defaults to latest")

    for name in COMMANDS:
        if name in {"init", "run", "eval", "chart", "history", "ranking", "trace"}:
            continue
        sub.add_parser(name, help="(stub)")

    args = p.parse_args(argv)
    COMMANDS[args.cmd](args)


if __name__ == "__main__":
    main()
