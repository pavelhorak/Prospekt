# Prospect

Turn raw internet pain signals into ranked solo-founder business opportunities.
Files on disk, git-tracked, agent-tunable. No data is ever deleted.

## What it does

Six-stage pipeline — **ingest → tag → cluster → enrich → score → model** —
followed by an autoresearch loop that tunes `pipeline.yaml` and `prompts/` to
improve a composite `pipeline_score` across runs. Every recommendation traces
back to the original Reddit post, G2 review, or Upwork job that contributed.

## Status

**Stages 1–2 wired; clustering → modeling still stubbed.**

Stage 1 ingest produces real signal corpora via `adapters.py`:

- Hacker News, Stack Overflow, GitHub Issues — zero-config, free
- Google Trends — via `trendspy` (pytrends was dropped after Google's
  2024-2025 backend changes returned HTTP 400 universally)
- Reddit — application-only OAuth; set `REDDIT_CLIENT_ID` +
  `REDDIT_CLIENT_SECRET` (one-time, free; register a "web app" at
  reddit.com/prefs/apps). Soft-skips when creds missing.

Two committed real-data runs: 318 signals from three sources, then 3
Google Trends signals from the second run.

Stage 2 tag calls Claude via `tagger.py` against `prompts/tagging.md`
in batches; writes one tag file per signal with verbatim justification
quotes. Requires `ANTHROPIC_API_KEY`. Resume-safe.

Stage 3 cluster runs `clusterer.py`: sentence-transformers MiniLM
embeddings (disk-cached), sklearn HDBSCAN, greedy centroid merge,
stratified representative selection, Claude labeling with an explicit
`INCOHERENT` escape hatch, capped cross-assignment, and per-cluster
metrics (primary vs total counts, source/context diversity, temporal
trend, intensity histogram and competitor mentions when tags exist).
Emits `runs/{rid}/clusters/clust_NNN.yaml` + `clusters/index.yaml`.

Stage 4 enrich runs `enricher.py`: Claude with the `web_search_20250305`
tool researches the 8 enrichment data points per cluster (competitors,
pricing, weaknesses, market size, search demand, funding, regulatory,
distribution channels). Filters by `enrichment.triggers` and skips
INCOHERENT/PARSE_ERROR clusters. Citations are preserved in the output.

`prospect eval` walks a run dir, computes the six `pipeline_score`
components using the pure metric functions in `prospect.py`, writes
`runs/{rid}/metrics.yaml`, and appends to `calibration/history.yaml`
and `results.tsv`. The cold-context auditor (`auditor.py`) runs by
default when `ANTHROPIC_API_KEY` is set; `--no-audits` skips it.
First eval against the existing 318-signal corpus: `pipeline_score =
0.1013` (ingest_quality 0.675; tag/cluster/enrich = 0 — those stages
haven't run on that corpus yet).

Stages 5–6 (score → model) raise `NotImplementedError`.

G2, Capterra, Upwork, LinkedIn — adapters not yet wired (Cloudflare /
anti-bot / paid API).

## Quick start

```bash
pip install -r requirements.txt
python prospect.py init        # creates calibration/, results.tsv, .gitkeep
python prospect.py --help      # 17 subcommands
python prospect.py history     # print the experiment log
```

## Usage

```
prospect init                  bootstrap directory layout (idempotent)
prospect run [--stages …]      run a pipeline (stages comma-separated)
       --eval                  also compute pipeline_score after the run
       --run-id ID             override the auto-generated UTC timestamp
prospect eval                  compute metrics for the latest run
prospect chart                 ASCII improvement chart over generations
prospect history               print results.tsv
prospect loop                  start the autonomous improvement loop

# Inspection
prospect signals | clusters | cluster ID | ranking | trace ID

# Validation
prospect backtest add-case | run | eval
prospect forward-test start | update | report

# Calibration
prospect calibrate | source-quality | diff RUN_A RUN_B
```

Run stages individually for development: `prospect run --stages ingest,tag`.

## Layout

```
prospect.py            engine — frozen, not tuned by the loop
pipeline.yaml          all agent-tunable config (sources, prompts, thresholds, weights)
program.md             agent meta-instructions (human-edited)
prompts/               per-stage LLM prompts (agent-tunable)
runs/{run_id}/         per-run signals, tags, clusters, enrichments, scores, models
backtests/             ground-truth cases + backtest runs + results
forward_tests/         predicted-vs-actual milestones for shipped products
calibration/           longitudinal metrics, bias log, source SNR, backtest status
results.tsv            commit · pipeline_score · status — the experiment log
```

Run IDs are UTC timestamps (`2026-04-14T09-12-08`). Signal IDs are
`sig_` + 12 hex chars; clusters carry a separate `cluster_fingerprint`
for cross-run identity. See DESIGN.md §2 for the full ID table.

## The autoresearch loop

Adapted from [karpathy/autoresearch](https://github.com/karpathy/autoresearch).
The agent reads the latest `metrics.yaml`, proposes ONE change to
`pipeline.yaml` or a prompt, runs the pipeline, measures `pipeline_score`,
and keeps or discards via git.

Discard = `git checkout HEAD~1 -- pipeline.yaml prompts/` — config-only
revert. Run directories under `runs/` are immutable and stay as evidence
of what was tried. The composite-metric weights live as frozen constants
inside `prospect.py` so longitudinal comparisons remain meaningful when
the agent retunes everything else.

The loop will refuse to chase `pipeline_score` alone when
`calibration/backtest_status.yaml` shows a stale (>30 days) or failing
backtest — see `program.md`.

## Design docs

- **SPECIFICATION.md** — pipeline philosophy and per-stage data model
- **DESIGN.md** — system design, autoresearch loop, composite metric, IDs
- **EVALUATION.md** — stage-level metrics, backtest, forward-test protocols

Read DESIGN.md §3 first.
