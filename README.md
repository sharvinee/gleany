# Gleany

A harvest-decision agent for US specialty crop growers. When market prices fall
below the cost of harvesting, the agent detects the crossover, tells the grower
whether to harvest, partial-pick, or abandon, and on the abandon branch routes
the standing crop to a gleaning organisation, food bank, or processor.

Demo crop: California strawberries, Santa Maria district.

## The problem

US farming generated 16.9 million tons of surplus produce in 2024. Over 80% was
left in the field and never harvested. Only 1.6% was donated for hunger relief.
The decision to abandon is made in days, under pressure, with poor market
visibility, and there is no tool for it.

## The thesis

A Santa Clara University study ran 123 in-field surveys across 20 hand-harvested
crops. Measured edible loss exceeded growers' own estimates by a median of 157%
— roughly two and a half times what growers believed. The grower's intuition is
not merely imprecise, it is wrong in a consistent direction. That is the case
for computing the floor rather than feeling it.

## How it works

```
Live USDA AMS prices  →  Wage floor selection  →  Cost floor arithmetic
        ↓                                              ↓
  Confidence gate  ←  net per flat  ←  Decision bands (GO / PARTIAL / ABANDON)
        ↓                                              ↓
     SILENT                                    Decision record on disk
                                                     ↓
                                          If ABANDON: recovery agent
                                                     ↓
                                          Human approval gate (structural)
                                                     ↓
                                          Composio Gmail send
```

**The agent gathers, the code decides.** The model extracts, summarises, and
drafts. The cost floor is arithmetic and the decision bands are thresholds —
both are plain Python. This makes the output auditable and stops the model from
producing a plausible wrong number.

## Key design choices

- **Three wage floors, not one.** California's OEWS-derived AEWR ($16.45), H-2A
  housing-adjusted rate ($13.45), and state minimum wage ($16.90). The employer
  pays the highest applicable. Using the housing-adjusted rate underprices labour
  by $3.45/hr and produces a false GO.

- **Filter inside the tool.** The AMS payload is 53 rows. The tool returns only
  the 2 matching strawberry/Santa Maria rows. The verbose payload never reaches
  the model.

- **data_age_hours from published date.** Computed from the report's own
  timestamp, not fetch time. Stale inputs gate confidence down.

- **Two independent sources required.** Fewer than two price sources → SILENT.
  A demo that correctly stays silent is worth more than one that always fires.

- **The abandon branch requires human approval, enforced structurally.** The
  agent does not hold the send tool. It returns the drafted advisory, prints it,
  and a typed confirmation triggers the send from outside the agent loop.

- **Every placeholder is marked.** Grower-side costs (pick rate, cooling,
  commission, freight) are demo placeholders. They are marked ⚠️ in the output
  and the decision record. Market prices are real, from live USDA endpoints.

## Stack

| Layer | Tool |
|---|---|
| Model | OpenAI GPT-4o |
| Agent harness | LangChain `create_agent` |
| Market data | USDA AMS MARS API (live, basic auth) |
| Delivery | Composio Gmail (after human approval) |
| Language | Python, `uv` for deps |

## Running

```bash
# Set up .env with MARS_API_KEY, OPENAI_API_KEY, COMPOSIO_API_KEY

# Deterministic pipeline only (no agent)
uv run python run_decision.py

# Agent-driven (calls tools, drafts advisory)
uv run python run_agent.py

# Full demo: GO + ABANDON + recovery routing + approval gate
uv run python run_full_demo.py

# Tests
uv run pytest
```

## Demo script

1. **GO scenario**: Live Santa Maria strawberry prices ($8.00/flat mostly) vs
   cost floor ($7.84/flat). Net $0.16/flat — barely positive. Pick as planned.
2. **ABANDON scenario**: Same prices, higher costs ($11.98/flat). Net -$3.98/flat.
   The price doesn't even cover harvest labour. Agent says skip the pick.
3. **Recovery routing**: Second agent finds food banks (Santa Barbara, San Luis
   Obispo, Ventura) and processors (California Strawberry Commission network).
   Drafts advisory with timeline: hours, not days.
4. **Human approval gate**: Program prints the draft. Type `yes` to send via
   Composio Gmail. The agent cannot send on its own.
5. **Open `decision_record.md`**: Every number traced to a source. Every
   placeholder marked.

## Honesty

- Market prices are **real**, from live USDA AMS MARS API calls.
- Grower-side costs are **placeholders** — demo values, not from a real grower.
- This is not a backtest. The claim is that the decision is currently made blind
  and this makes it legible.
- Gleaning coverage is regional, not national. California is strong.
