# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project context

Prospect is a six-stage pipeline (**ingest → tag → cluster → enrich → score → model**) that turns internet pain signals into ranked solo-founder business opportunities, wrapped in a Karpathy-style autoresearch loop that tunes itself via git commits.

**Status: ingest + tag + cluster wired; enrich → model still stubbed.** The CLI dispatches, the directory layout is created, all pure-math metrics are implemented.

- `stage_ingest` produces real signal corpora via `adapters.py` (HN, Stack Overflow, GitHub Issues, Google Trends via trendspy, Reddit). Reddit needs `REDDIT_CLIENT_ID` + `REDDIT_CLIENT_SECRET`; the rest are zero-config.
- `stage_tag` calls Claude via `tagger.py` using `prompts/tagging.md`, batches per `pipeline.yaml:tagging.batch_size`, writes per-signal tag files with verbatim justification quotes. Requires `ANTHROPIC_API_KEY`. Resume-safe.
- `stage_cluster` runs `clusterer.py`: sentence-transformers embed (disk-cached per `sha256(raw_text)` in `runs/{rid}/.cache/`), sklearn HDBSCAN, greedy centroid merge above `merge_threshold`, stratified rep selection (≤2 per source_platform), Claude labeling via `prompts/clustering.md` (INCOHERENT escape hatch), capped cross-assignment, primary vs total counts, `cluster_fingerprint = sha256(sorted(top-3 central signal_ids))[:12]`. Tag-dependent metrics (intensity histogram, industry spread, workaround/spend counts, competitor mentions) populate only when `runs/{rid}/tags/` is non-empty.
- `stage_enrich` through `stage_model` raise `NotImplementedError` with a one-line "what to wire next" note.

`cmd_run` now finalizes `run.yaml` on exit: success sets `status: completed` + `finished_at`; exceptions set `status: failed`, `failed_stage`, `error`, `finished_at` — and the exception still propagates so CI can detect failure.

Three design docs carry the load. Read in this order before non-trivial work:
1. `DESIGN.md` §3 (the autoresearch loop) — the heart of the system
2. `SPECIFICATION.md` — per-stage data model and tagging dimensions
3. `EVALUATION.md` — stage-level metrics, backtest and forward-test protocols

## Commands

```bash
pip install -r requirements.txt        # only pyyaml right now
python prospect.py init                # bootstrap calibration/, results.tsv (idempotent)
python prospect.py --help              # 17 subcommands
python prospect.py run                 # all stages (currently raises in stage_ingest)
python prospect.py run --stages tag,cluster --eval
python prospect.py history             # print results.tsv
```

No formal test suite yet. The pure-math metric functions are designed for inline smoke-tests:
```bash
python3 -c "import prospect as p; assert p.freshness_score(0.6)==1.0; assert abs(p.duplication_score(0.10)-0.5)<1e-9; assert p.cluster_count_health(30)==1.0"
```

## Architecture rules (non-obvious — read before editing)

### The two-axis split

| File | Edited by | Why |
|---|---|---|
| `prospect.py` | humans only | Engine + frozen metric weights. Changing it invalidates longitudinal `pipeline_score` comparisons. |
| `pipeline.yaml` | the autoresearch agent | All tunable knobs: sources, prompts, thresholds, the 7-criterion scoring weights, auditor config. |
| `prompts/*.md` | the autoresearch agent | Per-stage LLM prompts. |
| `program.md` | humans only | Agent meta-instructions. Sets the current focus and the loop's discipline. |

If you add a knob, decide deliberately: agent-tunable → `pipeline.yaml`; frozen → `prospect.py`. **Two unrelated weight systems coexist** — do not conflate them:

- **Composite-metric weights** (`ingest_quality`, `tag_quality`, …) — frozen in `prospect.py:PIPELINE_SCORE_WEIGHTS`. Rank the pipeline against itself *across* runs.
- **7-criterion scoring weights** (`market_demand`, `distribution`, …) — agent-tunable in `pipeline.yaml`. Rank clusters *within* one run.

### No database, files only

Everything is YAML on disk, tracked in git. Run directories under `runs/{utc-timestamp}/` are **immutable** by design rule. Never:
- `git reset --hard`
- `rm -rf runs/...`
- modify a previously-emitted signal / tag / cluster file

The autoresearch loop "discards" a failed experiment via config-only revert:
```bash
git checkout HEAD~1 -- pipeline.yaml prompts/
```
The run directory stays on disk as evidence with `status: discard` in `run.yaml`.

### Cold-context auditor pattern (DESIGN.md §4)

`workaround_precision`, `spend_precision`, and `coherence_score` MUST be computed by a model *different* from the tagger/clusterer, fed *only* the `raw_text` field — no prior labels, no tagging prompt, no cluster summary. Auditor config lives under `audit:` in `pipeline.yaml`. Don't introduce same-model self-checks: they go up when the model is confident, not when it's right.

### Backtest gate

The autoresearch loop (see `program.md`) reads `calibration/backtest_status.yaml` first. If `last_backtest_age_days > 30` or `last_backtest_passed = false`, the next change MUST address the backtest. This stops runaway `pipeline_score` optimization without ground truth.

### IDs and cross-run identity

- Run ID: UTC timestamp `2026-04-14T09-12-08` (no prefix)
- Signal ID: `sig_` + 12 hex chars (UUID4 prefix)
- Cluster ID: `clust_NNN` — run-local
- Cross-run cluster identity: `cluster_fingerprint = sha256(sorted(top-3 central signal_ids))[:12]`
- Backtest: `bt_`, forward test: `ft_`

Changing the embedding model invalidates fingerprint continuity — `metrics.yaml` records `embedding_model` and the longitudinal chart annotates model-change generations so a coherence shift isn't misread as agent progress.

### Cluster stage failure modes

`stage_cluster` in `prospect.py` carries five known failure modes in its docstring (style-based clustering, long-tail starvation, label hallucination, cross-assignment runaway, embedding-model invalidation). Read them before changing clustering thresholds, `min_cluster_size`, or the embedding model in `pipeline.yaml`.

## Git workflow

Commits on `origin/main` use the GitHub noreply alias `22235234+pavelhorak@users.noreply.github.com`. The local `user.email` is the gmail, which GitHub rejects on push due to the user's email-privacy setting. Use the noreply alias for new commits:

```bash
git -c user.email=22235234+pavelhorak@users.noreply.github.com \
    -c user.name=Pavel \
    commit -m "..."
```

Existing commits in the repo do not use the `Co-Authored-By` footer — match that style.
