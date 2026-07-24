"""Recovery routing agent — second create_agent for the ABANDON branch.

Invoked only when decide() returns ABANDON. Has its own prompt and tools.
Finds a gleaning organisation, food bank, or processor that can absorb the
standing crop within the perishability window (hours, not days).

Per SPEC:
  - Also offer the processor channel (freezing, puree, juice) — pays less
    but absorbs volume and tolerates fruit a food bank can't move fast enough.
  - Strawberries must be cooled soon after picking. A gleaning match that
    arrives two days late is worthless.
  - Calling it a subagent is fine in the pitch. In code it is just a function
    that builds a second agent.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool

from .config import DEMO_BLOCK


# ---------------------------------------------------------------------------
# Recovery tools
# ---------------------------------------------------------------------------
@tool
def search_food_banks(region: str) -> str:
    """Search for food banks near a growing region that can accept fresh produce.

    For the California demo, this returns known food banks in the Central Coast
    and Central Valley region with their produce acceptance capacity.

    Args:
        region: The growing region, e.g. "Santa Maria, Santa Barbara County, CA"

    Returns:
        JSON string with food bank names, locations, contact info, and
        produce acceptance notes.
    """
    # In production this would hit a food bank directory API or Octen search.
    # For the demo, we return known California food banks that accept fresh produce.
    import json
    banks = [
        {
            "name": "Santa Barbara County Food Bank",
            "location": "Santa Barbara, CA",
            "distance_from_block": "~30 miles",
            "accepts_fresh_produce": True,
            "cold_storage": True,
            "response_time": "same day",
            "notes": "Active gleaning program. Can dispatch volunteer crews.",
        },
        {
            "name": "Food Share (Ventura County)",
            "location": "Oxnard, CA",
            "distance_from_block": "~60 miles",
            "accepts_fresh_produce": True,
            "cold_storage": True,
            "response_time": "same day or next morning",
            "notes": "Large capacity, serves 200k+ people monthly.",
        },
        {
            "name": "San Luis Obispo Food Bank",
            "location": "San Luis Obispo, CA",
            "distance_from_block": "~35 miles",
            "accepts_fresh_produce": True,
            "cold_storage": True,
            "response_time": "same day",
            "notes": "Partners with local gleaning org California Association of Food Banks.",
        },
    ]
    return json.dumps({"food_banks": banks, "region": region}, indent=2)


@tool
def search_processors(commodity: str, region: str) -> str:
    """Search for processors (freezing, puree, juice) near a growing region.

    Processors pay less than fresh market but absorb volume and tolerate fruit
    a food bank cannot move fast enough. This is the secondary recovery channel.

    Args:
        commodity: e.g. "Strawberries"
        region: e.g. "Santa Maria, Santa Barbara County, CA"

    Returns:
        JSON string with processor names, processing types, and contact info.
    """
    import json
    processors = [
        {
            "name": "California Strawberry Commission Processor Network",
            "type": "freezing, puree, juice",
            "location": "Watsonville, CA (regional hub)",
            "distance_from_block": "~120 miles",
            "accepts_field_run": True,
            "notes": "Network of 10+ processors. Tolerates bruised or odd-sized fruit. Pays $2-4/flat for processor-grade.",
        },
        {
            "name": "Los Gatos Tomato Products (frozen fruit division)",
            "type": "freezing, IQF",
            "location": "Santa Clara, CA",
            "distance_from_block": "~250 miles",
            "accepts_field_run": True,
            "notes": "Can arrange pickup. Requires minimum volume (typically 1 truckload).",
        },
    ]
    return json.dumps({"processors": processors, "commodity": commodity, "region": region}, indent=2)


# ---------------------------------------------------------------------------
# Recovery agent prompt
# ---------------------------------------------------------------------------
RECOVERY_PROMPT = f"""\
You are a crop recovery routing agent. You are invoked ONLY when the harvest
decision agent has determined that a block should be ABANDONED — the crop is
not worth picking for the fresh market.

## Your job

Find a destination for the standing crop within the perishability window.
Strawberries must be cooled within hours of picking and have a shelf life
measured in days. A gleaning match that arrives two days late is worthless.

## The block

- Region: {DEMO_BLOCK.region}
- Crop: {DEMO_BLOCK.crop}
- Acres standing: {DEMO_BLOCK.acres_standing}
- Picks remaining: {DEMO_BLOCK.picks_remaining}

## Recovery channels (in priority order)

1. **Food bank / gleaning organisation** — free to the grower, fastest response,
   but limited cold storage and volunteer crew capacity. Best for partial
   volume.
2. **Processor (freezing, puree, juice)** — pays less ($2-4/flat vs $8 fresh)
   but absorbs large volume and tolerates fruit a food bank cannot move fast
   enough. This is the volume channel.

Always offer BOTH channels. The grower may split: food bank takes what they
can handle today, processor takes the rest.

## Workflow

1. Search for food banks near the block.
2. Search for processors that accept the commodity.
3. Draft a routing recommendation: which food bank(s) to contact, which
   processor, estimated volumes for each, and a timeline (call now, pickup
   within X hours).
4. Draft the advisory text that will be sent to the grower and the receiving
   organisations.

## Rules

- Be specific. Name actual organisations from the tool results.
- Include a timeline. Hours, not days.
- Mark anything you cannot verify from tool results as a placeholder.
- The advisory you draft will be printed for human approval. You do NOT send
  it. The program handles the send after explicit confirmation.
"""


def build_recovery_agent(model_name: str = "gpt-4o"):
    """Build and return the recovery routing agent.

    This is a second create_agent instance with its own tools and prompt.
    Called only on the ABANDON branch.
    """
    load_dotenv()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set.")

    model = ChatOpenAI(model=model_name, api_key=api_key, temperature=0)
    agent = create_agent(
        model,
        [search_food_banks, search_processors],
        system_prompt=RECOVERY_PROMPT,
    )
    return agent


# ---------------------------------------------------------------------------
# send_advisory — stubbed, called from OUTSIDE the agent loop
# ---------------------------------------------------------------------------
def send_advisory(recipient: str, subject: str, body: str) -> str:
    """Send an advisory message to a recipient via Composio.

    This function is called from OUTSIDE the agent loop, only after the
    human has typed explicit confirmation. The agent never holds this
    function as a tool — it is a structural gate, not a prompted one.

    Uses Composio's Gmail integration. Falls back to terminal print if
    no Gmail account is connected.
    """
    from .composio_send import send_advisory_via_composio

    # Parse recipient — if it looks like an email, use it directly
    # Otherwise it's a label and we use the terminal fallback
    if '@' in recipient:
        return send_advisory_via_composio(recipient, subject, body)
    else:
        # Terminal fallback for named recipients (demo mode)
        from .composio_send import _terminal_fallback
        return _terminal_fallback(recipient, subject, body)


RECOVERY_TOOLS = [search_food_banks, search_processors]
