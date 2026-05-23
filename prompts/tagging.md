# Tagging prompt — Stage 2

## Task

Given the raw text of an internet signal (Reddit post, HN comment, G2 review,
Upwork job, job posting, etc.), assign structured tags across the dimensions
below. For EVERY tag, quote the exact phrase in the signal that justifies it.
If a dimension cannot be determined from the text, return `unknown` rather
than guessing.

## Tag dimensions

- `pain_type`: complaint | feature_request | workaround | wish | paying_for_bad
  | question | switching | price_complaint | manual_process | hiring_signal
  | trend_data | competitive_gap
- `pain_intensity`: 1 (mild annoyance) – 5 (existential/business-failure)
- `industry`: healthcare | legal | construction | real_estate | … | unknown
- `buyer_persona`: individual_developer | team_lead | engineering_manager
  | vp_director | cto | small_business_owner | solo_practitioner | freelancer
  | operations_manager | unknown
- `company_size`: solo | 2-10 | 11-50 | 51-200 | 201-1000 | 1000+ | unknown
- `geography`: US | EU | UK | CEE | DACH | India | LatAm | SEA | Africa
  | global | unknown
- `has_workaround`: { value: yes|no, description: "…" if yes else null }
- `has_spend`: { value: yes|no, amount: "$X" or null }
- `existing_solution_mentioned`: [tool names…] or []
- `date_relevance`: current | recent | older | historical

## Output format

Return one entry per input signal, in the order received, inside a
top-level `tagged:` list. Wrap the whole response in a single fenced
YAML block:

````yaml
tagged:
  - signal_id: sig_xxxxxxxxxxxx
    tags:
      pain_type:        {value: workaround,           quote: "we built a Google Sheet that…"}
      pain_intensity:   {value: 3,                    quote: "3 hours every Friday"}
      industry:         {value: software_development, quote: "engineering team"}
      buyer_persona:    {value: engineering_manager,  quote: "as a manager I…"}
      company_size:     {value: 51-200,               quote: "40 engineers"}
      geography:        {value: unknown,              quote: ""}
      has_workaround:   {value: "yes", description: "manual Google Sheet weekly export"}
      has_spend:        {value: "no",  amount: null}
      existing_solution_mentioned: [Jira, GitHub]
      date_relevance:   {value: current,              quote: ""}
  - signal_id: sig_yyyyyyyyyyyy
    tags:
      …
````

Use `{value: unknown, quote: ""}` for any dimension that cannot be
determined from the text. Do not invent quotes — every `quote` field
must be a verbatim substring of the signal's `raw_text`.

## Rules

- A signal may have multiple valid tags (e.g. workaround AND has_spend).
  Apply all of them.
- Never modify or paraphrase the original text in your quotes — exact substring.
- If the text is too short or too ambiguous to support any tag, return
  `pain_type: unknown` with `quote: ""` and stop.

## Examples

<!-- Agent populates this section over time with calibrated examples drawn
     from runs where workaround_precision / spend_precision misfired. The
     baseline prompt is deliberately example-light so the first run's
     auditor scores reveal which categories need anchoring. -->
