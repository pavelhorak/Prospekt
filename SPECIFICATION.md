
**DATA PROCESSING**  
**SPECIFICATION**

How raw internet signals become ranked business opportunities

Companion to: Business Opportunity Research Playbook

**Core principle: No data is ever deleted.**

Every signal is tagged, layered, and referenced — never discarded.

# **Data Philosophy**

Before describing the processing pipeline, three principles that govern every step:

**1\. Nothing is deleted.** Every raw signal collected from any source is preserved permanently. Signals that seem irrelevant today may become relevant when context changes. A complaint about dental scheduling software that you dismissed in week 1 might become your best opportunity after you discover in week 3 that the dental software market has no good solo-founder-accessible competitor.

**2\. Duplicates are evidence, not noise.** When fifteen people on three different platforms describe the same frustration in different words, that is not fifteen duplicates to deduplicate — it is fifteen independent confirmations that the problem is real, widespread, and unsolved. The count matters. The diversity of sources matters. The different phrasings reveal different facets of the same pain. Every signal that maps to a cluster increases that cluster’s weight.

**3\. Processing means adding layers, not removing data.** Each processing stage adds metadata, tags, scores, and connections on top of the raw signals. The raw signal is never modified. You can always trace a final business opportunity recommendation back to the exact Reddit post, G2 review, or Upwork job that contributed to it.

# **Pipeline Overview**

The pipeline has six stages. Each stage takes input, adds a layer, and produces output. All data flows forward; nothing is discarded at any stage.

| Stage | Name | Input | What It Adds | Output |
| :---- | :---- | :---- | :---- | :---- |
| 1 | Ingest | Raw internet content | Normalized schema, source metadata | Signal records in uniform format |
| 2 | Tag | Normalized signals | Pain type, intensity markers, industry, buyer persona | Tagged signals |
| 3 | Cluster | Tagged signals | Cluster membership, frequency count, source diversity score | Problem clusters (signals preserved inside each cluster) |
| 4 | Enrich | Problem clusters | Competitor data, market size signals, pricing benchmarks, trend data | Enriched clusters |
| 5 | Score | Enriched clusters | 7-criterion scores with evidence links | Scored and ranked opportunities |
| 6 | Model | Top scored opportunities | Unit economics, scenario projections, risk factors | Investment-ready opportunity briefs |

# **Stage 1: Ingest**

**Purpose:** Collect raw signals from all sources and normalize them into a uniform record format so they can be compared regardless of where they came from.

**Core rule: preserve everything.** The original text, the URL, the engagement metrics, the author information, the date, the context. Store the raw data exactly as it was found. The normalized version is a copy with added structure, not a replacement.

## **Signal Record Schema**

Every signal, regardless of source, is stored with these fields:

| Field | Type | Description | Example |
| :---- | :---- | :---- | :---- |
| signal\_id | UUID | Unique identifier, auto-generated | a1b2c3d4-... |
| raw\_text | Text (unlimited) | The exact original text, unmodified. For reviews: the full review. For posts: the full post body. For jobs: the full job description. | "We spend 3 hours every Friday manually compiling engineering metrics from Jira and GitHub into a Google Sheet that nobody reads..." |
| source\_platform | Enum | Where it came from | reddit, hackernews, g2, upwork, linkedin\_jobs, google\_trends, facebook\_group, capterra, etc. |
| source\_url | URL | Direct link to the original content. Must be clickable and lead to the exact signal. | https://reddit.com/r/ExperiencedDevs/comments/... |
| source\_context | Text | The surrounding context: subreddit name, review category, job board, group name, product being reviewed | r/ExperiencedDevs, G2 review of LinearB, Upwork Web Development category |
| author\_info | Text (optional) | Any available info about who wrote it: job title, company size, industry, Reddit flair, LinkedIn title | "Senior Engineering Manager at a Series B startup, 40 engineers" |
| engagement | Object | Platform-specific metrics stored as key-value pairs | {upvotes: 340, comments: 89} or {rating: 1, helpful\_votes: 23} or {budget: '$5000', proposals: 42} |
| date\_posted | Date | When the original content was created | 2026-03-15 |
| date\_collected | Date | When you scraped/found it | 2026-04-13 |
| collection\_query | Text | The exact search query or browse path that led you to this signal | Reddit search: 'frustrated with' in r/ExperiencedDevs, sorted by top, past year |

**Why this matters:** Six months from now, you might revisit a cluster you initially deprioritized. If the raw text is gone, you have to re-scrape and hope the content still exists. If the source URL is broken, you lose the evidence chain. If the collection query is missing, you cannot reproduce or expand the search. Store everything.

## **Source-Specific Ingestion Notes**

Different sources produce different shapes of data. Here is how to handle each:

* **Reddit/HN/Twitter posts:** Store the post body AND the top 10-20 comments. Comments often contain the strongest signals — the post might be a question, but the answer describing a painful workaround is the real signal.

* **G2/Capterra reviews:** Store the full review, the star rating, the ‘Pros’ AND ‘Cons’ sections separately, the reviewer’s role/company size if shown, and which product is being reviewed. The product being reviewed is critical context.

* **Upwork/Fiverr jobs:** Store the full job description, the budget/price range, the number of proposals (competition indicator), and the client’s industry if visible. The budget is a direct willingness-to-pay signal.

* **Job postings:** Store the full description, the job title, the company name and size, and the location. The job title tells you who has the pain. The description tells you what the pain is. The company size tells you the market segment.

* **Google Trends:** This is not text but numerical data. Store the keyword, the interest-over-time data as a time series, and the ‘related queries’ list. The slope of the trend line is more important than the absolute value.

* **Facebook/Telegram groups:** Store the post text, the number of reactions/comments, and the group name. Group name is critical — it tells you the industry and buyer persona. Also note if the post author is a group admin (they often have influence and could become a distribution channel).

* **Competitor pricing pages:** Store the full pricing page as a screenshot AND as structured data (tiers, prices, feature lists). Date-stamp it. You will compare it with future snapshots to detect pricing changes.

# **Stage 2: Tag**

**Purpose:** Add structured metadata to every signal so it can be filtered, compared, and clustered. This is where raw text becomes analyzable data.

**Core rule:** Tagging is additive. The raw signal is never modified. Tags are stored alongside it.

## **Tag Categories**

Every signal gets tagged on these dimensions:

| Tag Dimension | Possible Values | How to Assign | Why It Matters |
| :---- | :---- | :---- | :---- |
| pain\_type | complaint, feature\_request, workaround, wish, paying\_for\_bad, question, switching, price\_complaint, manual\_process, hiring\_signal, trend\_data, competitive\_gap | Read the signal. What is the person doing? Complaining? Describing a workaround they built? Asking if a tool exists? Describing money they spend? | Different pain types have different conversion rates to business opportunities. Workarounds and paying-for-bad are the strongest. Questions and wishes are the weakest. |
| pain\_intensity | 1-5 scale | 1 \= mild annoyance. 2 \= recurring frustration. 3 \= significant time waste (hours/week). 4 \= costs real money or causes failures. 5 \= existential (compliance risk, job loss, business failure). | Intensity determines willingness to pay. Level 1-2 pain produces free-tier users. Level 4-5 pain produces paying customers who never churn. |
| industry | healthcare, legal, construction, real\_estate, agriculture, education, fitness, restaurant, logistics, accounting, ecommerce, freelance, manufacturing, insurance, software\_development, devops, engineering\_management, \[open list\] | Infer from context. The subreddit, the reviewer’s role, the job posting industry, the Facebook group name. | Clusters the signal into market segments. A pain that appears across multiple industries is bigger than one that’s industry-specific. |
| buyer\_persona | individual\_developer, team\_lead, engineering\_manager, vp\_director, cto, small\_business\_owner, solo\_practitioner, franchise\_operator, freelancer, operations\_manager, \[open list\] | Infer from author info, context, and who would buy a solution. The person complaining is not always the buyer. | Determines pricing ceiling, sales model, and distribution channel. SMB owners buy self-serve. VPs need sales calls. |
| company\_size | solo, 2-10, 11-50, 51-200, 201-1000, 1000+, unknown | Infer from context. Reddit flair, LinkedIn company, review metadata. | Determines TAM and product complexity. Solo/small \= simple product, low price, high volume. Enterprise \= complex, high price, long sales cycle. |
| geography | US, EU, UK, CEE, DACH, India, LatAm, SEA, Africa, global, unknown | Infer from language, platform, context, author info. | Affects pricing, compliance needs, competition landscape, and your distribution advantage. |
| has\_workaround | yes/no \+ description | Does the signal describe a manual workaround, script, spreadsheet, or Zapier automation? | Workarounds are the single strongest validation signal. Someone invested time to solve this without a proper tool. |
| has\_spend | yes/no \+ amount if known | Does the signal mention money spent on an existing solution, or budget for a custom build? | Direct evidence of willingness to pay. The mentioned amount is your pricing benchmark. |
| existing\_solution\_mentioned | tool name(s) if any | Does the signal reference a specific tool they use, tried, or switched from? | Maps the competitive landscape from the customer’s perspective. Which tools are being complained about? Which are being left? |
| date\_relevance | current, recent (\< 6 months), older (6-24 months), historical (2+ years) | How recently was this signal posted? | Recent signals are more actionable. But old signals describing the same pain as new signals \= durable problem. |

## **Tagging Methods**

For manual research (which is what you will do initially), you tag signals as you collect them. This is why the Signal Tracker spreadsheet has columns for workaround, paying-for-bad, and multi-source — those are tags.

For automated research (if you build the tool), tagging is done by an LLM. The prompt is: **“Given this raw signal, assign values for each of these tag dimensions. For each tag, quote the exact phrase in the signal that justifies the tag. If a tag cannot be determined, mark it as unknown.”** The justification quotes are critical — they let you audit the LLM’s judgment.

**Important:** Some signals will have multiple valid tags. A single Reddit post might describe a workaround (pain\_type: workaround), mention money spent on a bad tool (has\_spend: yes), and reference a specific competitor (existing\_solution\_mentioned: Jira). All of these tags apply simultaneously. Signals are not forced into single categories.

# **Stage 3: Cluster**

**Purpose:** Group signals that describe the same underlying problem into clusters. Critically, the signals remain inside the cluster — clustering is an organizational layer on top of the data, not a compression step.

**What “same underlying problem” means:** “PR reviews take too long,” “senior devs are overloaded with code reviews,” “no visibility into review bottlenecks,” and “our review cycle time is killing velocity” are all the same underlying problem: code review process is broken and unobservable. They are different manifestations of the same pain. They cluster together.

## **Cluster Schema**

Each cluster is a container with metadata computed from its member signals:

| Field | How Computed | What It Tells You |
| :---- | :---- | :---- |
| cluster\_id | Auto-generated | Unique identifier |
| cluster\_label | Human-written or LLM-generated from the 5 most representative signals | One-line description of the underlying problem: “Engineering teams lack visibility into code review bottlenecks” |
| cluster\_summary | Human-written or LLM-generated | 2-3 sentence description of the pain, who has it, and what they currently do about it |
| signal\_count | Count of all signals in the cluster | Raw volume of evidence. Higher \= more widespread pain. A cluster with 3 signals is speculative. A cluster with 50 is validated. |
| source\_diversity | Count of unique source\_platform values across member signals | If signals come from Reddit AND G2 AND Upwork AND LinkedIn jobs, the pain is real and cross-validated. If all 50 signals come from one Reddit thread, it might be an echo chamber. |
| industry\_spread | Count of unique industry tags across member signals | Pain appearing in healthcare AND construction AND accounting is a horizontal opportunity. Pain only in software development is vertical. |
| intensity\_distribution | Histogram of pain\_intensity values across members | A cluster where most signals are intensity 4-5 is more viable than one where most are intensity 1-2. Report the distribution, not just the average. |
| workaround\_count | Count of signals where has\_workaround \= yes | How many people built hacks to solve this? Each workaround is a feature spec. |
| spend\_evidence\_count | Count of signals where has\_spend \= yes | How many people mention spending money? Total mentioned spend amount if available. |
| temporal\_trend | Are signals increasing, stable, or decreasing over time? Based on date\_posted distribution. | Increasing \= growing market. Stable \= durable problem. Decreasing \= market might be solved or shrinking. |
| competitor\_mentions | Aggregated list of existing\_solution\_mentioned across all signals, with frequency count | Which tools are people using/leaving? The most-mentioned competitor is your primary positioning target. |
| all\_signal\_ids | Array of signal\_ids | The complete list of every signal that contributes to this cluster. Always preserved. Always traceable. |

## **How to Cluster**

**Manual method (for 50-200 signals):** Read each signal. Write the underlying problem it describes on a sticky note (physical or digital). Group sticky notes that describe the same problem. Name each group. This takes 2-4 hours for 200 signals and produces 15-40 clusters. It is imprecise but fast and builds your intuition for which problems are real.

**Semi-automated method (for 200-2000 signals):** Use an LLM. Prompt: “Read these 20 signals. Group them by the underlying problem they describe. For each group, write a one-line label. A signal can belong to multiple groups if it describes multiple problems. Do not discard any signal.” Process signals in batches of 20\. Then merge the group labels across batches. This takes 1-2 hours and produces cleaner clusters.

**Automated method (for 2000+ signals):** Generate text embeddings for each signal. Run HDBSCAN clustering on the embeddings with min\_cluster\_size=3. Use LLM to label each cluster from its 5 most central signals (closest to centroid). Post-process: merge clusters with centroid cosine similarity \> 0.85. This runs in minutes but requires engineering setup.

## **Critical: Handling Cross-Cluster Signals**

A single signal can belong to multiple clusters. A Reddit post saying “We waste 5 hours a week compiling engineering metrics from Jira into a spreadsheet for leadership” touches at least three clusters: engineering metrics tooling, spreadsheet-to-SaaS opportunity, and leadership reporting. The signal gets linked to all three clusters. Its contribution is counted in each. This is not double-counting — it is recognizing that a single pain point can spawn multiple business opportunities.

## **The Frequency Principle**

This is the most important concept in the entire pipeline:

**A cluster’s signal count is not a deduplication target. It is a demand indicator.** Fifteen people saying the same thing in different words is not redundancy — it is fifteen independent confirmations of a market need. Each additional signal that maps to a cluster makes that cluster more valuable, not less. The processing pipeline is designed to amplify frequency, not suppress it.

This is why no data is ever deleted. A signal you initially categorized as “noise” might later match a cluster you discover from a completely different source. Keeping everything allows the clusters to grow organically as you collect more data over time.

# **Stage 4: Enrich**

**Purpose:** For each cluster, go beyond the collected signals and actively research the market landscape. The signals tell you a problem exists. Enrichment tells you whether a business can be built around it.

**This stage is fundamentally different from Stages 1-3.** Stages 1-3 are about listening to what people say. Stage 4 is about investigating what the market looks like. You are no longer collecting pain signals — you are collecting business intelligence.

## **Enrichment Data Per Cluster**

| Data Point | Where to Find It | What to Record | What It Tells You |
| :---- | :---- | :---- | :---- |
| Direct competitors | G2 category pages, Google search “best \[category\] tools 2026”, competitor\_mentions from cluster signals | For each competitor: name, URL, founded year, pricing tiers, estimated revenue (SimilarWeb traffic × industry conversion benchmarks), team size (LinkedIn), funding (Crunchbase) | How crowded is the market? Who dominates? Where are the gaps? |
| Competitor pricing | Competitor websites, Wayback Machine for historical comparison | Exact pricing tiers, per-seat vs flat vs usage-based, free tier availability, enterprise tier existence | Your pricing benchmark. If the leader charges $50/seat/month, you know the market bears that price. If they recently raised prices, demand is strong. |
| Competitor weaknesses | G2/Capterra 1-2 star reviews for each competitor, AlternativeTo comments | Top 5 most frequent complaints per competitor, clustered by theme | Your positioning. If everyone hates competitor X’s complexity, you build the simple version. If everyone hates the price, you build the cheap version. |
| Market size estimate | Job board counts for the buyer persona title, industry association membership numbers, LinkedIn Sales Navigator searches | How many potential customers exist? E.g., “45,000 engineering managers at companies with 50-500 employees in US+EU” | Is the market big enough for your target? At $100/mo, you need 100 customers for $10k MRR. Are there 100 reachable buyers? |
| Search demand | Google Trends (trend direction), Ahrefs/SEMrush (monthly search volume for category keywords), Google Keyword Planner | Monthly search volume for top 5-10 keywords, trend direction over 24 months | Are people actively looking for solutions? Rising search volume \= growing demand. High volume \= established market. Low but rising \= early opportunity. |
| Funding activity | Crunchbase search for the category, TechCrunch/tech press | Recent funding rounds in the space: who raised, how much, what they’re building | VC-funded competitors validate the market but will pursue enterprise. Your opportunity is the segment they ignore: small teams, lower price, simpler product. |
| Regulatory context | EUR-Lex, regulations.gov, industry regulatory bodies | Any current or upcoming regulations that affect this problem space | Regulations that mandate tooling create forced adoption. E.g., e-invoicing mandates mean every business MUST have compliant software. |
| Distribution channels | SaaS marketplaces, community directories, content/SEO analysis of competitors | What acquisition channels do competitors use? Which marketplaces list tools in this category? What keywords do they rank for? | Your go-to-market playbook. If competitors grow through content, you write content. If they grow through marketplaces, you list there. |

**All enrichment data is attached to the cluster, not stored separately.** When you look at a cluster, you see: the original signals that define the problem, plus the market data that determines whether it’s a viable business. The two layers together give you the full picture.

## **Enrichment Triggers**

You do not enrich all clusters. Enrichment is time-intensive (1-3 hours per cluster). Prioritize clusters based on their Stage 3 metrics:

* **Signal count \> 10** AND **source diversity \> 2** — enough evidence to justify research time

* **Workaround count \> 3** — people are building hacks, which means the pain is intense enough to act on

* **Spend evidence \> 0** — someone mentioned paying money, which means willingness-to-pay is proven

* **Intensity distribution skews toward 3-5** — the pain is severe, not just annoying

A cluster that meets none of these criteria stays in the database but does not advance to enrichment. It is not deleted. It waits. New signals collected later might elevate it.

# **Stage 5: Score**

**Purpose:** Convert the qualitative enrichment data into a quantitative comparison framework so you can rank opportunities against each other.

**The scoring happens at the cluster level, but the evidence comes from the signals and enrichment data.** Every score must point back to specific data: a specific set of signals, a specific competitor’s pricing page, a specific Google Trends chart, a specific review. Scores without evidence are opinions, not assessments.

## **Scoring Method**

Use the 7-criterion rubric from the playbook. For each criterion, the score is derived from specific data points:

| Criterion (Weight) | Score \= 5 When... | Score \= 1 When... | Primary Evidence Source |
| :---- | :---- | :---- | :---- |
| Market Demand (20%) | Google Trends slope \> 50% growth over 2 years. Signal count \> 30\. Source diversity \> 4\. Workaround count \> 10\. | Flat or declining trend. Signal count \< 5\. Single source. No workarounds. | Google Trends data, cluster signal\_count, source\_diversity, workaround\_count |
| Distribution (20%) | You have existing audience in this niche. Low-competition SEO keywords exist. SaaS marketplace channel available. Product spreads within organizations. | No audience. No obvious acquisition channel. High CAC. Buyer unreachable. | SEO keyword difficulty, marketplace availability, your own network analysis |
| Competition (15%) | No direct competitor, or all competitors have bad reviews and high prices. No well-funded player. Open-source exists but no SaaS. | Dominant player with \> $50M funding and strong reviews. Low pricing. High switching costs. | Enrichment competitor list, funding data, review analysis |
| Founder-Market Fit (15%) | You have direct experience with the problem. You can name 20 potential buyers. You could write 10 blog posts without research. | Complete outsider. No network. No credibility. No domain knowledge. | Self-assessment \+ network analysis |
| Solo Feasibility (15%) | CRUD app with 0-2 integrations. Standard tech stack. Low maintenance burden. No regulatory complexity. | Requires ML, real-time infra, complex data pipelines, regulatory approval, or hardware. | Technical assessment of minimum viable product |
| Revenue Path (10%) | Clear per-seat or per-usage pricing. \< 100 customers needed for $10k MRR. Expansion revenue possible. | Unclear monetization. \> 500 customers needed. No expansion path. | Enrichment pricing data, unit economics calculation |
| Defensibility (5%) | Usage generates proprietary data. High switching costs. Network effects. Brand moat. | Feature-only product. Easily cloned in a weekend. No lock-in. | Product architecture assessment |

## **Evidence Chain Requirement**

For each score on each criterion, you must record:

* **The score** (1-5)

* **The primary evidence** — the specific data point(s) that justify the score. This could be: a link to Google Trends, a count of signals, a competitor’s pricing page URL, a specific cluster metric.

* **The confidence level** — high (hard data, directly measured), medium (inferred from strong signals), low (best guess, insufficient data). If most criteria have low confidence, you need more enrichment data before making a decision.

* **Contradicting evidence** — any data that argues against the score you assigned. If the market demand scores 4 but there’s one well-funded competitor that just launched a similar feature, note it. Honest scoring means acknowledging what argues against you.

**Why this matters:** Scoring without evidence chains produces feel-good numbers that confirm your biases. Scoring with evidence chains produces defensible assessments that reveal what you actually know vs. what you’re guessing.

# **Stage 6: Model**

**Purpose:** For the top 2-3 scored clusters, build a quantitative business model that projects whether the opportunity can reach your target income within your timeline.

**This is where the pipeline shifts from “is this a real problem?” to “can I build a viable business around this problem?”**

## **Model Inputs (from Earlier Stages)**

| Input | Source Stage | How It Maps to the Model |
| :---- | :---- | :---- |
| Price point | Stage 4 (Enrichment: competitor pricing) | Your estimated ARPU. Usually 50-80% of the leading competitor’s comparable tier. |
| Market size | Stage 4 (Enrichment: market size estimate) | Total addressable customers. Your serviceable market is 10-30% of this (geographic, segment, and capability constraints). |
| Churn estimate | Stage 4 (Enrichment: competitor weakness \+ buyer persona) | Inferred from buyer type. SMB \= 5-8% monthly. Mid-market \= 3-5%. Enterprise \= 1-2%. Tool-of-record (accounting, CRM) \= lower. Nice-to-have \= higher. |
| Acquisition rate | Stage 5 (Score: distribution advantage) | How many customers per month can you realistically acquire? Content/SEO: 5-15/month after 6 months. Community: 3-8/month. Direct outreach: 2-5/month. Marketplace: varies. |
| Build time | Stage 5 (Score: solo feasibility) | Weeks to MVP. Affects when revenue starts. |
| Cost structure | Your parameters (country, infrastructure choices) | Monthly fixed costs. For you in Slovakia: €400-1,100/month. |

## **Three-Scenario Projection**

For each opportunity, model three scenarios. The formula for each month is:

**MRR(month) \= MRR(month-1) × (1 \- churn) \+ (new\_customers × ARPU)**

Project forward 24 months. The key outputs are:

* **Month to $10k MRR** — when you hit your target income. If the conservative case never reaches it within 24 months, the opportunity fails.

* **Month to profitability** — when MRR exceeds your monthly costs. This is your minimum runway requirement.

* **Steady-state MRR** — the equilibrium where new customers \= churned customers. This is your ceiling without changing the model.

| Scenario | ARPU | Monthly Churn | New Customers/Month | Use For |
| :---- | :---- | :---- | :---- | :---- |
| Conservative | Lowest competitor tier | 8% (high for SaaS) | 3/month (organic only, no paid) | Kill decision. If this case never reaches $10k MRR in 24 months, eliminate. |
| Base | Median competitor pricing | 5% | 8/month (content \+ community \+ outreach) | Planning. This is your operating assumption. Target: $10k MRR in 12-18 months. |
| Optimistic | Higher tier with expansion | 3% | 15/month (marketplace \+ content \+ word-of-mouth) | Ceiling. If even this only reaches $5k MRR, the market is too small. |

## **Risk Factors**

The model produces clean numbers. Reality is messy. For each opportunity, document:

* **Platform risk** — does the product depend on a single platform’s API? What happens if they change terms, raise prices, or build the feature themselves?

* **Competitive response** — if you launch and succeed, will the dominant competitor copy your differentiator? How long would that take?

* **Regulatory risk** — could regulation help (forced adoption) or hurt (compliance costs, market access restrictions)?

* **Technical risk** — is there any part of the product you’re unsure you can build? Any dependency on technology that might not work as expected?

* **Market timing risk** — is the market too early (you’ll have to educate buyers) or too late (incumbents are entrenched)?

* **Personal risk** — how long can you sustain this without income? What is your financial runway? When is your personal deadline?

# **Full Traceability: From Recommendation to Raw Signal**

The most important property of this pipeline is end-to-end traceability. At every stage, you can click backward through the chain:

**Final recommendation** (“Build a PR review analytics tool for 10-50 person engineering teams”)

→ **Modeled projections** (Base case: $10k MRR in 14 months at $150/team with 8% monthly growth)

→ **Scores with evidence** (Market Demand: 4/5 because Google Trends slope \+65%, signal count 47, source diversity 5\)

→ **Enrichment data** (Competitors: LinearB $50M funded, Swarmia growing; Pricing: $8-15/seat; Market: \~45,000 engineering managers at target company size)

→ **Cluster** (47 signals across Reddit, HackerNews, G2 reviews, LinkedIn, and Slack; 12 workarounds described; 8 mentions of paying for LinearB/Swarmia but finding them too complex)

→ **Individual signals** (Reddit post with 340 upvotes: “How do you know if your code review process is actually working?”; G2 review of LinearB: “Too complex for our 20-person team, we just needed basic cycle time data”; Upwork job: “Build me a GitHub PR analytics dashboard, budget $3,000”)

**This traceability is the difference between “I have a hunch” and “I have evidence.”** Every business decision you make — what to build, how to price it, how to position it, who to sell to — can be traced back to specific statements from real people on the internet who described their pain in their own words.

The data was never deleted. The clusters accumulated evidence over time. The scores are anchored to that evidence. And when someone asks you “Why this idea?” you can show them the entire chain, from recommendation to raw signal, in under five minutes.

*Nothing deleted. Everything layered. Every recommendation traceable to real human pain.*
