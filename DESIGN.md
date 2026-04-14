# DESIGN.md — Prospect

**System design for a tool that turns raw internet signals into ranked business opportunities.**

Implements the six-stage pipeline from SPECIFICATION.md and the validation framework from EVALUATION.md.

---

## 1. What Prospect Does

Prospect is a single-user CLI + web tool that:

1. Ingests pain signals from Reddit, HN, G2, Upwork, job boards, Google Trends, and other sources.
2. Tags each signal with structured metadata (pain type, intensity, industry, buyer persona, spend evidence).
3. Clusters signals into problem groups that represent a single underlying pain.
4. Enriches top clusters with market data — competitors, pricing, search demand, funding, regulatory context.
5. Scores enriched clusters on 7 weighted criteria with evidence chains.
6. Models unit economics for the top-scored clusters and produces a ranked recommendation.

Every stage is auditable. Every recommendation traces back to raw signals. Nothing is deleted.

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      Prospect                           │
│                                                         │
│  ┌──────────┐  ┌──────┐  ┌─────────┐  ┌────────┐       │
│  │ CLI      │  │ Web  │  │ Cron /  │  │ LLM    │       │
│  │ Commands │  │ UI   │  │ Workers │  │ Client │       │
│  └────┬─────┘  └──┬───┘  └────┬────┘  └───┬────┘       │
│       │           │           │            │            │
│       └───────────┴─────┬─────┴────────────┘            │
│                         │                               │
│                 ┌───────▼────────┐                       │
│                 │  Pipeline      │                       │
│                 │  Orchestrator  │                       │
│                 └───────┬────────┘                       │
│                         │                               │
│    ┌────────┬───────┬───┴───┬────────┬────────┐         │
│    ▼        ▼       ▼       ▼        ▼        ▼         │
│  Ingest   Tag    Cluster  Enrich   Score    Model       │
│  Stage    Stage  Stage    Stage    Stage    Stage        │
│    │        │       │       │        │        │         │
│    └────────┴───────┴───┬───┴────────┴────────┘         │
│                         │                               │
│                 ┌───────▼────────┐                       │
│                 │  Data Layer    │                       │
│                 │  (SQLite +     │                       │
│                 │   JSON files)  │                       │
│                 └────────────────┘                       │
│                                                         │
│  ┌──────────────────────────────────────────────┐       │
│  │  Evaluation Engine                           │       │
│  │  Stage metrics · Backtest · Forward tracking │       │
│  └──────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────┘
```

### Deployment model

Single-machine, single-user. No cloud infrastructure required. Prospect runs locally and stores all data on disk. The web UI is a local server for browsing signals, clusters, and scores — not a hosted app.

### Key technology choices

| Component | Choice | Rationale |
|:--|:--|:--|
| Language | Python 3.12+ | Ecosystem for scraping, embeddings, LLM calls, and data work. Solo maintainability. |
| Database | SQLite (via sqlite3 or SQLAlchemy) | Zero-ops, single-file, portable. Handles 100k+ signals easily. Full SQL for ad-hoc queries. |
| LLM integration | Anthropic Claude API (primary), OpenAI-compatible fallback | Tagging, clustering summaries, enrichment research. Configurable per stage. |
| Embeddings | `sentence-transformers` (local) or OpenAI `text-embedding-3-small` | For automated clustering at scale (2000+ signals). Local option avoids API costs. |
| Clustering | HDBSCAN via `hdbscan` library | Handles variable-density clusters, does not require pre-specifying cluster count, identifies outliers. |
| Web UI | FastAPI + HTMX + Tailwind | Lightweight, server-rendered. No frontend build step. Reactive enough for browsing and auditing. |
| CLI | `click` library | Composable commands, clean help text. |
| Scraping | `httpx` + `beautifulsoup4` + platform-specific API clients | Async HTTP for speed. BS4 for HTML parsing. Reddit via PRAW, HN via Algolia API. |
| Task scheduling | `APScheduler` or system cron | Periodic re-ingestion runs. |

---

## 3. Data Model

### 3.1 Core Tables

#### `signals`

The immutable foundation. Raw signals are insert-only — never updated or deleted.

```sql
CREATE TABLE signals (
    signal_id       TEXT PRIMARY KEY,   -- UUID v4
    raw_text        TEXT NOT NULL,
    source_platform TEXT NOT NULL,      -- enum: reddit, hackernews, g2, upwork, ...
    source_url      TEXT NOT NULL,
    source_context  TEXT,               -- subreddit, review category, group name
    author_info     TEXT,
    engagement      TEXT,               -- JSON: {"upvotes": 340, "comments": 89}
    date_posted     DATE,
    date_collected  DATE NOT NULL DEFAULT (date('now')),
    collection_query TEXT,
    run_id          TEXT NOT NULL,      -- which pipeline run ingested this
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_signals_platform ON signals(source_platform);
CREATE INDEX idx_signals_date_posted ON signals(date_posted);
CREATE INDEX idx_signals_run ON signals(run_id);
CREATE UNIQUE INDEX idx_signals_url ON signals(source_url);  -- dedup by URL
```

#### `tags`

Additive layer. One row per signal. Tags never modify the signal row.

```sql
CREATE TABLE tags (
    signal_id               TEXT PRIMARY KEY REFERENCES signals(signal_id),
    pain_type               TEXT,       -- complaint, workaround, feature_request, ...
    pain_intensity          INTEGER CHECK(pain_intensity BETWEEN 1 AND 5),
    industry                TEXT,
    buyer_persona           TEXT,
    company_size            TEXT,
    geography               TEXT,
    has_workaround          BOOLEAN DEFAULT FALSE,
    workaround_description  TEXT,
    has_spend               BOOLEAN DEFAULT FALSE,
    spend_amount            TEXT,
    existing_solution       TEXT,       -- JSON array of tool names
    date_relevance          TEXT,       -- current, recent, older, historical
    tag_justifications      TEXT,       -- JSON: per-field quote from raw_text
    tagged_by               TEXT,       -- 'manual' or LLM model identifier
    tagged_at               DATETIME DEFAULT CURRENT_TIMESTAMP,
    run_id                  TEXT NOT NULL
);

CREATE INDEX idx_tags_pain_type ON tags(pain_type);
CREATE INDEX idx_tags_industry ON tags(industry);
CREATE INDEX idx_tags_intensity ON tags(pain_intensity);
```

#### `clusters`

```sql
CREATE TABLE clusters (
    cluster_id      TEXT PRIMARY KEY,   -- UUID v4
    cluster_label   TEXT NOT NULL,
    cluster_summary TEXT,
    run_id          TEXT NOT NULL,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    method          TEXT                -- 'manual', 'llm_batch', 'hdbscan'
);
```

#### `cluster_signals`

Many-to-many. A signal can belong to multiple clusters.

```sql
CREATE TABLE cluster_signals (
    cluster_id  TEXT REFERENCES clusters(cluster_id),
    signal_id   TEXT REFERENCES signals(signal_id),
    confidence  REAL DEFAULT 1.0,      -- 0.0–1.0 membership confidence
    PRIMARY KEY (cluster_id, signal_id)
);
```

#### `cluster_metrics`

Computed view materialized after each clustering run.

```sql
CREATE TABLE cluster_metrics (
    cluster_id              TEXT PRIMARY KEY REFERENCES clusters(cluster_id),
    signal_count            INTEGER,
    source_diversity        INTEGER,
    industry_spread         INTEGER,
    intensity_mean          REAL,
    intensity_distribution  TEXT,       -- JSON histogram: {"1": 2, "2": 5, ...}
    workaround_count        INTEGER,
    spend_evidence_count    INTEGER,
    total_spend_mentioned   REAL,
    temporal_trend          TEXT,       -- 'increasing', 'stable', 'decreasing'
    competitor_mentions     TEXT,       -- JSON: {"LinearB": 8, "Swarmia": 3, ...}
    computed_at             DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

#### `enrichments`

```sql
CREATE TABLE enrichments (
    cluster_id              TEXT PRIMARY KEY REFERENCES clusters(cluster_id),
    competitors             TEXT,       -- JSON array of competitor objects
    competitor_pricing      TEXT,       -- JSON array of pricing structures
    competitor_weaknesses   TEXT,       -- JSON: top complaints per competitor
    market_size_estimate    TEXT,       -- JSON: method + number + confidence
    search_demand           TEXT,       -- JSON: keywords + volumes + trend
    funding_activity        TEXT,       -- JSON array of funding rounds
    regulatory_context      TEXT,
    distribution_channels   TEXT,       -- JSON array of channel assessments
    enriched_at             DATETIME DEFAULT CURRENT_TIMESTAMP,
    enriched_by             TEXT,       -- 'manual' or 'llm'
    data_recency_check      DATE,      -- when enrichment data was verified current
    completeness_score      INTEGER    -- count of 8 data points filled (0–8)
);
```

#### `scores`

```sql
CREATE TABLE scores (
    cluster_id          TEXT PRIMARY KEY REFERENCES clusters(cluster_id),
    market_demand       INTEGER CHECK(market_demand BETWEEN 1 AND 5),
    distribution        INTEGER CHECK(distribution BETWEEN 1 AND 5),
    competition         INTEGER CHECK(competition BETWEEN 1 AND 5),
    founder_market_fit  INTEGER CHECK(founder_market_fit BETWEEN 1 AND 5),
    solo_feasibility    INTEGER CHECK(solo_feasibility BETWEEN 1 AND 5),
    revenue_path        INTEGER CHECK(revenue_path BETWEEN 1 AND 5),
    defensibility       INTEGER CHECK(defensibility BETWEEN 1 AND 5),
    weighted_total      REAL,          -- computed: sum of (score × weight)
    evidence_chains     TEXT,          -- JSON: per-criterion evidence + confidence + contradictions
    scored_at           DATETIME DEFAULT CURRENT_TIMESTAMP,
    scored_by           TEXT
);

CREATE INDEX idx_scores_total ON scores(weighted_total DESC);
```

#### `models`

```sql
CREATE TABLE models (
    model_id            TEXT PRIMARY KEY,
    cluster_id          TEXT REFERENCES clusters(cluster_id),
    price_point         REAL,
    market_size         INTEGER,
    churn_conservative  REAL,
    churn_base          REAL,
    churn_optimistic    REAL,
    acq_conservative    INTEGER,
    acq_base            INTEGER,
    acq_optimistic      INTEGER,
    build_time_weeks    INTEGER,
    monthly_costs       REAL,
    projections         TEXT,          -- JSON: 24-month MRR arrays for 3 scenarios
    months_to_target    TEXT,          -- JSON: {conservative: 22, base: 14, optimistic: 9}
    risk_factors        TEXT,          -- JSON: platform, competitive, regulatory, technical, timing, personal
    sensitivity_analysis TEXT,         -- JSON: which input change flips the recommendation
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

#### `pipeline_runs`

Every execution of the pipeline (full or partial) is logged.

```sql
CREATE TABLE pipeline_runs (
    run_id          TEXT PRIMARY KEY,
    started_at      DATETIME,
    completed_at    DATETIME,
    stages_run      TEXT,              -- JSON array: ["ingest", "tag", "cluster"]
    config          TEXT,              -- JSON: parameters used for this run
    stage_metrics   TEXT,              -- JSON: evaluation metrics per stage
    status          TEXT DEFAULT 'running'  -- running, completed, failed
);
```

### 3.2 Design Constraints

**Insert-only for signals.** The `signals` table has no UPDATE queries in the application code. Corrections are handled by adding new tags or re-running tagging — never by modifying `raw_text` or other source fields.

**Soft clustering.** `cluster_signals` is a join table, not a column on `signals`. A signal can appear in multiple clusters. The `confidence` field captures fuzzy membership from embedding-based clustering.

**Evidence as JSON.** Fields like `evidence_chains`, `competitor_mentions`, and `projections` are stored as JSON text. SQLite's `json_extract()` enables querying into them. This avoids schema explosion while keeping everything in one database.

**Run isolation.** Every row carries a `run_id`. You can compare outputs across runs, track metric improvement over time, and rollback by filtering on run.

---

## 4. Pipeline Stage Design

### 4.1 Stage 1: Ingest

**Responsibility:** Collect signals from configured sources and write them to `signals` table in uniform schema.

#### Source adapters

Each source is a Python class implementing a common interface:

```python
class SourceAdapter(Protocol):
    platform: str

    async def collect(self, queries: list[str], config: IngestConfig) -> list[RawSignal]:
        """Run queries against this source. Return normalized signal records."""
        ...
```

Implemented adapters:

| Adapter | API/Method | Rate limits | Notes |
|:--|:--|:--|:--|
| `RedditAdapter` | PRAW (Reddit API) | 60 req/min | Collects post body + top 20 comments as separate signals linked by `source_context`. |
| `HackerNewsAdapter` | Algolia HN Search API | 10k req/hr | Searches stories and comments separately. Engagement = points + comment count. |
| `G2Adapter` | Web scraping (httpx + BS4) | Polite: 1 req/3s | Scrapes review pages for specified product categories. Stores pros/cons as separate fields in `raw_text`. |
| `UpworkAdapter` | Web scraping or RSS | Polite: 1 req/5s | Extracts job description, budget, proposals count. Budget → `engagement.budget`. |
| `JobBoardAdapter` | Indeed/LinkedIn API or scraping | Varies | Captures title, description, company, size. Configurable board list. |
| `GoogleTrendsAdapter` | `pytrends` library | Throttled | Returns time-series data as structured JSON in `raw_text`. Not text signals — handled differently in tagging. |
| `GenericScraperAdapter` | httpx + BS4 | Configurable | For Facebook groups, Telegram, niche forums. User provides CSS selectors per site. |

#### Deduplication

On insert, check `source_url` uniqueness. If a URL already exists:
- Do NOT update the existing signal.
- Log the duplicate in a `duplicate_log` table with both `run_id` values.
- The duplicate count per URL is itself a metric (multiple collection paths reaching the same signal = broader coverage confirmation).

#### Configuration

```yaml
# prospect.yaml — ingest section
ingest:
  sources:
    reddit:
      enabled: true
      subreddits: [ExperiencedDevs, SaaS, smallbusiness, webdev, devops]
      queries: ["frustrated with", "waste time", "manual process", "looking for tool"]
      sort: top
      time_filter: year
      max_per_query: 50
    hackernews:
      enabled: true
      queries: ["ask hn", "painful", "workaround", "built internal"]
      max_per_query: 30
    g2:
      enabled: true
      categories: [project-management, engineering-analytics, crm-for-smb]
      min_rating: 1
      max_rating: 3  # focus on negative reviews
    # ... etc
  global:
    max_signals_per_run: 2000
    respect_rate_limits: true
    store_raw_html: false  # set true for archival
```

### 4.2 Stage 2: Tag

**Responsibility:** Read untagged signals from `signals`, assign structured metadata, write to `tags` table.

#### Tagging modes

**Manual mode.** The web UI presents untagged signals one at a time. The user fills in tag fields via a form. Useful for the first 50–100 signals to build intuition and calibrate LLM prompts.

**LLM mode.** Signals are sent to Claude in batches of 10–20. The prompt structure:

```
You are tagging internet signals for a business opportunity research pipeline.

For each signal below, assign values for every tag dimension.
For each tag, quote the EXACT phrase from the signal that justifies your choice.
If a dimension cannot be determined, set it to "unknown".

Tag dimensions:
- pain_type: one of [complaint, feature_request, workaround, wish, paying_for_bad,
  question, switching, price_complaint, manual_process, hiring_signal,
  trend_data, competitive_gap]
- pain_intensity: 1–5 (1=mild annoyance, 3=hours/week wasted, 5=compliance/job risk)
- industry: infer from context
- buyer_persona: who would buy a solution (not always the author)
- company_size: solo, 2-10, 11-50, 51-200, 201-1000, 1000+, unknown
- geography: infer from language, platform, author info
- has_workaround: true/false. If true, describe the workaround.
- has_spend: true/false. If true, note the amount.
- existing_solution_mentioned: list any tool names referenced
- date_relevance: current (<3mo), recent (<6mo), older (6-24mo), historical (2yr+)

Respond as a JSON array with one object per signal.
Each object must include a "justifications" field mapping each dimension
to the quoted phrase that supports it.

Signals:
---
[signal_id: abc123]
{raw_text here}
---
[signal_id: def456]
{raw_text here}
---
```

**Hybrid mode (recommended).** LLM tags all signals. User audits a random sample of 30 (per EVALUATION.md protocol). Disagreements trigger re-prompting with clarified instructions. This is the steady-state workflow.

#### Tag quality gate

After tagging completes, compute stage metrics automatically:

- `tag_coverage`: count where `pain_type != 'unknown'` / total tagged. Must be >85%.
- `intensity_distribution`: histogram. Flag if >70% fall on a single value.
- `workaround_rate`: count where `has_workaround = true` / total. Sanity check — should be 5–25%.
- `spend_rate`: count where `has_spend = true` / total. Typically 2–15%.

If `tag_coverage < 60%`, the pipeline halts and prompts the user to review the tagging prompt or signal quality.

### 4.3 Stage 3: Cluster

**Responsibility:** Group tagged signals into problem clusters. Signals are not moved — they are linked via `cluster_signals`.

#### Clustering pipeline

```
Tagged signals
    │
    ▼
┌──────────────────┐
│ Generate         │  sentence-transformers or OpenAI embeddings
│ embeddings       │  stored in signals.embedding (BLOB or separate table)
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ HDBSCAN          │  min_cluster_size=3, min_samples=2
│ clustering       │  produces cluster labels + outlier designation
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Merge similar    │  cosine similarity between cluster centroids > 0.85
│ clusters         │  → merge into single cluster
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Label clusters   │  LLM reads 5 most central signals per cluster
│ via LLM          │  → writes cluster_label and cluster_summary
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Cross-assign     │  For each signal, check cosine similarity to all
│ signals          │  cluster centroids. If sim > 0.70 to a non-primary
│                  │  cluster, add secondary membership with confidence.
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Compute cluster  │  signal_count, source_diversity, workaround_count,
│ metrics          │  intensity_distribution, temporal_trend, etc.
└──────────────────┘
```

#### Manual override

The web UI shows clusters with their member signals. The user can:

- **Split** a cluster that conflates two problems.
- **Merge** two clusters that describe the same problem.
- **Reassign** a signal from one cluster to another.
- **Rename** a cluster label.

All overrides are logged with the original state preserved. The system never discards the algorithmic assignment — it records the human correction as a layer on top.

#### Embeddings table

```sql
CREATE TABLE embeddings (
    signal_id   TEXT PRIMARY KEY REFERENCES signals(signal_id),
    model       TEXT NOT NULL,          -- e.g. 'all-MiniLM-L6-v2'
    vector      BLOB NOT NULL,          -- float32 array, serialized
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

Embeddings are cached. If the model changes, old embeddings are kept (for reproducibility) and new ones are generated alongside.

### 4.4 Stage 4: Enrich

**Responsibility:** For clusters that pass enrichment triggers, gather market intelligence and attach it to the cluster.

#### Enrichment triggers (automated gate)

A cluster advances to enrichment when it meets **at least 3 of 4**:

| Trigger | Threshold |
|:--|:--|
| Signal count | > 10 |
| Source diversity | > 2 platforms |
| Workaround count | > 3 |
| Spend evidence | > 0 signals |

Plus: intensity distribution must skew ≥3 (median pain_intensity ≥ 3).

Clusters that don't qualify remain in the database. They are re-evaluated after every new ingest run — new signals may push them over the threshold.

#### Enrichment workflow

Enrichment is semi-automated. Some data points can be gathered programmatically; others require human research or LLM-assisted web research.

| Data point | Automated? | Method |
|:--|:--|:--|
| Direct competitors | Partially | LLM web search for "[cluster keyword] tools 2026". User verifies and supplements. |
| Competitor pricing | No | User visits pricing pages. Records structured data in UI form. |
| Competitor weaknesses | Partially | If G2/Capterra reviews were ingested in Stage 1, aggregate negative reviews per competitor. Otherwise, manual. |
| Market size estimate | Partially | LinkedIn Sales Navigator search (manual), job board API counts (automated), LLM estimation with cited sources. |
| Search demand | Yes | `pytrends` for Google Trends. SEMrush/Ahrefs API if keys configured. |
| Funding activity | Partially | Crunchbase API (if key available) or LLM web search. |
| Regulatory context | No | Manual research. LLM can summarize findings. |
| Distribution channels | No | User assessment based on competitor analysis. Structured form in UI. |

#### Completeness enforcement

After enrichment, compute `completeness_score` (0–8). If <6, the UI shows a warning: "Enrichment incomplete — scores based on this data will have low confidence." The user can proceed but the confidence floor is capped at "low" for any criterion that depends on missing enrichment data.

### 4.5 Stage 5: Score

**Responsibility:** Apply the 7-criterion weighted rubric to each enriched cluster. Produce a ranked list with evidence chains.

#### Scoring weights

```python
SCORING_WEIGHTS = {
    "market_demand":      0.20,
    "distribution":       0.20,
    "competition":        0.15,
    "founder_market_fit": 0.15,
    "solo_feasibility":   0.15,
    "revenue_path":       0.10,
    "defensibility":      0.05,
}
```

Weights are configurable in `prospect.yaml` and can be adjusted over time based on calibration feedback (per EVALUATION.md §Calibration Over Time).

#### Scoring modes

**Manual scoring.** The UI presents one cluster at a time with all its signals and enrichment data visible. For each criterion, the user selects 1–5, writes the primary evidence (free text or selects from pre-populated options), sets confidence (high/medium/low), and notes contradicting evidence.

**LLM-assisted scoring.** The LLM receives the cluster summary, all signal texts, and all enrichment data. It proposes scores with evidence chains. The user reviews, adjusts, and approves. The LLM's initial proposal and the user's final decision are both stored.

**The user always has final say.** LLM scoring is a draft, not a decision. This is critical because founder-market fit and distribution advantage require self-knowledge the LLM doesn't have.

#### Evidence chain schema

```json
{
  "market_demand": {
    "score": 4,
    "confidence": "high",
    "primary_evidence": [
      "Google Trends slope +65% over 24 months for 'PR review analytics'",
      "47 signals across 5 platforms",
      "12 workarounds described in cluster"
    ],
    "contradicting_evidence": [
      "Search volume still low in absolute terms (<500/mo)"
    ],
    "data_sources": [
      "google_trends:pr_review_analytics",
      "cluster_metrics:cluster_abc123"
    ]
  }
}
```

#### Weighted total computation

```python
weighted_total = sum(
    scores[criterion] * SCORING_WEIGHTS[criterion]
    for criterion in SCORING_WEIGHTS
)
# Range: 1.0 – 5.0
```

#### Kill criteria

Certain conditions eliminate a cluster regardless of weighted total:

| Kill condition | Trigger | Rationale |
|:--|:--|:--|
| No demand signal | `signal_count < 5` AND `source_diversity < 2` | Not enough evidence the problem exists broadly. |
| Unwinnable competition | Single competitor with >$50M funding AND >4.0 avg review rating AND <$20/mo pricing | You cannot compete on features, brand, or price. |
| Infeasible solo | `solo_feasibility = 1` | Cannot be built by one person in reasonable time. |
| No revenue path | `revenue_path = 1` AND no spend evidence in cluster | No evidence anyone would pay. |
| Conservative model fails | Conservative scenario never reaches target MRR in 24 months | Even the best case for worst assumptions doesn't work. |

Kill criteria are checked after scoring and after modeling. A killed cluster is marked `status = 'killed'` with the reason. It is never deleted.

### 4.6 Stage 6: Model

**Responsibility:** For the top 2–3 scored clusters (by `weighted_total`), build 24-month MRR projections under three scenarios.

#### Projection engine

```python
def project_mrr(
    arpu: float,
    monthly_churn: float,
    new_customers_per_month: int,
    build_time_months: float,
    monthly_costs: float,
    months: int = 24,
) -> list[MonthProjection]:
    """
    MRR(m) = MRR(m-1) × (1 - churn) + (new_customers × arpu)
    Revenue starts after build_time_months.
    Returns per-month: mrr, customer_count, net_revenue, cumulative_revenue.
    """
    projections = []
    mrr = 0.0
    customers = 0
    for month in range(1, months + 1):
        if month > math.ceil(build_time_months):
            customers = customers * (1 - monthly_churn) + new_customers_per_month
            mrr = customers * arpu
        net = mrr - monthly_costs
        projections.append(MonthProjection(
            month=month,
            mrr=round(mrr, 2),
            customers=round(customers),
            net_revenue=round(net, 2),
        ))
    return projections
```

Three scenarios are run per cluster using inputs from enrichment data:

| Parameter | Conservative | Base | Optimistic |
|:--|:--|:--|:--|
| ARPU | Lowest competitor tier | Median competitor pricing | Higher tier + expansion |
| Monthly churn | 8% | 5% | 3% |
| New customers/mo | 3 (organic only) | 8 (content + community + outreach) | 15 (marketplace + content + WoM) |

#### Sensitivity analysis

For each input parameter, re-run the base scenario with the parameter at 2× and 0.5×. Identify which single parameter change flips the recommendation (e.g., changes months-to-target from <18 to >24). This is the "what could kill the business" answer.

#### Output

The model stage produces an **opportunity brief** — a structured document per cluster containing: cluster summary, top signals, enrichment highlights, all 7 scores with evidence, 3-scenario projections as tables and charts, risk factors, sensitivity results, and a go/no-go recommendation.

---

## 5. Evaluation Engine

Implements EVALUATION.md. Three evaluation types, all stored in the database for longitudinal tracking.

### 5.1 Stage-Level Metrics

Computed automatically after each pipeline run. Stored in `pipeline_runs.stage_metrics` as JSON.

```python
@dataclass
class StageMetrics:
    """Computed after each run. Compared against thresholds from EVALUATION.md."""

    # Stage 1: Ingest
    ingest_coverage: int            # unique source platforms with ≥1 signal
    ingest_volume: int              # total signals collected
    ingest_schema_completeness: float  # % signals with all required fields
    ingest_freshness: float         # % signals posted within 12 months
    ingest_duplication_rate: float  # % signals with duplicate source_url

    # Stage 2: Tag
    tag_accuracy: float | None      # from manual audit; null if not audited
    tag_coverage: float             # % where pain_type != 'unknown'
    tag_intensity_distribution: dict  # histogram
    tag_workaround_precision: float | None  # from audit
    tag_spend_precision: float | None       # from audit

    # Stage 3: Cluster
    cluster_coherence: float | None  # from manual audit
    cluster_orphan_rate: float       # % signals in no cluster
    cluster_count: int
    cluster_size_distribution: dict  # histogram
    cluster_cross_overlap: float     # % signals in >1 cluster
    cluster_source_diversity_avg: float

    # Stage 4: Enrich
    enrich_completeness_avg: float   # avg completeness_score across enriched clusters
    enrich_competitor_discovery_avg: float
    enrich_pricing_availability: float
    enrich_data_recency: str         # oldest data point age

    # Stage 5: Score
    score_evidence_linkage: float    # % scores with ≥1 evidence link
    score_range_utilization: dict    # histogram of all scores
    score_confidence_coverage: float # % high-confidence scores in top-3

    # Stage 6: Model
    model_input_traceability: float  # % inputs with source
    model_scenario_spread: float     # optimistic/conservative MRR ratio at month 18
    model_conservative_viable: bool  # conservative reaches target in 24mo?
    model_sensitivity_identified: bool
```

#### Threshold checking

Each metric is compared against the Good/Bad thresholds from EVALUATION.md. The run report shows a traffic-light summary:

- 🟢 Green: meets "Good" threshold.
- 🟡 Yellow: between Good and Bad.
- 🔴 Red: meets "Bad" threshold.

If any stage has a red metric, the pipeline warns the user before proceeding to the next stage.

### 5.2 Backtest Framework

```sql
CREATE TABLE backtest_cases (
    case_id         TEXT PRIMARY KEY,
    product_name    TEXT NOT NULL,
    description     TEXT,
    launch_date     DATE,
    outcome         TEXT NOT NULL,       -- 'success' or 'failure'
    revenue_evidence TEXT,               -- URL to revenue proof
    founder_account TEXT,                -- why it succeeded/failed
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE backtest_runs (
    backtest_id     TEXT PRIMARY KEY,
    run_date        DATE,
    cases           TEXT,                -- JSON array of case_ids
    pipeline_run_id TEXT,                -- the pipeline run used for scoring
    results         TEXT,                -- JSON: per-case scores + ranking
    metrics         TEXT,                -- JSON: separation, top3_precision, etc.
    pass            BOOLEAN,
    notes           TEXT
);
```

#### Backtest workflow (CLI)

```bash
# 1. Register cases
prospect backtest add-case --name "Plausible" --outcome success \
  --launch 2019-04 --revenue "https://plausible.io/about" \
  --description "Privacy-focused Google Analytics alternative"

# 2. Collect signals with date constraint (pre-launch)
prospect backtest collect --case "Plausible" --before 2018-10 \
  --queries "google analytics frustration,privacy analytics,simple analytics"

# 3. Run pipeline on collected signals
prospect backtest run --cases all

# 4. Evaluate
prospect backtest evaluate
# Output: separation, top-3 precision, bottom-3 precision,
#         kill criterion sensitivity, signal presence
```

#### Bias mitigation

The `backtest collect` command enforces outcome blindness:

- Signals are collected for ALL cases before any tagging begins.
- The command shuffles case order so the user doesn't process all successes then all failures.
- Collection queries must not include the product name — only problem-space keywords.
- The system logs which queries were used per case for auditability.

### 5.3 Forward Test Tracker

Once the user commits to an opportunity, Prospect tracks real-world metrics against pipeline predictions.

```sql
CREATE TABLE forward_tests (
    test_id             TEXT PRIMARY KEY,
    cluster_id          TEXT REFERENCES clusters(cluster_id),
    model_id            TEXT REFERENCES models(model_id),
    start_date          DATE,
    target_mrr          REAL,

    -- Milestones (filled in as they happen)
    problem_confirmed   BOOLEAN,
    problem_confirmed_date DATE,
    problem_confirmed_notes TEXT,

    wtpay_confirmed     BOOLEAN,        -- willingness to pay
    wtpay_confirmed_date DATE,
    landing_page_cvr    REAL,
    pre_launch_payments INTEGER,

    mvp_shipped_date    DATE,
    build_time_actual   INTEGER,        -- weeks

    first_10_customers_date DATE,
    day_90_paying       INTEGER,

    mrr_1k_date         DATE,
    month_6_mrr         REAL,
    month_6_churn       REAL,
    distribution_channel TEXT,
    distribution_repeatable BOOLEAN,

    month_12_mrr        REAL,
    month_18_mrr        REAL,

    outcome             TEXT,           -- 'ongoing', 'succeeded', 'failed'
    failure_stage       TEXT,           -- which forward test stage failed
    retrospective       TEXT,           -- free-text learnings
    completed_at        DATETIME
);
```

The web UI shows a forward test dashboard comparing predicted vs. actual at each milestone. Deviations >2× from the model's base case are flagged for retrospective analysis.

### 5.4 Calibration Store

After each forward test (or even partial validation), the user records calibration data.

```sql
CREATE TABLE calibration_entries (
    entry_id        TEXT PRIMARY KEY,
    cluster_id      TEXT,
    criterion       TEXT,               -- which scoring criterion
    predicted_score INTEGER,
    actual_outcome  INTEGER,            -- retrospective "what should it have been"
    delta           INTEGER,            -- predicted - actual
    notes           TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE source_quality (
    source_platform TEXT,
    run_id          TEXT,
    signals_collected INTEGER,
    signals_in_top_clusters INTEGER,    -- how many ended up in enriched clusters
    signal_to_noise REAL,               -- ratio
    PRIMARY KEY (source_platform, run_id)
);
```

Over time, this data enables:

- Adjusting scoring weights based on which criteria predict actual outcomes.
- Refining scoring anchors with real examples ("a 5 on distribution looks like Cluster X from Run 3").
- Dropping low-SNR sources and investing more in high-SNR sources.
- Identifying personal biases (e.g., consistently overscoring solo feasibility).

---

## 6. Web UI

Server-rendered with FastAPI + HTMX. No SPA complexity. Pages load fast, forms submit without JavaScript frameworks.

### Key screens

| Screen | Purpose | Key interactions |
|:--|:--|:--|
| **Dashboard** | Overview of latest run. Stage metric traffic lights. Top-ranked clusters. | Click through to any stage. Start new run. |
| **Signal Browser** | Paginated table of all signals. Filterable by platform, date, tags, cluster. | Click signal → full detail with raw text, tags, cluster memberships. |
| **Tag Audit** | Shows 30 random signals with LLM tags. User confirms or corrects each. | Agree/disagree buttons per tag. Computes inter-rater agreement. |
| **Cluster Map** | Visual overview of clusters. Size = signal count. Color = avg intensity. | Click cluster → member signals, metrics, enrichment status. |
| **Cluster Detail** | All data for one cluster: signals, tags summary, metrics, enrichment, scores, model. | Full traceability view. Edit enrichment. Score/rescore. |
| **Enrichment Form** | Structured form for entering market research per cluster. | Competitor table, pricing grid, market size calculator, channel assessment. |
| **Scoring Workbench** | Side-by-side: cluster data on left, scoring form on right. LLM draft scores pre-filled. | Adjust scores, write evidence, flag contradictions. |
| **Ranking Table** | All scored clusters ranked by weighted total. Columns for each criterion. Kill indicators. | Sort, filter, compare side-by-side. Export to CSV. |
| **Model Builder** | Input assumptions, run projections, view 3-scenario charts. Sensitivity sliders. | Interactive: change ARPU and watch MRR curve update. |
| **Backtest Console** | Manage cases, run backtests, view pass/fail metrics. | Add cases, trigger collection, view results. |
| **Forward Test Tracker** | Log real-world milestones. Compare predicted vs actual. | Update metrics as the business progresses. |
| **Calibration Report** | Cross-run analysis. Score accuracy trends. Source quality rankings. Bias detection. | Read-only analysis view with charts. |

### Design principles

- **No JavaScript frameworks.** HTMX handles dynamic interactions. Alpine.js for small client-side state (dropdowns, toggles).
- **Mobile-usable.** Signal tagging and browsing should work on a phone for reviewing on the go.
- **Export everywhere.** Every table and view has a CSV/JSON export button. The opportunity brief exports as Markdown and PDF.
- **Dark mode.** Configurable. Default follows system preference.

---

## 7. CLI Interface

```bash
prospect run                    # Full pipeline: ingest → tag → cluster → enrich → score → model
prospect run --stages ingest,tag  # Run specific stages only
prospect run --resume <run_id>  # Resume a failed/paused run

prospect ingest                 # Ingest only, using prospect.yaml config
prospect ingest --source reddit --queries "frustrated with,waste time"

prospect tag                    # Tag all untagged signals from latest ingest
prospect tag --method llm       # Force LLM tagging (default: hybrid)
prospect tag --audit 30         # Start a 30-signal audit session

prospect cluster                # Cluster all tagged signals
prospect cluster --method hdbscan --min-size 3

prospect enrich <cluster_id>    # Open enrichment workflow for a cluster
prospect enrich --auto-qualify  # Enrich all clusters meeting trigger thresholds

prospect score                  # Score all enriched clusters
prospect score <cluster_id>     # Score a specific cluster

prospect model <cluster_id>     # Build model for a specific cluster
prospect model --top 3          # Model top 3 by weighted score

prospect eval                   # Print stage metrics for latest run
prospect eval --run <run_id>    # Metrics for a specific run
prospect eval --compare <id1> <id2>  # Compare two runs

prospect backtest ...           # See §5.2

prospect serve                  # Start web UI on localhost:8080
prospect export <cluster_id>    # Export opportunity brief as Markdown

prospect config                 # Open prospect.yaml in $EDITOR
```

---

## 8. Configuration

All configuration lives in `prospect.yaml` at the project root.

```yaml
# prospect.yaml
project:
  name: "Q2 2026 Opportunity Scan"
  target_mrr: 10000              # USD/month
  timeline_months: 18
  monthly_costs: 900             # EUR, converted at runtime

llm:
  provider: anthropic            # anthropic | openai
  model: claude-sonnet-4-20250514
  api_key_env: ANTHROPIC_API_KEY # env var name, never stored in config
  max_tokens_per_call: 4096
  temperature: 0.2               # low for consistent tagging

embeddings:
  provider: local                # local | openai
  model: all-MiniLM-L6-v2       # for local
  # model: text-embedding-3-small  # for openai

clustering:
  method: hdbscan                # hdbscan | llm_batch | manual
  min_cluster_size: 3
  min_samples: 2
  merge_threshold: 0.85          # cosine similarity for cluster merging
  cross_assign_threshold: 0.70   # for secondary cluster membership

scoring:
  weights:
    market_demand: 0.20
    distribution: 0.20
    competition: 0.15
    founder_market_fit: 0.15
    solo_feasibility: 0.15
    revenue_path: 0.10
    defensibility: 0.05

enrichment:
  triggers:
    min_signal_count: 10
    min_source_diversity: 2
    min_workaround_count: 3
    require_spend_evidence: false  # true = stricter
    min_median_intensity: 3

ingest:
  # ... source configs as shown in §4.1

web_ui:
  host: 127.0.0.1
  port: 8080
  theme: system                  # light | dark | system

database:
  path: ./prospect.db            # SQLite file location
  backup_on_run: true            # auto-backup before each pipeline run
```

---

## 9. Data Flow Example

A concrete walkthrough of one signal's journey through the pipeline.

**1. Ingest.** RedditAdapter runs query `"frustrated with" in r/ExperiencedDevs`. Finds a post: *"How do you know if your code review process is actually working? We spend hours in PRs with no idea if it's getting better or worse."* 340 upvotes, 89 comments. Stored as signal `sig_001` with `source_platform=reddit`, `engagement={"upvotes":340,"comments":89}`, `date_posted=2026-01-15`.

**2. Tag.** LLM reads `sig_001`. Assigns: `pain_type=question`, `pain_intensity=3` (significant time waste), `industry=software_development`, `buyer_persona=engineering_manager`, `has_workaround=no`, `has_spend=no`, `existing_solution=null`. Justification: *"spend hours in PRs"* → intensity 3; *"code review process"* → software_development.

**3. Cluster.** Embedding for `sig_001` is generated. HDBSCAN places it in cluster `clust_017` alongside 46 other signals about code review visibility. Cluster label: *"Engineering teams lack visibility into code review bottlenecks."* Signal count: 47. Source diversity: 5 (Reddit, HN, G2, LinkedIn, Slack). Workaround count: 12.

**4. Enrich.** `clust_017` passes all enrichment triggers. User researches competitors: LinearB ($50M funded), Swarmia (growing), Haystack (acquired). Pricing: $8–15/seat. Market size: ~45,000 engineering managers at 50–500 person companies in US+EU. Google Trends: +65% over 24 months.

**5. Score.** Market demand: 4/5 (strong trend, high signal count, good diversity). Distribution: 3/5 (content channel viable, but no existing audience). Competition: 3/5 (funded players exist but reviews show complexity complaints). Founder-market fit: 4/5 (user is an engineering manager). Solo feasibility: 4/5 (CRUD + GitHub API). Revenue path: 4/5 ($150/team, need ~67 teams for $10k). Defensibility: 2/5 (data moat possible but slow). Weighted total: 3.50.

**6. Model.** Base case: $150 ARPU, 5% churn, 8 new/mo, 6 weeks to MVP. Reaches $10k MRR at month 14. Conservative case: $100, 8% churn, 3 new/mo. Reaches $10k at month 22. Sensitivity: if churn exceeds 10%, never reaches target. Risk factors: LinearB could ship a simpler tier; GitHub could build native analytics.

**Result.** `clust_017` ranks #2 overall. The opportunity brief is exported. The user decides to proceed to forward testing.

---

## 10. Non-Goals and Boundaries

Things Prospect deliberately does not do:

- **Real-time monitoring.** Prospect runs in batch mode, not as a live stream processor. You run the pipeline when you're actively researching, not 24/7.
- **Automated decision-making.** The pipeline produces recommendations and evidence. The human decides. There is no "auto-pick the winner" mode.
- **Multi-user collaboration.** Single-user tool. No auth, no permissions, no team features. If you want to share results, export them.
- **Scraping at scale.** Prospect is designed for hundreds to low thousands of signals per run, not millions. It respects rate limits and does not attempt to circumvent platform restrictions.
- **Category-creator detection.** The pipeline finds painkiller opportunities — problems people already articulate. It will not surface iPhone-style innovations where demand doesn't yet exist. This is acknowledged as a structural limitation.

---

## 11. Development Phases

### Phase 1: Foundation (weeks 1–2)
- SQLite schema, data model, basic CLI scaffold.
- `RedditAdapter` and `HackerNewsAdapter` (the two highest-signal sources).
- Manual tagging via CLI.
- Manual clustering (sticky-note method, recorded in DB).

### Phase 2: LLM Integration (weeks 3–4)
- LLM tagging with batch prompting and justification storage.
- LLM-assisted cluster labeling.
- Tag audit workflow.
- Basic stage metrics computation.

### Phase 3: Automation (weeks 5–6)
- Embedding generation and HDBSCAN clustering.
- Cluster merging and cross-assignment.
- All remaining source adapters (G2, Upwork, job boards, Google Trends).
- Enrichment form and structured storage.

### Phase 4: Scoring and Modeling (weeks 7–8)
- Scoring workbench with evidence chains.
- Kill criteria checking.
- Projection engine with 3-scenario modeling.
- Sensitivity analysis.
- Opportunity brief export.

### Phase 5: Web UI (weeks 9–10)
- FastAPI + HTMX application.
- All screens from §6.
- Dashboard with traffic-light metrics.

### Phase 6: Evaluation (weeks 11–12)
- Backtest framework with CLI workflow.
- Forward test tracker.
- Calibration store and reporting.
- Cross-run comparison.

---

*Every signal preserved. Every score traced to evidence. Every recommendation auditable.*
