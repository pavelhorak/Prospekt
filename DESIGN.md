# DESIGN.md — Prospect (v2)

**System design for a tool that turns raw internet signals into ranked business opportunities — and gets better at it with every run.**

Implements the six-stage pipeline from SPECIFICATION.md, the validation framework from EVALUATION.md, and an autoresearch-inspired self-improvement loop.

---

## 1. What Prospect Does

Prospect is a single-user CLI tool that:

1. Ingests pain signals from Reddit, HN, G2, Upwork, job boards, Google Trends, and other sources.
2. Tags each signal with structured metadata (pain type, intensity, industry, buyer persona, spend evidence).
3. Clusters signals into problem groups representing a single underlying pain.
4. Enriches top clusters with market data — competitors, pricing, search demand, funding, regulatory context.
5. Scores enriched clusters on 7 weighted criteria with evidence chains.
6. Models unit economics for the top-scored clusters and produces a ranked recommendation.

Then — critically — it measures how well the pipeline performed, compares against previous runs, and modifies its own configuration to improve. The human edits `program.md` (the meta-instructions). The agent edits `pipeline.yaml` (the configuration). The pipeline measures itself.

---

## 2. No Database. Files on Disk.

### Why not SQLite

The pipeline processes hundreds to low thousands of signals per run. There are no complex joins, no concurrent writers, no transactions. The only relationship is signals↔clusters, which is a list of IDs inside a cluster file. Everything fits in memory. A directory of YAML and Markdown files, version-controlled in git, gives you:

- Human-readable data you can inspect with `cat` and `grep`
- Full history via `git log` — every run, every config change, every result
- Diffs between runs via `git diff`
- No dependencies, no migrations, no schema versioning
- Portability — copy the directory, you have the whole system

### Directory structure

```
prospect/
├── prospect.py             ← CLI, orchestration, frozen metric math (engine)
├── adapters.py             ← Stage 1 source adapters (engine — frozen)
├── program.md              ← meta-instructions for the agent (human edits this)
├── pipeline.yaml           ← all pipeline config (agent edits this)
├── results.tsv             ← experiment log: run_id, metrics, status, description
│
├── runs/
│   └── {run_id}/           ← one directory per pipeline run (run_id = YYYY-MM-DDTHH-MM-SS UTC)
│       ├── run.yaml        ← run metadata: timestamp, config snapshot, stages run
│       ├── metrics.yaml    ← stage-level metrics for this run
│       │
│       ├── signals/
│       │   ├── index.yaml  ← signal manifest: count, sources, date range
│       │   └── {platform}/
│       │       └── {signal_id}.yaml  ← one file per signal
│       │
│       ├── attachments/    ← binary blobs referenced by signal files (screenshots, PDFs)
│       │   └── {signal_id}/
│       │       └── {filename}
│       │
│       ├── tags/
│       │   └── {signal_id}.yaml  ← one file per tagged signal
│       │
│       ├── clusters/
│       │   ├── index.yaml  ← cluster manifest: count, size distribution
│       │   └── {cluster_id}.yaml  ← cluster with member signal_ids + metrics
│       │
│       ├── enrichments/
│       │   └── {cluster_id}.yaml  ← market data layered onto cluster
│       │
│       ├── scores/
│       │   ├── ranking.yaml  ← sorted list of clusters by weighted score
│       │   └── {cluster_id}.yaml  ← 7-criterion scores with evidence chains
│       │
│       └── models/
│           └── {cluster_id}.yaml  ← 3-scenario projections + risk factors
│
├── backtests/
│   ├── cases/
│   │   └── {case_id}.yaml  ← known success/failure with metadata
│   ├── runs/
│   │   └── {backtest_id}/  ← signals + pipeline output for backtest
│   └── results/
│       └── {backtest_id}.yaml  ← separation, precision, kill sensitivity
│
├── forward_tests/
│   └── {test_id}.yaml      ← real-world milestones vs predictions
│
├── calibration/
│   ├── history.yaml          ← per-run metrics over time (the improvement record)
│   ├── source_quality.yaml   ← signal-to-noise per source across runs
│   ├── bias_log.yaml         ← predicted vs actual scores, per criterion
│   ├── weight_history.yaml   ← how scoring weights changed and why
│   └── backtest_status.yaml  ← last backtest id, age, pass/fail, gating the loop
│
└── prompts/
    ├── tagging.md          ← current LLM prompt for Stage 2
    ├── clustering.md       ← current LLM prompt for Stage 3
    ├── enrichment.md       ← current LLM prompt for Stage 4
    └── scoring.md          ← current LLM prompt for Stage 5
```

### Signal file example

```yaml
# runs/2026-04-14T09-12-08/signals/reddit/sig_a1b2c3d4.yaml
signal_id: sig_a1b2c3d4
raw_text: |
  We spend 3 hours every Friday manually compiling engineering metrics
  from Jira and GitHub into a Google Sheet that nobody reads...
source_platform: reddit
source_url: https://reddit.com/r/ExperiencedDevs/comments/abc123
source_context: r/ExperiencedDevs
author_info: "Senior Engineering Manager, Series B startup, 40 engineers"
engagement:
  upvotes: 340
  comments: 89
date_posted: 2026-01-15
date_collected: 2026-04-14
collection_query: "frustrated with" in r/ExperiencedDevs, sorted by top, past year

# Optional. Source-specific structured data preserved in addition to raw_text.
# Examples: G2/Capterra → {rating, pros, cons, role, company_size};
# competitor pricing page → {tiers: [...], billing: per_seat|flat|usage};
# job posting → {title, company, location, salary_range};
# Google Trends → {keyword, series: [[date, value], ...]}
structured: {}

# Optional. Paths (relative to the run directory) to binary attachments.
# Screenshots, archived HTML, PDFs. The signal file is the source of truth;
# attachments are referenced, never inlined.
attachments: []
```

### Cluster file example

```yaml
# runs/2026-04-14T09-12-08/clusters/clust_017.yaml
cluster_id: clust_017
cluster_label: "Engineering teams lack visibility into code review bottlenecks"
cluster_summary: |
  Engineering managers and team leads can't measure whether code review
  is getting better or worse. They build spreadsheet workarounds, export
  data from GitHub/GitLab manually, or just guess.
signal_ids:
  - sig_a1b2c3d4
  - sig_e5f6g7h8
  # ... 45 more
metrics:
  signal_count: 47
  source_diversity: 5
  sources: [reddit, hackernews, g2, linkedin, slack]
  industry_spread: 3
  industries: [software_development, devops, engineering_management]
  intensity_distribution: {1: 2, 2: 8, 3: 19, 4: 14, 5: 4}
  intensity_mean: 3.2
  workaround_count: 12
  spend_evidence_count: 8
  total_spend_mentioned: 24000
  temporal_trend: increasing
  competitor_mentions: {LinearB: 8, Swarmia: 3, Haystack: 2, Jellyfish: 1}
method: hdbscan
```

### ID format

Every ID has a stable prefix so files are self-identifying when read out of context:

| Kind | Prefix | Example |
|:--|:--|:--|
| Signal | `sig_` | `sig_a1b2c3d4e5f6` |
| Cluster | `clust_` | `clust_017` |
| Run | none | `2026-04-14T09-12-08` (UTC timestamp) |
| Backtest | `bt_` | `bt_2026-05-01a` |
| Forward test | `ft_` | `ft_001` |

Signal IDs are the first 12 hex chars of a UUID4 with the `sig_` prefix — short enough to type, long enough to avoid collisions inside a single run. The same ID is used as the filename (without extension) and as the value of `signal_id:` inside the file.

### Design rules

- **Signals are write-once.** No file in `signals/` is ever modified after creation.
- **Tags, clusters, scores are additive layers.** They reference `signal_id` but never touch the signal file.
- **Runs are immutable snapshots.** Once a run completes, its directory is never modified. New runs create new directories.
- **Git tracks everything.** Every run is committed. `git log --oneline` shows the full history of the pipeline's evolution.

---

## 3. The Autoresearch Loop

Adapted from [karpathy/autoresearch](https://github.com/karpathy/autoresearch). The core idea: **the human edits `program.md` (the meta-instructions). The agent edits `pipeline.yaml` (the configuration). The pipeline measures itself. Changes that improve the metric are kept. Changes that don't are discarded.**

### What autoresearch does

In Karpathy's setup: an AI agent modifies `train.py`, runs a 5-minute training experiment, checks if `val_bpb` improved, keeps or discards the change, and repeats indefinitely. The human only edits `program.md` — the instructions that guide the agent's research strategy.

### What Prospect adapts

The same pattern, but for a business opportunity pipeline instead of LLM training:

| Autoresearch | Prospect |
|:--|:--|
| `train.py` — agent modifies this | `pipeline.yaml` + `prompts/*.md` — agent modifies these |
| `prepare.py` — fixed, not modified | `prospect.py` — pipeline engine, not modified |
| `program.md` — human edits this | `program.md` — human edits this |
| `results.tsv` — experiment log | `results.tsv` — experiment log |
| `val_bpb` — single metric, lower is better | `pipeline_score` — composite metric, higher is better |
| 5-minute time budget | one pipeline run (~10-30 min depending on signal count) |

### The three files that matter

**`prospect.py`** — the pipeline engine. Fixed. Implements ingest, tag, cluster, enrich, score, model. Computes all metrics. Not modified by the agent.

**`pipeline.yaml`** — everything the agent can tune. This is the equivalent of `train.py`:

```yaml
# pipeline.yaml — the agent modifies this file

tagging:
  prompt_file: prompts/tagging.md
  batch_size: 15
  model: claude-sonnet-4-20250514
  temperature: 0.2

clustering:
  method: hdbscan
  min_cluster_size: 3
  min_samples: 2
  merge_threshold: 0.85
  cross_assign_threshold: 0.70
  embedding_model: all-MiniLM-L6-v2

enrichment:
  triggers:
    min_signal_count: 10
    min_source_diversity: 2
    min_workaround_count: 3
    min_median_intensity: 3

scoring:
  weights:
    market_demand: 0.20
    distribution: 0.20
    competition: 0.15
    founder_market_fit: 0.15
    solo_feasibility: 0.15
    revenue_path: 0.10
    defensibility: 0.05
  kill_criteria:
    min_signal_count: 5
    min_source_diversity: 2
    max_funded_competitor_rating: 4.0
    min_feasibility: 2

ingest:
  sources:
    reddit:
      subreddits: [ExperiencedDevs, SaaS, smallbusiness, webdev, devops]
      queries: ["frustrated with", "waste time", "manual process", "looking for tool"]
      sort: top
      time_filter: year
      max_per_query: 50
    hackernews:
      queries: ["ask hn", "painful", "workaround", "built internal"]
      max_per_query: 30
```

**`program.md`** — the meta-instructions that tell the agent how to do research. The human edits this. It describes the experiment strategy, what kinds of changes to try, what to prioritize.

### The experiment loop

```
LOOP FOREVER:

1. Read the current pipeline.yaml, prompts/*.md, and calibration/history.yaml.
   Read calibration/backtest_status.yaml — if `last_backtest_age_days > 30` or
   `last_backtest_passed = false`, the next proposed change MUST be either
   (a) a backtest run, or (b) a change explicitly targeting the failing
   backtest metric. The loop refuses to optimize against `pipeline_score`
   alone when the backtest signal is stale or failing.
2. Propose one change:
   - Modify a tagging prompt to improve tag accuracy
   - Adjust clustering thresholds to improve coherence
   - Change scoring weights based on calibration data
   - Add/remove/modify ingest queries based on source quality data
   - Adjust enrichment triggers
   - Rewrite a prompt for better precision
3. Git commit the change with a descriptive message
4. Run the pipeline: prospect run --eval > run.log 2>&1
5. Read the results: grep "pipeline_score:" run.log
6. Log to results.tsv:
   commit, pipeline_score, tag_quality, cluster_quality, backtest_mult, status, description
7. If pipeline_score improved → keep (advance the branch)
   If pipeline_score equal or worse → discard:
     - `git checkout HEAD~1 -- pipeline.yaml prompts/`  (revert config only)
     - the run directory under `runs/` is NOT deleted; it stays as a
       failed-experiment record with `status: discard` in run.yaml
     - commit the revert with "discard: <reason>" so results.tsv stays linear
8. Go to 1.
```

**Why config-only reset.** Design rule §2 says runs are immutable snapshots. Deleting a discarded run via `git reset --hard` would violate that and erase evidence of what was tried. Resetting only `pipeline.yaml` and `prompts/` keeps the experiment log complete while ensuring the next iteration starts from the last *kept* configuration.

### What the agent can change

| Lever | File | Effect |
|:--|:--|:--|
| Tagging prompt wording | `prompts/tagging.md` | Changes how signals are classified |
| Tagging batch size | `pipeline.yaml` | More/fewer signals per LLM call |
| Clustering thresholds | `pipeline.yaml` | Tighter/looser cluster formation |
| Merge threshold | `pipeline.yaml` | How aggressively similar clusters are merged |
| Scoring weights | `pipeline.yaml` | Which criteria matter more/less |
| Kill criteria thresholds | `pipeline.yaml` | How aggressively bad opportunities are filtered |
| Enrichment trigger thresholds | `pipeline.yaml` | Which clusters advance to enrichment |
| Ingest queries | `pipeline.yaml` | What signals are collected |
| Source config (subreddits, categories) | `pipeline.yaml` | Where signals come from |
| Embedding model | `pipeline.yaml` | How signals are represented for clustering |
| Scoring prompt | `prompts/scoring.md` | How LLM evaluates criteria |
| Clustering prompt | `prompts/clustering.md` | How LLM labels and summarizes clusters |

### What the agent cannot change

- `prospect.py` — the pipeline engine, source adapters, and metric computation
- The composite-metric weights inside `prospect.py` (see §4)
- The evaluation metric definitions
- The backtest case definitions
- The signal files from previous runs

---

## 4. The Metric: `pipeline_score`

Autoresearch has one clean number: `val_bpb`. Prospect needs the same — a single composite score that the agent optimizes, computed automatically after every run.

### Why a single number

No single number perfectly captures "is this pipeline finding good business opportunities." But without one, the agent can't decide keep/discard. The solution: a composite score built from measurable stage-level metrics, validated against backtest ground truth.

### `pipeline_score` definition

```
pipeline_score = (
    0.15 × ingest_quality +
    0.20 × tag_quality +
    0.25 × cluster_quality +
    0.15 × enrichment_quality +
    0.15 × score_quality +
    0.10 × model_quality
) × backtest_multiplier
```

Each component is normalized to 0.0–1.0. The `backtest_multiplier` scales the whole score by how well the pipeline separates known successes from failures.

**Where these weights live.** The six component weights and the `backtest_multiplier` formula are defined as frozen constants inside `prospect.py`. They are *not* exposed in `pipeline.yaml` and the agent cannot modify them — changing the metric definition mid-experiment makes longitudinal comparisons meaningless. Per §6.3, changing the metric requires a human-edited code change.

> Don't confuse these with the 7-criterion *scoring* weights (market_demand, distribution, …) that the agent tunes in `pipeline.yaml`. Those rank clusters within a run. These six rank the pipeline against itself across runs.

### Component definitions

#### `ingest_quality` (0.0–1.0)

```
ingest_quality = mean(
    min(coverage / 10, 1.0),                       # ≥10 sources → 1.0
    min(volume / 500, 1.0),                        # ≥500 signals → 1.0
    schema_completeness,                           # % with all required fields
    freshness_score,                               # see below
    duplication_score                              # see below
)

# freshness_score: tent function peaking at the target band 0.5–0.7
# (i.e. 50–70% of signals posted within the last 12 months is ideal).
# Penalize both stale-only and fire-hose-of-just-this-week corpora.
f = fraction_within_12_months
freshness_score = 1.0                   if 0.5 ≤ f ≤ 0.7
                = f / 0.5                if f < 0.5
                = max(0, 1.0 - (f - 0.7) / 0.3)  if f > 0.7

# duplication_score: 0% to 5% is fine; 5% to 15% degrades linearly;
# above 15% the corpus is too contaminated to trust.
d = fraction_with_duplicate_source_url
duplication_score = 1.0                  if d ≤ 0.05
                  = 1.0 - (d - 0.05) / 0.10   if 0.05 < d ≤ 0.15
                  = 0.0                  if d > 0.15
```

Measured automatically from the signal files in the run directory. No human input needed.

#### `tag_quality` (0.0–1.0)

```
tag_quality = mean(
    tag_coverage,                         # % where pain_type != 'unknown'
    intensity_distribution_health,        # penalize if >70% on one value
    workaround_precision,                 # cold-context audit (see below)
    spend_precision                       # cold-context audit (see below)
)
```

`intensity_distribution_health`: entropy of the intensity histogram, normalized so max entropy (uniform across 1–5) = 1.0, min entropy (everything on one value) = 0.0. Target is 0.5–0.8 (bell curve, not uniform).

`workaround_precision` and `spend_precision` (cold-context audit): the pipeline samples 20 signals tagged `has_workaround=yes` (and 20 tagged `has_spend=yes`), and passes ONLY the `raw_text` field — no tags, no prior reasoning, no tagging prompt — to an *auditor* model that is configured to be different from the tagger (different model family if available, otherwise same model with a fresh system prompt and temperature 0). The auditor answers a single yes/no question: "Does this text describe a manual workaround for a software problem?" (resp. "Does this text mention money spent on a software product or budget for one?"). Precision = #yes / 20. Manual override: if a `tag_audit.yaml` file exists for the run, its labels supersede the auditor's. The auditor is a weaker signal than a human spot-check but is genuinely independent of the tagger.

#### `cluster_quality` (0.0–1.0)

The most important component. Bad clusters corrupt everything downstream.

```
cluster_quality = mean(
    coherence_score,                      # cold-context auditor (see below)
    1.0 - clamp(orphan_rate, 0, 0.4),    # <20% orphans → 0.5+
    cluster_count_health,                 # penalize <5 or >100
    size_distribution_health,             # power-law is good, uniform is bad
    cross_platform_rate,                  # % of top clusters with source_diversity > 2
    overlap_health                        # 5-20% cross-cluster overlap is ideal
)
```

`coherence_score` (cold-context auditor): for each of the top 10 clusters, sample 5 signals and pass ONLY their `raw_text` fields to the auditor model (the same independent model used for `tag_quality`). The cluster's label and summary are NOT provided. The auditor answers: "Do these 5 texts describe the same underlying problem? Rate 0–5." Average across the 10 clusters, normalize to 0–1. Because the auditor never sees the LLM-generated cluster label, it cannot rationalize an incoherent grouping.

`cluster_count_health`: 1.0 if count is 15–50, linearly decreasing to 0.0 below 5 or above 100.

`size_distribution_health`: Gini coefficient of cluster sizes. Power-law distributions have Gini 0.4–0.7. Uniform has Gini ≈ 0. Normalize: Gini 0.4–0.7 → 1.0, outside that range → decreasing.

#### `enrichment_quality` (0.0–1.0)

```
enrichment_quality = mean(
    avg_completeness / 8,                 # 8 data points per cluster, 0–1
    competitor_discovery_rate,            # % clusters with ≥3 competitors
    pricing_availability,                 # % clusters with pricing data
    data_recency_score                    # 1.0 if all <6mo, 0.0 if all >18mo
)
```

#### `score_quality` (0.0–1.0)

```
score_quality = mean(
    evidence_linkage,                     # % scores with ≥1 evidence link
    range_utilization,                    # entropy of score distribution / max entropy
    confidence_coverage                   # % high-confidence in top-3 clusters
)
```

#### `model_quality` (0.0–1.0)

```
model_quality = mean(
    input_traceability,                   # % model inputs with source citation
    scenario_spread_health,               # 2-5× spread → 1.0, <1.5 or >10 → 0.0
    conservative_viable ? 1.0 : 0.0,      # does conservative case reach target
    sensitivity_identified ? 1.0 : 0.0    # was the kill-input identified
)
```

#### `backtest_multiplier` (0.5–1.5)

If a backtest has been run:

```
backtest_multiplier = 0.5 + (
    0.20 × clamp(separation / 2.0, 0, 1)  +
    0.30 × (top3_precision / 1.0) +
    0.25 × (bottom3_precision / 1.0) +
    0.15 × (kill_sensitivity / 1.0) +
    0.10 × (signal_presence / 1.0)
)
```

If no backtest exists yet: `backtest_multiplier = 1.0` (neutral).

The multiplier rewards pipelines that successfully separate known winners from losers and penalizes pipelines that can't.

### `results.tsv`

```
commit	pipeline_score	tag_quality	cluster_quality	backtest_mult	status	description
a1b2c3d	0.000	0.000	0.000	1.000	keep	baseline (first run)
b2c3d4e	0.642	0.780	0.650	1.000	keep	rewrite tagging prompt: clearer intensity scale
c3d4e5f	0.638	0.760	0.670	1.000	discard	batch_size 30 (tag accuracy dropped)
d4e5f6g	0.671	0.810	0.690	1.000	keep	workaround detection examples in prompt
e5f6g7h	0.724	0.810	0.740	1.120	keep	backtest passed, separation=1.3, adjusted weights
```

---

## 5. Evaluation: How to Know the System Is Improving

### 5.1 Three levels of evaluation

| Level | Question | Frequency | Metric |
|:--|:--|:--|:--|
| **Run-level** | Did this run produce better output than the last? | Every run | `pipeline_score` |
| **Longitudinal** | Is the pipeline getting better over time? | After every 5+ runs | Trend of `pipeline_score` across runs |
| **Ground-truth** | Does the pipeline actually predict real-world success? | After forward tests | Predicted-vs-actual delta |

### 5.2 Run-level metrics (automated, every run)

Computed by `prospect eval` after each run. Stored in `runs/{run_id}/metrics.yaml`.

```yaml
# runs/2026-04-14/metrics.yaml
run_id: "2026-04-14"
pipeline_score: 0.671

components:
  ingest_quality: 0.72
  tag_quality: 0.81
  cluster_quality: 0.69
  enrichment_quality: 0.58
  score_quality: 0.64
  model_quality: 0.55
  backtest_multiplier: 1.00

stage_details:
  ingest:
    coverage: 8
    volume: 347
    schema_completeness: 0.94
    freshness: 0.62
    duplication_rate: 0.03
  tag:
    tag_coverage: 0.87
    intensity_entropy: 0.71
    workaround_precision: 0.88
    spend_precision: 0.92
  cluster:
    coherence_score: 0.78
    orphan_rate: 0.18
    cluster_count: 23
    gini_coefficient: 0.52
    cross_platform_rate: 0.74
    overlap_rate: 0.12
  enrich:
    avg_completeness: 5.8
    competitor_discovery: 0.83
    pricing_availability: 0.67
    data_recency: 0.80
  score:
    evidence_linkage: 0.96
    range_utilization: 0.58
    confidence_coverage: 0.45
  model:
    input_traceability: 0.88
    scenario_spread: 3.2
    conservative_viable: true
    sensitivity_identified: true
```

### 5.3 Longitudinal metrics (track improvement over time)

Stored in `calibration/history.yaml`. Appended after each run.

```yaml
# calibration/history.yaml
runs:
  - run_id: "2026-04-01"
    pipeline_score: 0.52
    tag_quality: 0.65
    cluster_quality: 0.48
    config_hash: "abc123"
    generation: 1

  - run_id: "2026-04-07"
    pipeline_score: 0.61
    tag_quality: 0.74
    cluster_quality: 0.59
    config_hash: "def456"
    generation: 5

  - run_id: "2026-04-14"
    pipeline_score: 0.67
    tag_quality: 0.81
    cluster_quality: 0.69
    config_hash: "ghi789"
    generation: 12
```

`generation` counts how many keep/discard cycles have occurred. This is the x-axis of the improvement chart.

#### Key longitudinal metrics

| Metric | Computation | Meaning |
|:--|:--|:--|
| **Score trend** | Linear regression slope of `pipeline_score` across generations | Positive = improving. Flat = stalled. Negative = degrading. |
| **Score velocity** | Δ(pipeline_score) / Δ(generation) over last 5 runs | How fast improvement is happening. Decreasing = diminishing returns. |
| **Component rates** | Per-component slope across generations | Which stage is improving fastest? Which is stuck? The stuck stage is where to focus. |
| **High-water mark** | Max `pipeline_score` ever achieved | If recent runs are below it, something regressed. |
| **Improvement ceiling** | Moving average of last 10 Δ scores | If avg Δ → 0, current configuration space is exhausted. Time for structural changes. |
| **Config churn rate** | Parameters changed per generation | High churn + no improvement = flailing. Low churn + steady improvement = systematic. |
| **Backtest correlation** | Pearson r between `pipeline_score` and backtest separation | If r > 0.5, the composite metric is a valid proxy for real predictive power. If not, redesign the metric. |

#### The improvement chart

The equivalent of Karpathy's `progress.png`:

```
pipeline_score
    ^
0.8 |                                          ●
    |                                      ●
0.7 |                                  ●
    |                          ●   ●
0.6 |                  ●   ●
    |          ●   ●
0.5 |      ●
    |  ●
0.4 |
    +---+---+---+---+---+---+---+---+---+---→ generation
    0   2   4   6   8  10  12  14  16  18
```

Generated by `prospect chart` from `calibration/history.yaml`.

### 5.4 Ground-truth validation (backtest + forward test)

These answer: **does a higher `pipeline_score` actually predict better real-world outcomes?**

#### Backtest metrics

| Metric | Definition | Target |
|:--|:--|:--|
| **Separation** | Mean score(successes) − mean score(failures) | > 1.0 |
| **Top-3 precision** | Of 3 highest-scored cases, how many are actual successes? | ≥ 2/3 |
| **Bottom-3 precision** | Of 3 lowest-scored, how many are actual failures? | ≥ 2/3 |
| **Kill sensitivity** | Of 5 failures, how many hit ≥1 kill criterion? | ≥ 4/5 |
| **Signal presence** | Of 5 successes, how many had ≥10 pre-launch signals? | ≥ 4/5 |

#### Forward test metrics

| Metric | Check at | Pipeline right if... |
|:--|:--|:--|
| Problem confirmation | Week 1–4 | 80%+ of interviewees confirm the pain |
| Willingness to pay | Week 4–8 | Landing page converts >3% |
| Build time accuracy | Week 6–10 | MVP shipped within 2× estimate |
| First 10 customers | Day 90 | 10 paying customers acquired |
| $1k MRR | Month 4–6 | Reached $1k MRR |
| Churn accuracy | Month 6+ | Actual churn within 2× of model |
| Target MRR | Month 12–18 | On trajectory for target |

#### Predicted-vs-actual deltas

After each forward test milestone, compute the delta:

```yaml
# forward_tests/test_001.yaml
cluster_id: clust_017
predictions:
  problem_confirmation: 0.85
  willingness_to_pay: 0.70
  build_time_weeks: 6
  month_6_mrr: 3200
  month_6_churn: 0.05
actuals:
  problem_confirmation: 0.78
  willingness_to_pay: 0.45      # big miss
  build_time_weeks: 9           # 50% over
  month_6_mrr: 1800
  month_6_churn: 0.09           # almost 2× predicted
deltas:
  problem_confirmation: -0.07
  willingness_to_pay: -0.25     # scoring or enrichment failed here
  build_time_weeks: +3
  month_6_mrr: -1400
  month_6_churn: +0.04
```

These deltas feed directly back into the agent's loop:

- `willingness_to_pay` delta > 0.2 → agent increases `revenue_path` weight, tightens spend evidence requirements
- `build_time` delta > 50% → agent adjusts feasibility scoring to be more conservative
- `churn` delta > 2× → agent adds churn-relevant tagging signals (one-time-use indicators)

#### `calibration/bias_log.yaml`

Each forward-test result is appended to `bias_log.yaml`. This is the system's
record of where its predictions diverge from reality, broken out by criterion
so per-criterion miscalibration is visible.

```yaml
# calibration/bias_log.yaml
entries:
  - run_id: "2026-04-14T09-12-08"
    cluster_id: clust_017
    test_id: test_001
    closed_at: 2026-10-20         # date the milestone was reached
    criterion_deltas:             # predicted score (1-5) → observed score (1-5)
      market_demand:      {predicted: 4, observed: 4, delta:  0}
      distribution:       {predicted: 4, observed: 2, delta: -2}
      competition:        {predicted: 3, observed: 3, delta:  0}
      founder_market_fit: {predicted: 5, observed: 4, delta: -1}
      solo_feasibility:   {predicted: 4, observed: 2, delta: -2}
      revenue_path:       {predicted: 4, observed: 2, delta: -2}
      defensibility:      {predicted: 2, observed: 2, delta:  0}
    milestone_deltas: { ... copy from forward_tests/test_NNN.yaml ... }

# Aggregates (recomputed by `prospect calibrate`)
per_criterion_bias:
  distribution:       {n: 3, mean_delta: -1.7, stddev: 0.6}   # consistently overscored
  solo_feasibility:   {n: 3, mean_delta: -1.3, stddev: 0.9}
  market_demand:      {n: 3, mean_delta:  0.0, stddev: 0.4}
```

`mean_delta` is what the agent reads when it considers a weight adjustment.
A criterion with consistent negative delta and low stddev is a systematic
over-scoring bias and should be down-weighted or have its rubric tightened.

### 5.5 The meta-metric

From EVALUATION.md: **time-to-revenue relative to random selection.** Measurable only after 3–5 complete cycles (pipeline run → forward test → outcome).

```
If prospect_median_time_to_10k < random_median_time_to_10k → system works.
If not → methodology is waste. Abandon.
```

---

## 6. Self-Improvement Mechanics

### 6.1 What improves automatically (agent-driven)

Each iteration, the agent picks ONE change from this menu:

**Prompt tuning** — rewrite `prompts/tagging.md` to improve tag accuracy. Agent reads `metrics.yaml`, sees `workaround_precision = 0.72` (target: 0.90), reads 10 false-positive workaround tags, identifies the pattern, adds clarifying examples to the prompt.

**Threshold tuning** — adjust clustering thresholds. Agent sees `orphan_rate = 0.35` (target: < 0.20), lowers `min_cluster_size` from 5 to 3, re-runs, checks if orphan rate decreased without destroying coherence.

**Weight tuning** — adjust scoring weights. Forward test reveals distribution had the largest predicted-vs-actual delta. Agent increases `distribution` from 0.20 to 0.25, decreases `defensibility` from 0.05 to 0.00.

**Source tuning** — adjust ingest queries. Agent reads `calibration/source_quality.yaml`, sees r/smallbusiness has 0.12 SNR vs r/ExperiencedDevs at 0.67, drops or refines the low-SNR source.

**Enrichment trigger tuning** — if completeness is low because too many marginal clusters advance, raise thresholds. If too few advance, lower them.

### 6.2 What improves manually (human-driven via `program.md`)

- "Focus this week on improving cluster coherence — it's the bottleneck"
- "We completed a forward test. Here are the deltas. Prioritize willingness-to-pay miss."
- "Add G2 reviews for project management tools as a new source"
- "Run a backtest with these 5 new cases"
- "The tagging prompt is too long. Simplify while maintaining accuracy."

### 6.3 What cannot be improved by the loop

These require human judgment and structural changes — the equivalent of "changing `prepare.py`":

- Adding new pipeline stages
- Changing the composite metric formula
- Adding new scoring criteria
- Fundamental architecture changes (different clustering algorithm)
- Redefining evaluation thresholds

---

## 7. Pipeline Stage Design (Summary)

### Stage 1: Ingest
Source adapters collect signals, normalize to YAML schema, write one file per signal. Dedup by `source_url` across runs. Duplicate count tracked separately.

### Stage 2: Tag
LLM tags signals in batches using `prompts/tagging.md`. Per-tag justification quotes stored for automated precision checks. One YAML per tagged signal.

### Stage 3: Cluster

Generate embeddings → HDBSCAN → merge similar clusters → LLM labeling → cross-assign → compute metrics. One YAML per cluster with signal_ids list.

**Contract specification.** Several details under-specified by SPECIFICATION.md are pinned here so the implementation is deterministic and the autoresearch loop can attribute changes:

- **Representative selection (for LLM labeling).** Stratified by `source_platform`: at most 2 reps per platform, fill the remaining slots up to 5 with the next-closest-to-centroid signals across all platforms. Prevents a Reddit-only sample from labeling a cross-platform cluster in Reddit voice.
- **Cross-assignment algorithm.** Signal-to-centroid one-direction: a signal `s` is cross-assigned to cluster `c` iff `cosine(embed(s.raw_text), centroid(c)) > cross_assign_threshold` AND `c` is not `s`'s primary cluster. Each signal capped at 3 total cluster memberships (primary + up to 2 secondary) to prevent overlap-rate runaway. Cross-assignment does NOT modify the signal's primary cluster.
- **Primary vs total counts.** Cluster metrics distinguish `primary_signal_count` (signals whose hard HDBSCAN assignment is this cluster) from `total_signal_count` (primary + cross-assigned). Kill criteria and enrichment triggers read `primary_signal_count`; demand evidence reads `total_signal_count`.
- **Temporal trend.** Bin members by `date_posted` into monthly buckets, fit linear regression on bucket counts, classify slope: `increasing` if >+5%/month, `stable` if within ±5%, `decreasing` if <-5%. Requires ≥6 months of signal date range; otherwise emit `unknown`.
- **Source diversity (two flavors).** `source_diversity` = count of distinct `source_platform` values (platform-level). `context_diversity` = count of distinct `source_context` values (e.g. distinct subreddits, distinct G2 product pages). `cluster_quality.cross_platform_rate` uses `context_diversity > 2`, which is the stronger echo-chamber filter.
- **Cluster fingerprint (cross-run identity).** `cluster_fingerprint = sha256(sorted(top3_central_signal_ids))[:12]`. The fingerprint is the stable identity carried in `calibration/history.yaml`, enabling claims like "this cluster grew from 47 to 62 signals over two runs." `cluster_id` itself remains run-local.
- **Embedding model in metrics.** `metrics.yaml` records `embedding_model`. Changing it invalidates fingerprint continuity; the longitudinal chart annotates model-change generations so a sudden coherence shift isn't read as agent progress.

### Stage 4: Enrich
Clusters passing triggers get market research: competitors, pricing, demand, funding, regulatory, distribution channels. Mix of automated and manual. One YAML per enriched cluster.

### Stage 5: Score
7-criterion rubric with evidence chains. Weighted total. Kill criteria. One YAML per scored cluster + `ranking.yaml`.

### Stage 6: Model
Top 2–3 clusters get 3-scenario 24-month projections. Sensitivity analysis. Risk factors. One YAML per modeled cluster.

---

## 8. CLI Interface

```bash
# Core pipeline
prospect run                     # full pipeline: all 6 stages
prospect run --stages ingest,tag # specific stages only
prospect eval                    # compute metrics for latest run
prospect chart                   # print improvement chart to terminal

# Autoresearch mode
prospect loop                    # start the autonomous improvement loop
prospect loop --max-gen 20       # cap iterations

# Inspection
prospect signals                 # list signals in latest run
prospect clusters                # list clusters with metrics
prospect cluster clust_017       # full cluster detail
prospect ranking                 # scored ranking table
prospect trace clust_017         # full chain: model → score → cluster → signals

# Backtesting
prospect backtest add-case ...
prospect backtest run
prospect backtest eval

# Forward testing
prospect forward-test start clust_017
prospect forward-test update test_001
prospect forward-test report

# Calibration
prospect calibrate               # longitudinal metrics + bias report
prospect source-quality          # source SNR ranking
prospect history                 # results.tsv viewer
prospect diff run_a run_b        # diff configs + metrics between runs
```

---

## 9. `program.md` — Baseline

```markdown
# Prospect Research Program

## Your role
You are an autonomous research agent improving a business opportunity
detection pipeline. You modify pipeline.yaml and prompts/*.md to improve
the pipeline_score metric. You do not modify prospect.py or prepare.py.

## The experiment loop
1. Read calibration/history.yaml to understand the trend
2. Read the latest metrics.yaml to find the weakest component
3. Propose ONE change targeting the weakest component
4. Commit, run, measure, keep or discard
5. Never stop. Never ask for permission. Loop until interrupted.

## Strategy
- Tag accuracy first — everything downstream depends on it
- Cluster coherence second — bad clusters corrupt scoring
- Score calibration third — only after 1 and 2 are solid
- One change per experiment (compound changes are unattributable)
- If 5 consecutive experiments show no improvement, try something
  qualitatively different (don't keep tweaking the same lever)
- Log your reasoning in the commit message

## Current focus
[Human updates this section to direct the agent's attention]
```

---

## 10. What Success Looks Like

**After 30+ generations:**
- `pipeline_score` shows a clear upward trend from ~0.5 to ~0.8
- Backtest separation is >1.0 and stable
- Tag accuracy (manual audit) exceeds 80%
- Cluster coherence (manual audit) exceeds 80%
- Commit log shows clear reasoning: "tried X, measured Y, kept/discarded because Z"
- `prompts/*.md` evolved from generic to calibrated, example-rich
- `pipeline.yaml` weights shifted from defaults to empirically validated values

**After 3+ forward tests:**
- `prospect_median_time_to_10k < baseline_median_time_to_10k`
- Or: the data shows it doesn't work, and the methodology is abandoned honestly

*Everything is files. Everything is diffable. Every change is measured. The pipeline improves itself.*
