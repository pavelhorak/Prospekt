# Enrichment prompt — Stage 4

## Task

Given a cluster (label, summary, member signals), research the 8 enrichment
data points specified in SPECIFICATION.md Stage 4. Use web search freely.
For every URL you cite, add `{url, title}` to the `citations` array.

## Output

Output is enforced by `--json-schema` — return ONLY valid JSON, no prose,
no markdown fences, no commentary outside the JSON object.

The expected shape:

```json
{
  "direct_competitors": [
    {
      "name": "LinearB",
      "url": "https://linearb.io",
      "founded_year": 2018,
      "pricing": {"tiers": [{"name": "Team", "price_per_seat": 15, "billing": "monthly"}]},
      "estimated_revenue": "$40M ARR (SimilarWeb × benchmark)",
      "team_size": 120,
      "funding": "$50M Series B, 2022",
      "source": "https://crunchbase.com/..."
    }
  ],
  "competitor_weaknesses": {
    "LinearB": ["too complex for small teams", "expensive at >20 seats"]
  },
  "market_size_estimate": {
    "buyers": 45000,
    "segment": "engineering managers at 50-500-employee companies, US+EU",
    "source": "LinkedIn Sales Navigator search"
  },
  "search_demand": {
    "keywords": [
      {"term": "engineering metrics dashboard", "monthly_volume": 1900, "trend_24mo_pct": 65}
    ],
    "source": "ahrefs"
  },
  "funding_activity": [],
  "regulatory_context": null,
  "distribution_channels": null,
  "citations": [
    {"url": "https://crunchbase.com/...", "title": "LinearB - Crunchbase profile"}
  ]
}
```

## Rules

- Find at least 3 direct competitors when the space has any. If genuinely
  no competitors after a real search, return `"direct_competitors": []`
  and add a citation note.
- Every figure must have a `source` field or be traceable to a `citations` URL.
- Pricing must be exact tier names + prices (`{"name": "Team", "price_per_seat": 15}`),
  not "starting at $X".
- Numeric fields are numbers in JSON (no `$`, no units inside the number) —
  put units in adjacent string fields.
- If a field is genuinely unknown after a reasonable search, set it to `null`.
