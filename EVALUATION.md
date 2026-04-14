
**PIPELINE EVALUATION**  
**FRAMEWORK**

How to measure whether the data processing pipeline

produces reliable, actionable business opportunity recommendations

Companion to: Data Processing Specification

# **The Problem**

The pipeline has six stages: ingest, tag, cluster, enrich, score, model. Each stage transforms data. But how do you know if the transformations are correct? How do you know if the final ranked list of opportunities is actually good?

Without an evaluation framework, you have no way to distinguish between a pipeline that surfaces real opportunities and one that produces plausible-sounding garbage. The output of both looks the same: a ranked table with scores and evidence links. The difference only shows up months later when you either have $10k MRR or a failed product.

This document defines how to measure pipeline quality at every stage, how to detect when it is failing, and how to improve it over time.

# **Three Types of Evaluation**

The pipeline can be evaluated in three fundamentally different ways. Each answers a different question.

| Evaluation Type | Question It Answers | When to Use It | Cost |
| :---- | :---- | :---- | :---- |
| Stage-level metrics | Is each stage doing its job correctly? Are tags accurate? Are clusters coherent? Are scores calibrated? | During pipeline development and after every run | Low — can be done on the output of any run |
| Backtest | Would this pipeline have surfaced known successful products and filtered known failures? | Once, to validate the methodology before trusting it | Medium — requires researching 5-10 historical cases |
| Forward test | Does the top-ranked opportunity from a blind run actually become a viable business? | After the pipeline is calibrated and you are ready to commit | High — requires building the product and finding out |

Most people skip to the forward test (just build something and see). The whole point of the pipeline is to make the forward test cheaper by filtering bad ideas before you invest months. But the pipeline itself needs validation first. That is what stage-level metrics and backtests provide.

# **Stage-Level Metrics**

Each pipeline stage has measurable outputs. For each stage, we define: what good output looks like, what bad output looks like, and how to measure the difference.

## **Stage 1: Ingest**

**What it produces:** Raw signal records in a uniform schema.

| Metric | How to Measure | Good | Bad | What Bad Means |
| :---- | :---- | :---- | :---- | :---- |
| Coverage | Count unique sources that produced at least 1 signal | ≥10 distinct source platforms | \<5 sources | You are only seeing one corner of the internet. Signals are biased toward one community. |
| Volume | Total signals collected | 200-2000 per run | \<50 | Not enough data to cluster meaningfully. Either your queries are too narrow or your sources are too few. |
| Schema completeness | % of signals with all required fields filled (raw\_text, source\_url, source\_platform, engagement, date\_posted) | \>90% | \<70% | Missing fields mean you cannot tag, cluster, or trace back. Usually means the scraping/collection is sloppy. |
| Freshness | % of signals posted within last 12 months | \>50% | \<20% | You are collecting stale pain. The problem may already be solved. Old signals are useful as durability evidence but should not dominate. |
| Duplication rate | % of signals with identical source\_url | \<5% | \>15% | Your queries overlap too much, or you are scraping the same content from multiple aggregators. Deduplicate by URL, but keep both records — different collection paths to the same signal are metadata, not waste. |

## **Stage 2: Tag**

**What it produces:** Structured metadata on every signal.

| Metric | How to Measure | Good | Bad | What Bad Means |
| :---- | :---- | :---- | :---- | :---- |
| Tag accuracy (sample audit) | Randomly select 30 signals. Read the raw text. Independently assign tags. Compare your tags to the pipeline’s tags. | \>80% agreement on pain\_type, \>70% on industry and buyer\_persona | \<60% agreement | The tagging logic (whether human or LLM) is misreading signals. Retrain or re-prompt. |
| Tag coverage | % of signals where pain\_type is not ‘unknown’ | \>85% | \<60% | Too many signals are ambiguous. Either the signals are too vague (collection problem) or the tagging categories are too narrow (taxonomy problem). |
| Intensity distribution | Histogram of pain\_intensity across all signals | Bell curve centered on 2-3, with a meaningful tail at 4-5 | Almost everything is 1-2 or almost everything is 4-5 | If everything is low-intensity, your sources are surfacing annoyances, not real pain. If everything is high-intensity, your tagging is inflated — not every signal is a crisis. |
| Workaround detection rate | % of signals tagged has\_workaround=yes where the raw text actually describes a workaround | \>90% precision | \<70% precision | False positives on workarounds are dangerous because workaround count is a primary cluster quality signal. Audit these carefully. |
| Spend detection rate | % of signals tagged has\_spend=yes where the raw text actually mentions money | \>95% precision | \<80% precision | False positives on spend signals corrupt your willingness-to-pay estimates downstream. |

## **Stage 3: Cluster**

**What it produces:** Problem clusters with signals grouped by underlying pain.

| Metric | How to Measure | Good | Bad | What Bad Means |
| :---- | :---- | :---- | :---- | :---- |
| Cluster coherence (sample audit) | For each of the top 10 clusters: read 5 random member signals. Do they all describe the same underlying problem? | 4-5 out of 5 signals clearly describe the same problem in each cluster | 2 or fewer match | Clusters are too loose. Signals about different problems are being grouped together. Reduce min\_cluster\_size or refine the clustering prompt. |
| Orphan rate | % of signals that belong to no cluster | \<20% | \>40% | Too many signals are unclustered. Either your clustering is too strict, or many of your signals are genuinely unique (which suggests your queries are too broad). |
| Cluster count | Total number of clusters | 15-50 from 200-2000 signals | \<5 or \>100 | \<5 means your clustering is too aggressive and merging distinct problems. \>100 means it is too granular and splitting one problem into fragments. |
| Signal-per-cluster distribution | Histogram of cluster sizes | Power law: a few large clusters (10-50 signals), many small ones (3-10) | All clusters same size (5-10 each) | Uniform distribution suggests arbitrary grouping rather than natural clustering. Real demand is uneven — some problems are much more widespread than others. |
| Cross-cluster signal overlap | % of signals that belong to \>1 cluster | 5-20% | \>40% or 0% | \>40% means your clusters are not distinct enough. 0% means you are forcing single membership and missing that some signals touch multiple opportunities. |
| Source diversity per cluster | Average number of unique source platforms per cluster | \>2 for top clusters | 1 for most clusters | If top clusters only draw from one source, they may be echo chambers. Cross-platform confirmation is what separates real demand from community bias. |

## **Stage 4: Enrich**

**What it produces:** Market data layered onto clusters.

| Metric | How to Measure | Good | Bad | What Bad Means |
| :---- | :---- | :---- | :---- | :---- |
| Enrichment completeness | For each enriched cluster, count how many of the 8 enrichment data points are filled | \>6 out of 8 filled for every enriched cluster | \<4 filled | You are scoring with insufficient data. Scores based on thin enrichment are guesses, not assessments. |
| Competitor discovery | For each enriched cluster, count identified competitors | ≥3 direct competitors found | 0 competitors found | Either the market truly does not exist (kill signal) or your search was too narrow. Try broader queries before concluding. |
| Pricing data availability | % of enriched clusters with at least one competitor’s pricing documented | \>80% | \<50% | Without pricing benchmarks, your revenue path scoring is pure speculation. |
| Data recency | Age of the enrichment data (competitor websites, funding rounds, Google Trends) | All data from last 6 months | Data older than 18 months | Stale enrichment data means your competitive landscape may have shifted. Refresh before scoring. |

## **Stage 5: Score**

**What it produces:** Ranked opportunities with 7-criterion scores.

| Metric | How to Measure | Good | Bad | What Bad Means |
| :---- | :---- | :---- | :---- | :---- |
| Score-evidence linkage | For each score on each criterion: does the evidence cited actually support the score? | 100% of scores have at least one specific evidence link | Any score without evidence | Unlinked scores are opinions. They will not survive scrutiny and should not drive decisions. |
| Inter-rater reliability | Have 2 people independently score the same cluster. Compare scores per criterion. | Scores differ by ≤1 point on each criterion | Scores differ by ≥3 on any criterion | The scoring rubric is ambiguous. The criterion definitions need to be more specific, or the evidence is being interpreted differently. |
| Score range utilization | Distribution of scores across all clusters and criteria | Scores span 1-5 with meaningful spread | All scores cluster around 3-4 | If everything scores 3-4, the rubric is not discriminating. Either the criteria are too vague or you are unconsciously avoiding extreme scores. Force yourself to use 1s and 5s. |
| Rank stability | Re-score the same clusters one week later without looking at original scores. Does the ranking change? | Same top-3 in both runs | Completely different top-3 | Your scoring is sensitive to mood, not data. The evidence is too ambiguous to produce stable judgments. You need more enrichment data. |
| Confidence coverage | % of scores rated ‘high confidence’ vs ‘low confidence’ | \>50% high confidence for top-3 clusters | \<30% high confidence for top-3 | You are about to commit to an opportunity where most of your knowledge is guesswork. Go back to Stage 4 and enrich more before deciding. |

## **Stage 6: Model**

**What it produces:** Unit economics projections and a final recommendation.

| Metric | How to Measure | Good | Bad | What Bad Means |
| :---- | :---- | :---- | :---- | :---- |
| Input traceability | Can every model input (ARPU, churn, acquisition rate, market size) be traced to a specific enrichment data point? | 100% traceable | Any input is a guess without source | Your projection is fiction built on assumptions. It will tell you whatever you want to hear. |
| Scenario spread | Ratio between optimistic and conservative MRR at month 18 | 2-5x difference | \<1.5x or \>10x difference | \<1.5x means your scenarios are not actually testing different assumptions. \>10x means your inputs are so uncertain the model is meaningless. |
| Conservative case viability | Does the conservative scenario reach target MRR within 24 months? | Yes | No | If even the worst case does not work, the opportunity fails regardless of how good the optimistic case looks. |
| Sensitivity identification | Which single input, if wrong by 2x, changes the recommendation? | Clearly identified with a named risk | Not tested | You do not know what could kill the business. This is the most dangerous blind spot. |

# **Backtest Protocol**

A backtest validates the entire pipeline end-to-end against known outcomes. It answers: **if I had run this pipeline 2 years ago, would it have surfaced today’s winners and filtered today’s failures?**

## **How to Run a Proper Backtest**

The key requirement is **outcome blindness during signal collection.** You must not let your knowledge of whether a product succeeded or failed influence which signals you collect or how you tag them. This is extremely hard in practice, which is why the protocol is strict.

1. **Select 10 cases: 5 confirmed successes, 5 confirmed failures.** Successes: solo/small-team SaaS products with verified revenue above $10k/month (IndieHackers open startups, Baremetrics dashboards, public revenue posts). Failures: products that launched, gained some traction, and then shut down or stagnated below $1k/month (IndieHackers postmortems, ProductHunt launches that went quiet, Acquire.com listings with declining revenue). Document each case with: product name, what it does, launch date, current revenue (or shutdown date), and the founder’s public account of why it succeeded or failed.

2. **For each case, set the clock back to 6-12 months before launch.** This is the critical step. You need to search for pain signals that existed BEFORE the product existed. Use the Wayback Machine to verify that your sources existed at that time. Search Reddit, HN, G2, and other sources using keywords related to the problem the product solves — NOT the product name.

3. **Collect signals as if you do not know the outcome.** This is where bias creeps in. If you know Plausible succeeded, you will unconsciously search harder for ‘Google Analytics frustration’ signals and interpret ambiguous signals as strong. To mitigate this: have someone else collect signals who does not know which cases are successes and which are failures. If you must do it yourself, collect signals for all 10 cases before tagging or clustering ANY of them.

4. **Run stages 2-6 on the collected signals.** Tag, cluster, enrich, score, and model. Produce a ranked list of the 10 cases as if they were 10 candidate opportunities you discovered through the pipeline.

5. **Compare the ranking to actual outcomes.** This is the measurement.

## **Backtest Metrics**

| Metric | How to Compute | Pass Threshold | What Failure Means |
| :---- | :---- | :---- | :---- |
| Separation | Average score of the 5 successes minus average score of the 5 failures | \>1.0 point difference | The pipeline cannot distinguish winners from losers. The scoring criteria or weights are wrong. |
| Top-3 precision | Of the 3 highest-scored cases, how many are actual successes? | ≥2 out of 3 | The pipeline ranks failures above successes. Either scoring is miscalibrated or the signal collection missed critical evidence. |
| Bottom-3 precision | Of the 3 lowest-scored cases, how many are actual failures? | ≥2 out of 3 | The pipeline does not reliably filter bad ideas. The kill criteria are too lenient. |
| Kill criterion sensitivity | For each failure: did at least one kill criterion fire? | 4 out of 5 failures hit ≥1 kill criterion | The kill criteria are missing the patterns that cause real-world failure. |
| Signal presence | For each success: were pain signals findable before launch? | 4 out of 5 successes had ≥10 pre-launch signals | Either the pipeline sources don’t cover where pain was expressed, or the product was a category-creator (valid limitation of the pipeline). |

**If the backtest passes all five metrics,** the pipeline is validated for painkiller opportunities (problems people already know they have). Proceed to forward testing with confidence.

**If the backtest fails,** diagnose which stage broke. Did signals exist but tagging missed them? Were clusters incoherent? Was scoring miscalibrated? Was the enrichment data wrong? Fix the failing stage, re-run the backtest, and repeat until it passes.

## **Backtest Limitations**

The backtest has inherent limitations you must acknowledge:

* **Survivorship bias in case selection.** You can only backtest products you know about. The most interesting failure cases — products that died so quietly nobody wrote a postmortem — are invisible to you.

* **Hindsight contamination.** Even with strict protocols, your knowledge of outcomes will influence signal collection and interpretation. The backtest is always somewhat optimistic about pipeline performance.

* **Category-creators are out of scope.** The pipeline is designed for painkiller opportunities. Products like the iPhone, which created demand that did not previously exist, will not be surfaced. This is a feature, not a bug — category creation requires resources a solo founder does not have.

* **Market timing is invisible in hindsight.** Plausible benefited from GDPR enforcement rulings in 2022 that nobody could have predicted in 2019\. The pipeline cannot score future regulatory tailwinds. It can only score what is visible now.

# **Forward Test Protocol**

The forward test is the ultimate evaluation: run the pipeline blind on a fresh domain, commit to the top-ranked opportunity, and see if it works. This is expensive (months of your time) and irreversible (you cannot un-build a product). So the forward test has strict entry criteria.

## **Entry Criteria**

Do not run a forward test until:

* **The backtest passes** with separation \>1.0 and top-3 precision ≥2/3.

* **Stage-level metrics are clean** — no stage has a ‘bad’ rating on any metric.

* **The top-ranked opportunity scores \>3.5** with \>50% high-confidence scores.

* **The conservative scenario reaches target MRR** within 24 months.

* **You have personally validated Stage 4 validation** — at least Rung 2 (solution interviews) completed with real humans.

## **Forward Test Metrics**

Once you commit and build, track these metrics to evaluate whether the pipeline’s prediction was correct:

| Metric | Check At | Pipeline Was Right If... | Pipeline Was Wrong If... |
| :---- | :---- | :---- | :---- |
| Problem confirmation | Week 1-4 (customer interviews) | 80%+ of interviewees confirm the pain exists and describe it consistently with the cluster signals | Fewer than 50% recognize the problem, or they describe a fundamentally different pain |
| Willingness to pay | Week 4-8 (landing page \+ pricing test) | Landing page converts \>3% of qualified visitors. At least 3 people give you money before the product is finished. | Nobody converts. People say ‘cool but I wouldn’t pay for it.’ |
| Build time accuracy | Week 6-10 (MVP shipped) | MVP shipped within 2x the estimated build time | MVP took \>3x estimated time, indicating solo feasibility was overscored |
| First 10 customers | Day 90 | 10 paying customers acquired | Fewer than 3 paying customers despite outreach to 100+ prospects |
| $1k MRR | Month 4-6 | Reached $1k MRR | Still below $500 MRR with no clear growth trend |
| Distribution channel validation | Month 3-6 | At least one acquisition channel produces ≥3 customers/month repeatably | All customers came from personal network; no scalable channel found |
| Churn reality vs model | Month 6+ | Monthly churn within 2x of the modeled estimate | Churn is \>3x the modeled estimate, meaning the model was fundamentally wrong about retention |
| Target MRR | Month 12-18 | Reached target MRR or is on a trajectory that projects reaching it within 24 months | Growth has plateaued well below target with no clear path to reach it |

## **Interpreting Forward Test Results**

The forward test does not just validate the specific opportunity — it validates the pipeline itself. After the forward test, regardless of outcome, do a retrospective:

* **If the opportunity succeeded:** Which pipeline signals were most predictive? Which scores were most accurate? Which enrichment data points turned out to matter most? Increase the weight of these in future runs.

* **If the opportunity failed at problem confirmation:** The pipeline’s signal collection or clustering was wrong. The signals looked like demand but were not. Audit: were the signals from real users or from marketers? Were the clusters coherent? Was source diversity high enough?

* **If the opportunity failed at willingness to pay:** The pipeline’s enrichment or scoring was wrong. The problem is real but the business model does not work. Audit: was competitor pricing data accurate? Was the buyer persona correctly identified? Was the distribution score inflated?

* **If the opportunity failed at distribution:** The pipeline’s distribution scoring was wrong. This is the most common failure mode for technical founders. Audit: did you have evidence of a scalable channel, or did you assume you would figure it out? The distribution criterion needs to be weighted higher or evaluated more rigorously.

* **If the opportunity failed at churn:** The pipeline’s enrichment of buyer persona and product-market fit was wrong. The product solves the problem but users do not stick. Audit: was the pain intense enough (pain\_intensity ≥4) to justify ongoing subscription? Or was this a one-time-use problem disguised as a recurring need?

# **The Feedback Loop**

The pipeline is not a one-shot tool. It is a system that improves with every use. Every run produces data that calibrates the next run.

## **What to Record After Every Run**

* **Stage-level metrics** for this run (coverage, tag accuracy, cluster coherence, etc.). Store them. Compare across runs. Are they improving?

* **Which sources produced the highest-quality signals?** Rank your sources by signal-to-noise ratio. Drop low-quality sources. Add new ones that were missing.

* **Which query patterns produced the most signals?** Some queries return noise. Some return gold. Track which ones work and refine them.

* **Which clusters were ultimately pursued, and what happened?** This is the most valuable data. Even if you only validated one cluster and it failed, record why. ‘Cluster X scored 3.8 but failed at willingness-to-pay because the buyer persona was wrong’ is a calibration data point for every future run.

* **Which scores were most wrong?** If distribution scored 4 but turned out to be 1 in reality, your distribution scoring method needs to change. Track the delta between predicted and actual for every criterion you eventually test.

## **Calibration Over Time**

After 3-5 pipeline runs with forward test feedback, you will have enough data to:

* **Adjust criterion weights.** If distribution is consistently the criterion where predicted and actual diverge most, increase its weight. If defensibility never matters at the $10k/month scale, decrease its weight or remove it.

* **Refine scoring anchors.** Replace the generic ‘score \= 5 when...’ descriptions with examples from your own runs. ‘Score \= 5 looks like Cluster X from Run 3, which had 47 signals, 5 source diversity, and 12 workarounds.’ Real anchors produce better calibration than abstract descriptions.

* **Identify your personal biases.** Every founder has predictable blind spots. Maybe you consistently overscore solo feasibility (because you can build anything) and underscore distribution (because you hate marketing). The feedback data will reveal this pattern. Correct for it.

* **Build a case library.** Every cluster you evaluated, whether you pursued it or not, becomes a reference case for future runs. After 5 runs with 10 clusters each, you have 50 scored examples. This library is more valuable than any framework — it is your calibrated judgment, externalized.

# **The Meta-Metric**

There is one metric that measures the pipeline’s overall value:

**Time-to-revenue relative to random selection.**

If a founder picks an idea randomly (which is what most do — they build whatever sounds cool), the median time to $10k MRR for solo founders is somewhere between ‘never’ and ‘3 years.’ If the pipeline consistently gets founders to $10k MRR in 12-18 months, it is working. If it does not beat random selection, the entire methodology is waste and should be abandoned.

You will not know this meta-metric from one run. You will know it after 3-5 runs, either your own or by sharing the pipeline with other founders and tracking their outcomes. This is the long game. The pipeline is a hypothesis about how to systematically find viable businesses. The evaluation framework is how you test that hypothesis.

*Measure every stage. Backtest before trusting. Forward test before committing. Calibrate after every run.*
