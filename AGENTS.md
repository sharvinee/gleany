# AGENTS.md

## What this is

A harvest-decision agent for US specialty crop growers. When market prices fall
below the cost of harvesting, the agent detects the crossover, tells the grower
whether to harvest, partial-pick, or abandon, and on the abandon branch routes the
standing crop to a gleaning organisation, food bank, or processor.

Demo crop is California strawberries, Santa Maria district.

Built as a hackathon demo. Two hour build window. Full spec in `docs/SPEC.md`.
Read it before writing code.

## Stack, and what is settled

- **OpenAI** — the model. Required, non-negotiable.
- **Octen** — real-time search. The unstructured layer.
- **Composio** — delivery and outbound actions. Handles auth.
- **LangChain `create_agent`** — the agent harness. Chosen over `deepagents`
  because this workflow is a fixed pipeline with one branch, not open-ended
  research. There is nothing for a planner to plan.
- **Zendesk** — deliberately excluded. There is no support-ticket surface here.
  Do not add it.

`deepagents` was evaluated and dropped. Of its five headline features, only
subagent delegation was arguably useful here, and the large-payload problem it
would solve is already solved by filtering inside the AMS tool. Do not add it
back without a reason.

## Conventions

- Python. `uv` for dependency management.
- All secrets via environment variables. Never inline a key, never commit one.
- Every retrieved claim carries its source sentence through to the decision
  record. If a signal cannot be traced to a source, it does not enter the rule.
- Money in USD, per flat of 8 one-pound containers, which is the standard AMS
  fresh strawberry trade unit. Do not silently switch units.
- AMS report slugs are hardcoded config, never discovered at runtime.
  `SLUG_SHIPPING_POINT = 2390` (FR_FV110) and `SLUG_NATIONAL_FOB = 3130`.
- Every signal carries `data_age_hours`, computed from the report's own published
  date and not from fetch time. Stale inputs gate confidence down.
- Write decision records to disk as files, not to stdout. Plain `pathlib`, no
  virtual filesystem layer needed.

## Pitfalls specific to this domain

**California has three candidate wage floors, not one.** Under the October 2025
IFR the OEWS-derived entry-level rate is $16.45/hr, a $3.00 housing adjustment can
apply to H-2A workers giving $13.45, and California's 2026 minimum wage is
$16.90. The employer pays the highest applicable rate, so the housing-adjusted
number is not the floor. Pulling the adjusted figure naively underprices labour by
about $3.45/hr and produces a false GO. Verify the binding rate against the
current DOL table at build time and record which of the three bound.

**Strawberries are picked repeatedly, not once.** Fruit ripens over months and is
picked every two to three days. The decision is never all-or-nothing for a season.
It is per-pick. Model `picks_remaining`, not a single harvest event.

**The recovery window is hours, not days.** Strawberries must be cooled soon after
picking and have a shelf life measured in days. A gleaning match that arrives two
days late is worthless. On the abandon branch, also offer the processor channel
(freezing, puree, juice), which pays less but absorbs volume and tolerates fruit
a food bank cannot move fast enough.

**Report names lie about coverage.** Slug 2390 is called Fresno Shipping Point
Fruit Prices, but Fresno is the reporting office, not the district. That single
report carries Santa Maria and Salinas-Watsonville strawberries plus every other
California fruit commodity the office covers. Filter on commodity and district
fields, never on report name. Filter inside the tool because the payload is
large, and confirm the JSON field names against a live response rather than
against the printed PDF.

**Do not invent market numbers.** Any figure not returned by a live API call is a
placeholder and must be marked as such in the code and in the output. This demo
gets shown to people who know these markets.

**Deterministic work stays out of the model.** The cost floor is arithmetic and
the decision bands are thresholds. Both are plain Python called from tools. The
model extracts, summarises, and drafts. It does not compute the answer.

**The abandon branch requires human approval, enforced structurally.** Do not
give the agent the `send_advisory` tool on the abandon path. Have it return the
drafted advisory, print it to the terminal, and require an explicit typed
confirmation before the send function is called from outside the agent loop. A
hard gate outside the model is more defensible than an interrupt the model
mediates, and it is faster to build.

## Out of scope

Planting-time advice. Yield prediction. Anything that requires training a model.
Anything requiring a grower account system or persistent user database.
