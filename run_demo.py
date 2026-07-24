"""Demo script — runs both GO and ABANDON branches for the hackathon pitch.

Track A: Show both decision paths against live market data.
  - Run 1: Current placeholder costs → GO (thin margin, $0.16/flat)
  - Run 2: Higher realistic costs → ABANDON (triggers the gate)

Usage:
    uv run python run_demo.py
"""

from pathlib import Path

from src.ams import get_ams_price
from src.config import DEMO_BLOCK, SLUG_SHIPPING_POINT, SLUG_LA_TERMINAL
from src.decision import decide, GrowerCosts
from src.record import write_decision_record
from src.wages import get_wage_floors


def run_scenario(label, costs, output_file):
    print(f"\n{'='*60}")
    print(f"SCENARIO: {label}")
    print(f"{'='*60}\n")

    # Fetch live prices
    print("[1] Fetching live prices...")
    ps = get_ams_price(SLUG_SHIPPING_POINT, "Strawberries", "Santa Maria")
    pt = get_ams_price(SLUG_LA_TERMINAL, "Strawberries", "Central Coast")
    print(f"    Shipping point: {ps.row_count} rows, age {ps.data_age_hours}h")
    print(f"    Terminal:       {pt.row_count} rows, age {pt.data_age_hours}h")

    # Wages
    print("[2] Wage floors...")
    wages = get_wage_floors("CA", 2026, "entry")
    print(f"    Binding: ${wages.binding_rate:.2f}/hr ({wages.binding_label})")

    # Costs
    print(f"[3] Grower costs: fph={costs.flats_per_person_hour}, "
          f"cool=${costs.cooling_pack_per_flat}, comm={costs.commission_pct}%, "
          f"freight=${costs.freight_per_flat}")

    # Decide
    print("[4] Computing decision...")
    result = decide(DEMO_BLOCK, [ps, pt], wages, costs)
    print(f"    Band: {result.band.value}")
    print(f"    Net:  ${result.net_per_flat:.2f}/flat")
    print(f"    Cost: ${result.cost_floor.total_cost_per_flat:.2f}/flat")
    print(f"    Price: ${result.expected_price:.2f}/flat")
    print(f"    Labour: ${result.cost_floor.harvest_labour_per_flat:.2f}/flat")

    # Write record
    print(f"[5] Writing {output_file}...")
    write_decision_record(result, output_file)

    # Handle ABANDON gate
    if result.band.value == "ABANDON":
        print()
        print("⚠️  ABANDON — HUMAN APPROVAL REQUIRED")
        print(f"    {result.band_reason}")
        print(f"    Advisory draft is in {output_file}")
        print(f"    No message sent. Type 'yes' to approve send:")
        try:
            confirm = input("    > ").strip().lower()
        except EOFError:
            confirm = "no"
        if confirm == "yes":
            print("    ✅ Approved — send_advisory would fire here via Composio")
        else:
            print("    ❌ Aborted — no advisory sent")

    return result


def main():
    print("=" * 60)
    print("GLEANY — Harvest Decision Agent Demo")
    print("Two scenarios, live USDA AMS data, deterministic decisions")
    print("=" * 60)

    # Scenario 1: GO — thin margin, current costs
    go_costs = GrowerCosts(
        flats_per_person_hour=5.0,
        cooling_pack_per_flat=1.50,
        commission_pct=12.0,
        freight_per_flat=2.00,
        costs_are_placeholders=True,
        notes=[
            "ALL grower-side costs are placeholders for the demo.",
            "No Octen search was performed in this run.",
        ],
    )
    run_scenario("GO — thin margin (current costs)", go_costs, "decision_record_go.md")

    # Scenario 2: ABANDON — higher costs trigger the gate
    abandon_costs = GrowerCosts(
        flats_per_person_hour=5.0,
        cooling_pack_per_flat=3.00,
        commission_pct=20.0,
        freight_per_flat=4.00,
        costs_are_placeholders=True,
        notes=[
            "ALL grower-side costs are placeholders for the demo.",
            "Higher cooling, commission, and freight to simulate a "
            "scenario where the crop is not worth picking.",
            "No Octen search was performed in this run.",
        ],
    )
    result = run_scenario("ABANDON — costs exceed price", abandon_costs, "decision_record_abandon.md")

    print(f"\n{'='*60}")
    print("Demo complete. Records on disk:")
    print("  - decision_record_go.md      (GO scenario)")
    print("  - decision_record_abandon.md (ABANDON scenario)")
    print("=" * 60)


if __name__ == "__main__":
    main()
