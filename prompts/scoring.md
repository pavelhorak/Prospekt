# Scoring prompt — Stage 5

## Task

Score a cluster on the 7 criteria below, on a 1–5 scale. For each criterion
produce: the score, the primary evidence (signal IDs and/or enrichment
fields that justify it), a confidence level (high | medium | low), and any
contradicting evidence you noticed.

The scoring rubric anchors are in DESIGN.md §4. The criterion weights are
applied later by prospect.py from `pipeline.yaml`; you do NOT apply them.

## Criteria

1. `market_demand` — signal volume, source diversity, search trend
2. `distribution` — existing audience, SEO viability, marketplaces, virality
3. `competition` — direct competitors' funding, ratings, pricing power
4. `founder_market_fit` — founder's domain experience, network, credibility
5. `solo_feasibility` — buildability by one person without ML/regulatory drag
6. `revenue_path` — pricing benchmark and customers-needed-for-$10k-MRR math
7. `defensibility` — proprietary data, switching costs, network effects

## Output

Output is enforced by `--json-schema` — return ONLY valid JSON, no prose,
no markdown fences, no text outside the JSON object.

The expected shape:

```json
{
  "scores": {
    "market_demand": {
      "value": 4,
      "confidence": "high",
      "evidence": ["signal_count: 47", "source_diversity: 5", "google_trends_slope: +65%"],
      "contradicting": "one well-funded competitor (LinearB) launched a similar feature in 2025"
    },
    "distribution": {
      "value": 3,
      "confidence": "medium",
      "evidence": ["SEO difficulty 38 on 'engineering metrics dashboard'"],
      "contradicting": null
    },
    "competition":         {"value": 3, "confidence": "medium", "evidence": [...], "contradicting": null},
    "founder_market_fit":  {"value": 3, "confidence": "low",    "evidence": [...], "contradicting": null},
    "solo_feasibility":    {"value": 4, "confidence": "high",   "evidence": [...], "contradicting": null},
    "revenue_path":        {"value": 3, "confidence": "medium", "evidence": [...], "contradicting": null},
    "defensibility":       {"value": 2, "confidence": "high",   "evidence": [...], "contradicting": null}
  }
}
```

## Rules

- Force yourself to use 1 and 5 when warranted. If every criterion is 3
  or 4, the range_utilization metric will penalize the run.
- Confidence MUST reflect evidence type:
  - high   = hard data (signal counts, scraped pricing, search volume)
  - medium = inferred from strong signals or proxies
  - low    = best guess, insufficient enrichment data
- `contradicting` is mandatory if any data argues against the score, even
  weakly. A score with `contradicting: null` for every criterion is suspicious.
- `evidence` is an array of short strings (signal IDs, enrichment fields, numeric facts).
