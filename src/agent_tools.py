"""LangChain tool wrappers around the deterministic decision pipeline.

The agent calls these tools to gather signals and compute the decision.
The tools are thin wrappers — all logic lives in the deterministic modules.
The model extracts, summarises, and drafts. It does not compute the answer.

Per AGENTS.md:
  - send_advisory is NOT given to the agent on the abandon path.
  - The agent returns the drafted advisory; the program prints it and requires
    typed confirmation before calling send_advisory from outside the agent loop.
"""

from __future__ import annotations

import json
from pathlib import Path

from langchain_core.tools import tool

from .ams import get_ams_price as _get_ams_price
from .config import (
    DEMO_BLOCK,
    SLUG_SHIPPING_POINT,
    SLUG_LA_TERMINAL,
)
from .decision import decide as _decide, GrowerCosts, Band, DecisionResult
from .record import write_decision_record as _write_record
from .wages import get_wage_floors as _get_wage_floors


# ---------------------------------------------------------------------------
# Tool 1: Fetch AMS shipping-point prices (slug 2390, Santa Maria)
# ---------------------------------------------------------------------------
@tool
def fetch_shipping_point_prices(commodity: str, district: str) -> str:
    """Fetch live USDA AMS shipping-point prices for a commodity and district.

    Hits slug 2390 (Fresno Shipping Point Fruit Prices / FR_FV110), which
    carries Santa Maria and Salinas-Watsonville strawberries plus other
    California fruit. Filters inside the tool so only matching rows return.

    Args:
        commodity: e.g. "Strawberries"
        district:  e.g. "Santa Maria"

    Returns:
        JSON string with matching rows: price range, mostly range, organic
        flag, published date, data age in hours, and report comments.
    """
    result = _get_ams_price(SLUG_SHIPPING_POINT, commodity, district)
    rows = []
    for row in result.rows:
        rows.append({
            "commodity": row.commodity,
            "district": row.district,
            "organic": row.organic,
            "low_price": row.low_price,
            "high_price": row.high_price,
            "mostly_low": row.mostly_low_price,
            "mostly_high": row.mostly_high_price,
            "published_date": row.published_date,
            "data_age_hours": row.data_age_hours,
            "rep_cmt": row.rep_cmt,
            "slug_name": row.slug_name,
        })
    return json.dumps({
        "slug_id": result.slug_id,
        "source": "Fresno Shipping Point (FR_FV110)",
        "row_count": result.row_count,
        "published_date": result.published_date,
        "data_age_hours": result.data_age_hours,
        "rows": rows,
    }, indent=2)


# ---------------------------------------------------------------------------
# Tool 2: Fetch AMS terminal-market prices (slug 2306, LA Terminal)
# ---------------------------------------------------------------------------
@tool
def fetch_terminal_prices(commodity: str, district: str) -> str:
    """Fetch live USDA AMS terminal-market prices for a commodity and district.

    Hits slug 2306 (Los Angeles Terminal Market Fruit Prices / HC_FV010),
    used as a cross-check source. Filters inside the tool.

    Args:
        commodity: e.g. "Strawberries"
        district:  e.g. "Central Coast"

    Returns:
        JSON string with matching rows.
    """
    result = _get_ams_price(SLUG_LA_TERMINAL, commodity, district)
    rows = []
    for row in result.rows:
        rows.append({
            "commodity": row.commodity,
            "district": row.district,
            "organic": row.organic,
            "low_price": row.low_price,
            "high_price": row.high_price,
            "mostly_low": row.mostly_low_price,
            "mostly_high": row.mostly_high_price,
            "published_date": row.published_date,
            "data_age_hours": row.data_age_hours,
            "rep_cmt": row.rep_cmt,
            "slug_name": row.slug_name,
        })
    return json.dumps({
        "slug_id": result.slug_id,
        "source": "LA Terminal Market (HC_FV010)",
        "row_count": result.row_count,
        "published_date": result.published_date,
        "data_age_hours": result.data_age_hours,
        "rows": rows,
    }, indent=2)


# ---------------------------------------------------------------------------
# Tool 3: Get wage floors
# ---------------------------------------------------------------------------
@tool
def get_wage_floors(state: str, year: int, skill_level: str) -> str:
    """Get all candidate wage floors and which one binds.

    Returns the OEWS-derived AEWR, H-2A housing-adjusted rate, and state
    minimum wage. The employer pays the highest applicable rate. The
    housing-adjusted rate applies only to H-2A workers and never binds
    when a higher rate covers all workers.

    Args:
        state:        Two-letter code, e.g. "CA"
        year:         Calendar year, e.g. 2026
        skill_level:  "entry" or "experienced"

    Returns:
        JSON string with all candidates, the binding rate, and the reason.
    """
    result = _get_wage_floors(state, year, skill_level)
    return json.dumps({
        "state": result.state,
        "year": result.year,
        "skill_level": result.skill_level,
        "binding_rate": result.binding_rate,
        "binding_label": result.binding_label,
        "reason": result.reason,
        "candidates": [
            {"label": c.label, "rate": c.rate, "source": c.source,
             "applies_to": c.applies_to, "binding": c.binding}
            for c in result.candidates
        ],
    }, indent=2)


# ---------------------------------------------------------------------------
# Tool 4: Compute the decision (deterministic)
# ---------------------------------------------------------------------------
@tool
def compute_decision(
    commodity: str,
    district: str,
    state: str,
    year: int,
    skill_level: str,
    flats_per_person_hour: float,
    cooling_pack_per_flat: float,
    commission_pct: float,
    freight_per_flat: float,
    external_signals_triggered: bool = False,
) -> str:
    """Compute the harvest decision deterministically.

    This is the core decision engine. It fetches live prices from two
    independent AMS sources, selects the binding wage floor, computes the
    cost floor and net return per flat, applies the confidence gate and
    decision bands, and returns the result. The model does NOT compute
    this — this tool does.

    Args:
        commodity:  e.g. "Strawberries"
        district:   e.g. "Santa Maria"
        state:      e.g. "CA"
        year:       e.g. 2026
        skill_level: "entry" or "experienced"
        flats_per_person_hour: Pick rate (placeholder for demo)
        cooling_pack_per_flat:  Cooling & packing cost per flat (placeholder)
        commission_pct:         Commission percentage of price (placeholder)
        freight_per_flat:       Freight cost per flat (placeholder)
        external_signals_triggered: Whether Octen detected import surge or
                                    buyer cancellation

    Returns:
        JSON string with the band, net per flat, cost breakdown, and
        confidence gate status.
    """
    # Fetch live prices from both sources
    price_shipping = _get_ams_price(SLUG_SHIPPING_POINT, commodity, district)
    price_terminal = _get_ams_price(
        SLUG_LA_TERMINAL, commodity, "Central Coast"
    )
    price_results = [price_shipping, price_terminal]

    # Wage floors
    wages = _get_wage_floors(state, year, skill_level)

    # Grower costs
    grower_costs = GrowerCosts(
        flats_per_person_hour=flats_per_person_hour,
        cooling_pack_per_flat=cooling_pack_per_flat,
        commission_pct=commission_pct,
        freight_per_flat=freight_per_flat,
        external_signals_triggered=external_signals_triggered,
        costs_are_placeholders=True,
        notes=[
            "ALL grower-side costs are placeholders for the demo.",
            "No Octen search was performed in this run.",
        ],
    )

    # Decide
    result = _decide(DEMO_BLOCK, price_results, wages, grower_costs)

    return json.dumps({
        "band": result.band.value,
        "band_reason": result.band_reason,
        "net_per_flat": result.net_per_flat,
        "expected_price": result.expected_price,
        "total_cost_per_flat": result.cost_floor.total_cost_per_flat,
        "harvest_labour_per_flat": result.cost_floor.harvest_labour_per_flat,
        "cooling_pack_per_flat": result.cost_floor.cooling_pack_per_flat,
        "commission_per_flat": result.cost_floor.commission_per_flat,
        "freight_per_flat": result.cost_floor.freight_per_flat,
        "binding_wage": wages.binding_rate,
        "binding_wage_label": wages.binding_label,
        "independent_sources": result.input_trace.independent_source_count,
        "confidence_gated": result.confidence_gated,
        "confidence_reason": result.confidence_reason,
        "summary": result.summary,
    }, indent=2)


# ---------------------------------------------------------------------------
# Tool 5: Write the decision record to disk
# ---------------------------------------------------------------------------
@tool
def write_decision_record(
    commodity: str,
    district: str,
    state: str,
    year: int,
    skill_level: str,
    flats_per_person_hour: float,
    cooling_pack_per_flat: float,
    commission_pct: float,
    freight_per_flat: float,
    external_signals_triggered: bool = False,
) -> str:
    """Run the full decision pipeline and write the decision record to disk.

    This fetches live prices, computes wages, runs the decision, and writes
    decision_record.md. Returns the path to the written file and a summary.

    Args:
        commodity:  e.g. "Strawberries"
        district:   e.g. "Santa Maria"
        state:      e.g. "CA"
        year:       e.g. 2026
        skill_level: "entry" or "experienced"
        flats_per_person_hour: Pick rate (placeholder for demo)
        cooling_pack_per_flat:  Cooling & packing cost per flat (placeholder)
        commission_pct:         Commission percentage (placeholder)
        freight_per_flat:       Freight cost per flat (placeholder)
        external_signals_triggered: Whether external signals were detected

    Returns:
        JSON string with the file path, band, and summary.
    """
    # Fetch prices
    price_shipping = _get_ams_price(SLUG_SHIPPING_POINT, commodity, district)
    price_terminal = _get_ams_price(
        SLUG_LA_TERMINAL, commodity, "Central Coast"
    )
    price_results = [price_shipping, price_terminal]

    # Wages
    wages = _get_wage_floors(state, year, skill_level)

    # Grower costs
    grower_costs = GrowerCosts(
        flats_per_person_hour=flats_per_person_hour,
        cooling_pack_per_flat=cooling_pack_per_flat,
        commission_pct=commission_pct,
        freight_per_flat=freight_per_flat,
        external_signals_triggered=external_signals_triggered,
        costs_are_placeholders=True,
        notes=[
            "ALL grower-side costs are placeholders for the demo.",
            "No Octen search was performed in this run.",
        ],
    )

    # Decide
    result = _decide(DEMO_BLOCK, price_results, wages, grower_costs)

    # Write record
    output_path = Path("decision_record.md")
    written = _write_record(result, output_path)

    return json.dumps({
        "file_path": str(written.resolve()),
        "band": result.band.value,
        "net_per_flat": result.net_per_flat,
        "summary": result.summary,
    }, indent=2)


# ---------------------------------------------------------------------------
# Export the tool list for the agent
# ---------------------------------------------------------------------------
ALL_TOOLS = [
    fetch_shipping_point_prices,
    fetch_terminal_prices,
    get_wage_floors,
    compute_decision,
    write_decision_record,
]
