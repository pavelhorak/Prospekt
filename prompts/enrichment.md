# Enrichment prompt — Stage 4

## Task

Given a cluster (label, summary, member signals), produce the 8 enrichment
data points specified in SPECIFICATION.md Stage 4. For each field, cite the
source URL and the date the data was retrieved.

## Output format

```yaml
cluster_id: clust_017
enrichment_date: 2026-04-14
direct_competitors:
  - name: LinearB
    url: https://linearb.io
    founded_year: 2018
    pricing:
      tiers: [{name: Team, price_per_seat: 15, billing: monthly}, …]
    estimated_revenue: "$40M ARR (SimilarWeb traffic × benchmark)"
    team_size: 120
    funding: "$50M Series B, 2022"
    source: https://crunchbase.com/…
  # … ≥3 competitors when discoverable …
competitor_weaknesses:
  LinearB: ["too complex for small teams", "expensive at >20 seats", …]
market_size_estimate:
  buyers: 45000
  segment: "engineering managers at 50–500-employee companies, US+EU"
  source: "LinkedIn Sales Navigator search 2026-04-14"
search_demand:
  keywords:
    - {term: "engineering metrics dashboard", monthly_volume: 1900, trend_24mo: +65%}
  source: ahrefs/2026-04-14
funding_activity: [...]
regulatory_context: null
distribution_channels: [...]
```

## Rules

- If a field cannot be filled, return `null` with a note explaining why
  ("no public pricing", "competitor list empty"). Do not invent numbers.
- Every figure must have a `source` URL or a clearly named method.
- Pricing must be exact tier names + prices, not "starting at $X".
