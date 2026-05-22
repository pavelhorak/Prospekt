# Prospect

Turn raw internet pain signals into ranked solo-founder business opportunities.
Files on disk, git-tracked, agent-tunable. No data is ever deleted.

## What it does

Six-stage pipeline — **ingest → tag → cluster → enrich → score → model** —
followed by an autoresearch loop that tunes `pipeline.yaml` and `prompts/` to
improve a composite `pipeline_score` across runs. Every recommendation traces
back to the original Reddit post, G2 review, or Upwork job that contributed.

## Status

**Ingest works end-to-end; downstream stages stubbed.** Stage 1 ingest
produces real signal corpora via `adapters.py` — Hacker News, Stack
Overflow, GitHub Issues, and Google Trends (the first three are
zero-config; Google Trends soft-skips while pytrends chases Google's
backend changes). A first demo run produced 318 signals across three
platforms in ~90 seconds.

Stages 2–6 (tag → model) and the cluster engine raise
`NotImplementedError` with a one-line "what to wire next" note in their
docstrings. See `stage_cluster` for the inline contract style every
stage will carry.

Reddit, G2, Capterra, Upwork, LinkedIn — adapters not yet wired (Reddit
because of post-2023 OAuth setup friction; G2/Capterra because of
Cloudflare; Upwork/LinkedIn because of anti-bot).

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
