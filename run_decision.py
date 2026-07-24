"""End-to-end runner: live AMS price + wage floors + decision + record.

Wires the deterministic decision path end to end. No agent, no LLM.
Fetches live market data from two independent AMS sources:
  - Slug 2390 (Fresno Shipping Point) — Santa Maria district strawberries
  - Slug 2306 (LA Terminal Market)   — Central Coast California strawberries
Fetches wage floors for CA 2026, computes the cost floor and decision,
and writes the decision record to disk.

Usage:
    uv run python run_decision.py
"""

from pathlib import Path

from src.ams import get_ams_price
from src.config import (
    DEMO_BLOCK,
    SLUG_SHIPPING_POINT,
    SLUG_LA_TERMINAL,
    SLUG_NATIONAL_FOB,
)
from src.decision import decide, GrowerCosts
from src.record import write_decision_record
from src.wages import get_wage_floors


def main():
    print("=" * 60)
    print("HARVEST DECISION AGENT — Deterministic Decision Path")
    print("No agent, no LLM. Pure Python + live AMS data.")
    print("=" * 60)
    print()

    # --- 1. Fetch live market data from two independent sources ---
    print("[1a] Fetching AMS prices from slug 2390 (Santa Maria shipping point)...")
    price_shipping = get_ams_price(
        SLUG_SHIPPING_POINT,
        commodity="Strawberries",
        district="Santa Maria",
    )
    print(f"     {price_shipping.row_count} rows, published {price_shipping.published_date}, "
          f"age {price_shipping.data_age_hours}h")
    for row in price_shipping.rows:
        print(f"     {row.commodity} / {row.district} / organic={row.organic}: "
              f"${row.low_price}-${row.high_price} mostly "
              f"${row.mostly_low_price}-{row.mostly_high_price}")
    print()

    print("[1b] Fetching AMS prices from slug 2306 (LA Terminal Market)...")
    price_terminal = get_ams_price(
        SLUG_LA_TERMINAL,
        commodity="Strawberries",
        district="Central Coast",
    )
    print(f"     {price_terminal.row_count} rows, published {price_terminal.published_date}, "
          f"age {price_terminal.data_age_hours}h")
    for row in price_terminal.rows:
        print(f"     {row.commodity} / {row.district} / organic={row.organic}: "
              f"${row.low_price}-${row.high_price}")
    print()

    # Note: slug 3130 (National FOB) returns 404 — recorded in config comment.
    # The LA Terminal Market (2306) serves as the cross-check source instead.
    price_results = [price_shipping, price_terminal]
    print(f"     Independent sources: {len([r for r in price_results if r.row_count > 0])}")
    print()

    # --- 2. Wage floors ---
    print("[2] Selecting wage floors (CA 2026, entry level)...")
    wages = get_wage_floors("CA", 2026, "entry")
    print(f"     Binding: ${wages.binding_rate:.2f}/hr ({wages.binding_label})")
    for c in wages.candidates:
        flag = " ← BINDING" if c.binding else ""
        print(f"       {c.label}: ${c.rate:.2f}/hr{flag}")
    print()

    # --- 3. Grower costs (ALL PLACEHOLDERS for the demo) ---
    print("[3] Loading grower costs (ALL PLACEHOLDERS)...")
    grower_costs = GrowerCosts(
        flats_per_person_hour=5.0,        # PLACEHOLDER — 5 flats/hr is a guess
        cooling_pack_per_flat=1.50,       # PLACEHOLDER
        commission_pct=12.0,              # PLACEHOLDER
        freight_per_flat=2.00,            # PLACEHOLDER
        external_signals_triggered=False, # No Octen call in this run
        costs_are_placeholders=True,      # ALL costs are demo placeholders
        notes=[
            "ALL grower-side costs are placeholders for the demo. "
            "Pick rate, cooling, commission, and freight must come from "
            "grower input. These numbers are illustrative, not real.",
            "flats_per_person_hour=5.0 is a placeholder pick rate. "
            "Real value varies by crew, field, and variety.",
            "No Octen search was performed — external_signals_triggered is False.",
        ],
    )
    print(f"     Pick rate: {grower_costs.flats_per_person_hour} flats/hr (PLACEHOLDER)")
    print(f"     Cooling: ${grower_costs.cooling_pack_per_flat}/flat (PLACEHOLDER)")
    print(f"     Commission: {grower_costs.commission_pct}% (PLACEHOLDER)")
    print(f"     Freight: ${grower_costs.freight_per_flat}/flat (PLACEHOLDER)")
    print()

    # --- 4. Decide ---
    print("[4] Computing decision...")
    result = decide(DEMO_BLOCK, price_results, wages, grower_costs)
    print(f"     Band: {result.band.value}")
    print(f"     Net per flat: ${result.net_per_flat:.2f}")
    print(f"     Expected price: ${result.expected_price:.2f}")
    print(f"     Total cost: ${result.cost_floor.total_cost_per_flat:.2f}")
    print(f"     Harvest labour: ${result.cost_floor.harvest_labour_per_flat:.2f}/flat")
    print(f"     Confidence gated: {result.confidence_gated}")
    if result.confidence_gated:
        print(f"     Reason: {result.confidence_reason}")
    print()

    # --- 5. Write the decision record ---
    print("[5] Writing decision record...")
    output_path = Path("decision_record.md")
    written = write_decision_record(result, output_path)
    print(f"     Written to: {written.resolve()}")
    print()

    print("=" * 60)
    print(f"DECISION: {result.band.value}")
    print(result.summary)
    print("=" * 60)


if __name__ == "__main__":
    main()
