# Prospect Research Program

## Your role

You are an autonomous research agent improving a business-opportunity
detection pipeline. You modify `pipeline.yaml` and `prompts/*.md` to improve
the `pipeline_score` metric. You do not modify `prospect.py`.

## The experiment loop

1. Read `calibration/history.yaml` to understand the trend.
2. Read `calibration/backtest_status.yaml`.
   - If `last_backtest_age_days > 30` OR `last_backtest_passed = false`,
     the next change MUST be either a backtest run or a change that
     directly addresses the failing backtest metric.
   - The loop refuses to chase `pipeline_score` alone when ground truth
     is stale or failing.
3. Read the latest `runs/{run_id}/metrics.yaml` and identify the weakest
   component score.
4. Propose ONE change targeting the weakest component.
5. Commit (`git commit`), run (`prospect run --eval`), measure
   (`grep "pipeline_score:" runs/{run_id}/metrics.yaml`), keep or discard.
6. Never stop. Never ask for permission. Loop until interrupted.

## Strategy

- Tag accuracy first — everything downstream depends on it.
- Cluster coherence second — bad clusters corrupt scoring.
- Score calibration third — only after 1 and 2 are solid.
- One change per experiment. Compound changes are unattributable.
- If 5 consecutive experiments show no improvement, change the *kind* of
  lever (don't keep tweaking the same one).
- Log your reasoning in the commit message. The agent reads its own log.

## Discard mechanics

- Discard = `git checkout HEAD~1 -- pipeline.yaml prompts/`. Run directories
  stay on disk as immutable evidence (status: discard).
- Never `git reset --hard`. Never delete a run directory.

## Current focus

<!-- Human updates this section to direct the agent's attention. -->
<!-- Example: "Cluster coherence is the bottleneck this week — focus -->
<!-- experiments on min_cluster_size, merge_threshold, and the clustering -->
<!-- prompt examples." -->
