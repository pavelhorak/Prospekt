"""Stage 6 modeler — 3-scenario MRR projection for top-scored clusters.

Pure-Python projection (no LLM). Frozen engine surface (DESIGN.md §3).
The agent tunes pipeline.yaml's modeling.* and the conservative/base/
optimistic input bands.

Per-scenario monthly model:
  MRR(m) = MRR(m-1) * (1 - churn) + new_per_month * ARPU
Reports:
  months_to_target_mrr   (None if never within horizon)
  months_to_profitability (when MRR > monthly_cost)
  steady_state_mrr        (new * ARPU / churn — algebraic limit)
  final_mrr               (MRR at horizon)

Inputs are derived from the upstream stages where possible — ARPU from
competitor pricing in enrichment, build_weeks from solo_feasibility
score, new_per_month from distribution score — with explicit `sources:`
tracking so input_traceability in evaluator can compute model_quality.

Sensitivity test: each of {arpu_halved, churn_doubled, new_customers_halved}
is applied to the conservative case to find which single input change
flips conservative viability. The first to flip is named the killing_input.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def model_clusters(config: dict, rdir: Path) -> None:
    mcfg = config.get("modeling") or {}
    top_n = int(mcfg.get("top_n", 3))
    monthly_cost = float(mcfg.get("monthly_cost", 600))
    target_mrr = float(mcfg.get("target_mrr", 10000))
    horizon = int(mcfg.get("horizon_months", 24))

    scores_dir = rdir / "scores"
    ranking_file = scores_dir / "ranking.yaml"
    if not ranking_file.exists():
        print("  no ranking.yaml; run --stages score first")
        return

    ranking = yaml.safe_load(ranking_file.read_text()) or {}
    scored = [c for c in (ranking.get("clusters") or []) if c.get("status") == "scored"]
    top = scored[:top_n]
    if not top:
        print("  no scored clusters to model")
        return

    models_dir = rdir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    clusters_dir = rdir / "clusters"
    enrich_dir = rdir / "enrichments"

    for entry in top:
        cid = entry["cluster_id"]
        cluster = yaml.safe_load((clusters_dir / f"{cid}.yaml").read_text())
        score = yaml.safe_load((scores_dir / f"{cid}.yaml").read_text())
        enrichment_path = enrich_dir / f"{cid}.yaml"
        enrichment = yaml.safe_load(enrichment_path.read_text()) if enrichment_path.exists() else {}

        inputs = _derive_inputs(cluster, enrichment, score)
        scenarios = _model_scenarios(inputs, monthly_cost, target_mrr, horizon)
        sensitivity = _identify_sensitivity(inputs, monthly_cost, target_mrr, horizon)
        risks = _enumerate_risks(cluster, enrichment, score)

        record = {
            "cluster_id": cid,
            "cluster_label": entry.get("cluster_label"),
            "weighted_total": entry.get("weighted_total"),
            "horizon_months": horizon,
            "target_mrr": target_mrr,
            "monthly_cost": monthly_cost,
            "inputs": inputs,
            "scenarios": scenarios,
            "sensitivity": sensitivity,
            "risk_factors": risks,
        }
        with (models_dir / f"{cid}.yaml").open("w") as f:
            yaml.safe_dump(record, f, sort_keys=False, allow_unicode=True)
        base = scenarios["base"]
        print(
            f"    {cid}: months_to_${int(target_mrr/1000)}k "
            f"= {base.get('months_to_target', 'never')}, "
            f"conservative_viable = {scenarios['conservative']['viable']}"
        )


# ---------------------------------------------------------------------------
# Input derivation
# ---------------------------------------------------------------------------

def _derive_inputs(cluster: dict, enrichment: dict, score: dict) -> dict:
    sources: dict[str, str] = {}

    # ARPU — median of competitor pricing tiers between $5 and $500/mo.
    competitors = enrichment.get("direct_competitors") or []
    prices: list[float] = []
    for c in competitors[:8] if isinstance(competitors, list) else []:
        if not isinstance(c, dict):
            continue
        pricing = c.get("pricing")
        tiers = pricing.get("tiers") if isinstance(pricing, dict) else None
        if not isinstance(tiers, list):
            continue
        for t in tiers:
            if not isinstance(t, dict):
                continue
            for k in ("price", "price_per_seat", "monthly_price", "amount"):
                v = t.get(k)
                if v is None:
                    continue
                try:
                    p = float(str(v).replace("$", "").replace(",", "").strip())
                except (ValueError, TypeError):
                    continue
                if 5 <= p <= 500:
                    prices.append(p)
                    break
    if prices:
        prices.sort()
        arpu_median = prices[len(prices) // 2]
        arpu_low = prices[0]
        arpu_high = prices[-1]
        sources["arpu"] = (
            f"median of {len(prices)} competitor pricing tier(s) from "
            f"enrichment.direct_competitors[*].pricing.tiers"
        )
    else:
        arpu_median, arpu_low, arpu_high = 30.0, 15.0, 60.0
        sources["arpu"] = "default $30 (no pricing tiers parsed from enrichment)"

    # Build weeks — from solo_feasibility score (1 → 16w, 5 → 4w)
    feas = (score.get("scores") or {}).get("solo_feasibility") or {}
    feas_v = feas.get("value") if isinstance(feas, dict) else None
    if isinstance(feas_v, (int, float)):
        build_weeks = max(2, int(16 - (feas_v - 1) * 3))
        sources["build_weeks"] = f"derived from solo_feasibility score = {feas_v}"
    else:
        build_weeks = 10
        sources["build_weeks"] = "default 10 (no solo_feasibility score)"

    # New customers / month — from distribution score (1 → 2/mo, 5 → 14/mo)
    dist = (score.get("scores") or {}).get("distribution") or {}
    dist_v = dist.get("value") if isinstance(dist, dict) else None
    if isinstance(dist_v, (int, float)):
        base_new = max(1, int(2 + (dist_v - 1) * 3))
        sources["base_new_customers"] = f"derived from distribution score = {dist_v}"
    else:
        base_new = 5
        sources["base_new_customers"] = "default 5/mo (no distribution score)"

    return {
        "arpu_low": arpu_low,
        "arpu_median": arpu_median,
        "arpu_high": arpu_high,
        "build_weeks": build_weeks,
        "base_new_customers": base_new,
        "sources": sources,
    }


# ---------------------------------------------------------------------------
# Projection math
# ---------------------------------------------------------------------------

def _project(arpu: float, churn: float, new_per_month: float, monthly_cost: float,
             target_mrr: float, horizon: int, start_month: int) -> dict:
    mrr = 0.0
    months_to_target: int | None = None
    months_to_profit: int | None = None
    series: list[dict] = []
    for m in range(horizon):
        if m < start_month:
            series.append({"month": m, "mrr": 0.0})
            continue
        mrr = mrr * (1 - churn) + new_per_month * arpu
        series.append({"month": m, "mrr": round(mrr, 2)})
        if months_to_target is None and mrr >= target_mrr:
            months_to_target = m
        if months_to_profit is None and mrr >= monthly_cost:
            months_to_profit = m

    steady_state = (new_per_month * arpu) / churn if churn > 0 else None
    return {
        "arpu": arpu,
        "monthly_churn": churn,
        "new_customers_per_month": new_per_month,
        "months_to_target": months_to_target,
        "months_to_profitability": months_to_profit,
        "steady_state_mrr": round(steady_state, 2) if steady_state else None,
        "final_mrr": round(mrr, 2),
        "viable": months_to_target is not None,
        "series": series,
    }


def _model_scenarios(inputs: dict, monthly_cost: float, target_mrr: float, horizon: int) -> dict:
    start = max(0, inputs["build_weeks"] // 4)
    base_new = inputs["base_new_customers"]
    return {
        "conservative": _project(
            arpu=inputs["arpu_low"], churn=0.08,
            new_per_month=max(1, base_new // 2),
            monthly_cost=monthly_cost, target_mrr=target_mrr,
            horizon=horizon, start_month=start,
        ),
        "base": _project(
            arpu=inputs["arpu_median"], churn=0.05,
            new_per_month=base_new,
            monthly_cost=monthly_cost, target_mrr=target_mrr,
            horizon=horizon, start_month=start,
        ),
        "optimistic": _project(
            arpu=inputs["arpu_high"], churn=0.03,
            new_per_month=base_new * 2,
            monthly_cost=monthly_cost, target_mrr=target_mrr,
            horizon=horizon, start_month=start,
        ),
    }


# ---------------------------------------------------------------------------
# Sensitivity
# ---------------------------------------------------------------------------

def _identify_sensitivity(inputs: dict, monthly_cost: float, target_mrr: float, horizon: int) -> dict:
    start = max(0, inputs["build_weeks"] // 4)
    base_new = max(1, inputs["base_new_customers"] // 2)
    base = _project(
        arpu=inputs["arpu_low"], churn=0.08, new_per_month=base_new,
        monthly_cost=monthly_cost, target_mrr=target_mrr,
        horizon=horizon, start_month=start,
    )

    perturbations = {
        "arpu_halved": _project(
            arpu=inputs["arpu_low"] / 2, churn=0.08, new_per_month=base_new,
            monthly_cost=monthly_cost, target_mrr=target_mrr,
            horizon=horizon, start_month=start,
        )["viable"],
        "churn_doubled": _project(
            arpu=inputs["arpu_low"], churn=0.16, new_per_month=base_new,
            monthly_cost=monthly_cost, target_mrr=target_mrr,
            horizon=horizon, start_month=start,
        )["viable"],
        "new_customers_halved": _project(
            arpu=inputs["arpu_low"], churn=0.08, new_per_month=max(1, base_new // 2),
            monthly_cost=monthly_cost, target_mrr=target_mrr,
            horizon=horizon, start_month=start,
        )["viable"],
    }

    killing_input: str | None = None
    if base["viable"]:
        for k, still_viable in perturbations.items():
            if not still_viable:
                killing_input = k
                break

    return {
        "base_conservative_viable": base["viable"],
        "perturbations": perturbations,
        "killing_input": killing_input,
    }


# ---------------------------------------------------------------------------
# Risk enumeration (heuristic, from the upstream data)
# ---------------------------------------------------------------------------

def _enumerate_risks(cluster: dict, enrichment: dict, score: dict) -> list[dict]:
    risks: list[dict] = []
    metrics = cluster.get("metrics") or {}

    competitors = enrichment.get("direct_competitors") or []
    funded = [c for c in competitors if isinstance(c, dict) and c.get("funding")]
    if funded:
        risks.append({
            "type": "competitive_response",
            "note": f"{len(funded)} funded competitor(s) could copy a successful differentiator",
            "competitors": [c.get("name") for c in funded[:5]],
        })

    mentions = metrics.get("competitor_mentions") or {}
    if mentions:
        primary = max(mentions.items(), key=lambda kv: kv[1])[0]
        risks.append({
            "type": "platform_risk",
            "note": f"Signals reference '{primary}' most frequently — strong dependency on its ecosystem",
        })

    reg = enrichment.get("regulatory_context")
    if reg and reg != "null":
        risks.append({"type": "regulatory", "note": str(reg)[:300]})

    if metrics.get("temporal_trend") == "decreasing":
        risks.append({
            "type": "market_timing",
            "note": "signal volume declining over time — market may be solved or shrinking",
        })

    feas = (score.get("scores") or {}).get("solo_feasibility") or {}
    feas_v = feas.get("value") if isinstance(feas, dict) else None
    if isinstance(feas_v, (int, float)) and feas_v <= 2:
        risks.append({
            "type": "technical",
            "note": f"solo_feasibility score = {feas_v}; significant tech risk a solo founder may not absorb",
        })

    return risks
