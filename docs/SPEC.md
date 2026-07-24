# Harvest Decision Agent — Build Spec

## 1. The problem

US specialty crop growers are squeezed from both ends. Prices are pushed down by
oversupply and by import competition moving into what used to be domestic-only
market windows. Harvest costs are pushed up by farm labour rates.

When the two lines cross, the crop is worth less than the cost of picking and
shipping it, and growers walk away from ripe, edible produce.

The scale is documented. In 2024 US farming generated 16.9 million tons of
surplus produce. More than 80% was left in the field and never harvested. Only
1.6% was donated for hunger relief. ReFED attributes this directly to low market
prices and high harvest costs making it uneconomic to pick everything grown.

That 1.6% is the gap this product targets. Gleaning already exists. What does not
exist is a mechanism that fires the match while the crop is still good.

The decision to abandon is made in days, under pressure, with poor market
visibility, and there is no tool for it.

## 2. Market context

Figures below are for framing the pitch. Verify before quoting on stage.

**California on-farm loss, measured not surveyed.** A Santa Clara University study
ran 123 in-field surveys across 20 hand-harvested crops on midsize to large
conventional farms in northern and central California. Average loss was 11,299 kg
per hectare, or 31.3% of marketed yield. Including walk-by fields, meaning fields
left entirely unharvested, the figure reaches 33.7%. Walk-by alone accounted for
2.4%. In plainer terms, roughly five tons per acre.

**Strawberries specifically lost 44%** in that study. Watermelon 57%, cabbage 52%,
kale 39%. Romaine hearts measured 113%, but that reflects outer-leaf trimming
practice rather than abandonment, so do not use it as a headline.

**The thesis number.** Measured edible loss exceeded growers' own estimates by a
median of 157%, roughly two and a half times what growers believed. The grower's
intuition is not merely imprecise, it is wrong in a consistent direction. That is
the case for computing the floor rather than feeling it.

**Wider framing.** US import share of fresh vegetable availability rose from
roughly 20% to 38% between 2007 and 2021. Mexico supplies about 69% of US fresh
vegetable imports by value. The US agricultural trade balance reversed around
2019. AFBF estimates more than $7B in 2025 losses across six representative
specialty crops. Specialty crop growers spend close to 40% of total cash expenses
on labour.

## 3. Worked example

California strawberries, Santa Maria district, spring through summer.

Chosen because the crop is hand-picked so labour dominates the cost floor, it is
picked repeatedly over months so the decision recurs, perishability makes timing
genuinely urgent, California's 2026 wage floor changed sharply and interestingly,
and the state has the densest gleaning and food-recovery network in the country.

**Block config for the demo:**

```
grower_id:        demo-ca-001
region:           Santa Maria, Santa Barbara County, CA
crop:             strawberry, fresh market
acres_standing:   48
picks_remaining:  9
pick_interval:    every 2 to 3 days
unit:             flat, 8 x 1 lb containers
```

**Cost floor inputs:**

| Input | Value | Source | Status |
|---|---|---|---|
| OEWS-derived AEWR, CA 2026 entry level | $16.45/hr | DOL IFR | real |
| H-2A adverse compensation adjustment | -$3.00/hr | DOL IFR | real |
| Adjusted H-2A entry rate | $13.45/hr | derived | real |
| California minimum wage 2026 | $16.90/hr | CA DIR | real |
| **Binding entry-level floor** | **$16.90/hr** | highest applicable | real, verify |
| Experienced level, unadjusted | $18.71/hr | DOL IFR | real, verify |
| Pick rate, flats per person-hour | TBD | grower input | placeholder |
| Piece rate per flat, if used | TBD | grower input | placeholder |
| Cooling and packing per flat | TBD | grower input | placeholder |
| Marketer or shipper commission | TBD | grower agreement | placeholder |
| Freight, Santa Maria to LA or east | TBD | lane quote | placeholder |

Note on the wage table: sources differ on whether the housing-adjusted rate or
the minimum wage binds for the experienced tier. Resolve against the live DOL
table before the demo and have the agent record which rate bound and why. This
ambiguity is a feature of the demo, not a bug, because it is exactly the kind of
error the tool exists to prevent.

**Market inputs:**

| Input | Source | Slug | Status |
|---|---|---|---|
| Shipping point price, strawberry, flat | USDA AMS MARS, FR_FV110 | 2390 | confirmed |
| Cross-check price | USDA AMS MARS, National FOB Review | 3130 | confirmed |
| Terminal price, LA / SF / Chicago / NY | USDA AMS MARS | TBD | live endpoint |
| Arrivals by origin | National Shipping Point Trends | TBD | live endpoint |

Slug 2390 is named Fresno Shipping Point Fruit Prices, but Fresno is the
reporting office, not the district. The report carries both Santa Maria and
Salinas-Watsonville strawberry sections, alongside every other California fruit
commodity that office covers. Filter on commodity and district, not on report
name. The payload is large, so filter inside the tool.

**Observed 2026 medium flat prices, 8 x 1 lb containers:**

| Date | District | Conventional | Organic |
|---|---|---|---|
| Mar 17 | Salinas-Watsonville | 6.00 to 8.00 | not quoted |
| May 12 | Santa Maria | mostly 14.00 to 16.00 | mostly 20.00 to 22.00 |
| Jul 13 | Salinas-Watsonville | 8.00 to 12.00 | mostly 16.00 to 18.00 |

The March report notes berries being diverted to freezer or processor and sales
booked open with price to be established later. The May report says the same.
USDA is already recording the behaviour the recovery branch automates. The
product is not proposing something growers do not do. It is making the call
earlier and with a number behind it.

## 4. Decision logic

Compute net return per flat:

```
net = expected_price
      - harvest_labour_per_flat
      - cooling_pack_per_flat
      - commission_per_flat
      - freight_per_flat

harvest_labour_per_flat = binding_wage / flats_per_person_hour
```

Where a crew is mixed between H-2A and domestic workers, compute the labour term
per group and blend by crew composition. Never average the candidate wage figures
directly. Always record which floor bound.

Three bands:

| Band | Condition | Action |
|---|---|---|
| GO | net positive | pick as planned, no alert |
| PARTIAL | net near zero AND import surge or buyer cancellation detected | advise first-grade-only pick, shorten the crew day, reassess next pick |
| ABANDON | net below zero by more than the labour term alone | advise skipping the pick, trigger recovery routing |

For strawberries, ABANDON usually means skipping a pick or ending the season
early rather than walking away from a whole field at once. Phrase advisories
accordingly.

Confidence gate: if fewer than two independent sources support the price signal,
stay in GO and record why. Gate down further when `data_age_hours` is high on the
structured inputs. A demo that correctly stays silent is worth more than one that
always fires.

## 5. Architecture

LangChain `create_agent`. One agent, a set of tools, deterministic logic in Python
around it.

`deepagents` was considered and rejected. This workflow is a fixed pipeline with
one branch. There is no plan to write, the decision record is a single file, and
the large AMS payload is filtered inside the tool so context isolation buys
nothing. The harness cost was not earning its keep in a two hour build.

**The agent** holds the block config in the system prompt, calls tools to gather
signals, and drafts the advisory text. It does not compute the decision.

**Deterministic Python, outside the model:**

- the wage floor selection
- the cost floor arithmetic
- the band thresholds
- the confidence gate

The agent gathers, the code decides. This is the single most important structural
choice in the build, because it makes the output auditable and stops the model
from producing a plausible wrong number.

**Market scanning** is a normal tool call, not a subagent. `get_ams_price` filters
by commodity and district inside the tool and returns a handful of rows, so the
verbose payload never reaches the model.

**Recovery routing** is a second `create_agent` instance, invoked only on the
abandon branch, with its own prompt and the Composio tools. Calling it a subagent
is fine in the pitch. In code it is just a function that builds a second agent.

**Tools:**

- `get_wage_floors(state, year, skill_level)` — returns all candidate rates and
  which one binds, with the reason
- `compute_cost_floor(block_config, wage_inputs)` — arithmetic, deterministic
- `get_ams_price(slug_id, commodity, district, date)` — USDA AMS MARS. Filters
  inside the tool and returns only matching rows. The full payload is large.
- `get_ams_movement(commodity, date_range)` — arrivals by origin
- `octen_search(query, freshness_window)` — real-time unstructured
- `send_advisory(channel, recipient, body)` — Composio

**Human-in-the-loop:** the agent never holds `send_advisory` on the abandon path.
It returns the drafted text, the program prints it, and a typed confirmation in
the terminal triggers the send from outside the agent loop. Structural rather
than prompted, which is both faster to build and stronger to demo.

**Output files:** write `block_config.json`, `signals.json`, `cost_floor.json`,
and `decision_record.md` to disk with `pathlib`. Open the decision record on
stage. It is the audit trail.

## 6. Data sources

**Structured, live:**

- USDA AMS Market News via the MARS API — shipping point prices, terminal prices,
  movement by origin. Base `https://marsapi.ams.usda.gov/services/v1.2`. HTTP
  basic auth with the key as username and a blank password. Retrieval is by
  report slug_id only, never by commodity. Slugs are already resolved: 2390
  primary, 3130 cross-check. Hardcode them. Do not discover at runtime, because
  discovery costs a call and a chunk of context on every run and can silently
  land on the wrong report.
- DOL AEWR tables at `flag.dol.gov/wage-data/adverse-effect-wage-rates`.
- California DIR for the state minimum wage.
- USDA NASS Quick Stats — acreage including unharvested area series.

**Known latency.** AMS publishes reports on a batch schedule and the API serves
published data only. There are no webhooks, so API freshness equals report
freshness. Expect one to two days of lag, three across a weekend. This does not
break the product because the decision plays out over days, but do not claim
real-time price detection. Claim catching the crossover a day or two after the
turn, which is still ahead of a grower acting on instinct.

**Real-time unstructured, via Octen:**

- Buyer and retailer order cancellations
- Competing district status, eg. Watsonville starting early, Oxnard winding down
- Mexican and border crossing volumes
- Grower association and marketer bulletins

The two tiers are not redundant. AMS gives the defensible number, Octen gives the
leading edge, and the gap between them is itself the earliest signal.

## 7. Two hour timebox

| Minutes | Work |
|---|---|
| 0–15 | `create_agent` hello world with a dummy tool, confirm the model string works |
| 15–35 | Block config, `get_wage_floors`, `compute_cost_floor`. Deterministic core first. |
| 35–65 | AMS tool against slug 2390, Octen tool, wire both into the agent |
| 65–85 | Decision bands, confidence gate, decision record to filesystem |
| 85–105 | Recovery agent and Composio delivery, plus the terminal approval gate |
| 105–120 | Demo run-through including the stay-silent case |

Do the MARS key registration before the clock starts. Slugs are already resolved. Cut
order if time runs short: recovery-broker first, then the second AMS endpoint,
then the interrupt. Never cut the decision record.

## 8. Demo script

1. Open with the number: 16.9 million tons of surplus on US farms, over 80% left
   in the field, 1.6% donated.
2. Show the block: 48 acres of Santa Maria strawberries, nine picks left.
3. Run. The agent plans, fans out, and reports: terminal price fell, arrivals up
   week over week, a buyer cancelled. Each signal timestamped with its age.
4. Cost floor computes. Show it choosing the binding wage floor from three
   candidates and explaining why the housing-adjusted rate does not apply.
5. Net is negative. Agent proposes ABANDON. **It pauses for approval.** Press yes.
6. Recovery agent finds a food bank with capacity inside the perishability
   window and drafts the offer. Type the confirmation, Composio sends it.
7. Open `decision_record.md`. Every number traced to a source sentence.
8. Re-run on a second block where the price holds. The agent stays silent.

## 9. Honesty rules for the pitch

- Be precise about what is real. Market prices come from live USDA endpoints and
  are real. The grower-side costs, pick rate, cooling, commission, and freight,
  are placeholders. Say that distinction out loud rather than lumping them
  together, and do not let a judge discover it.
- Do not claim accuracy. There is no backtest. The claim is that the decision is
  currently made blind and this makes it legible.
- Do not claim real-time. Claim one to two days behind the market and far ahead
  of the grower.
- Gleaning coverage is regional, not national. California is strong. Say so
  rather than implying blanket coverage.
- The $7B loss figure is AFBF's estimate of sector losses, not a figure this
  system produced or would recover.
