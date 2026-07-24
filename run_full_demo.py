"""Full demo — GO + ABANDON with recovery routing and human approval gate.

This is the hackathon pitch script. Runs both branches against live USDA data:
  1. GO scenario — thin margin, pick as planned
  2. ABANDON scenario — costs exceed price, triggers recovery routing

On the ABANDON branch:
  - The decision agent drafts the advisory
  - The recovery agent finds food banks and processors
  - The program prints everything and waits for typed confirmation
  - Only after 'yes' does send_advisory fire (from outside the agent loop)
    via Composio Gmail (or terminal fallback if not connected)

Usage:
    uv run python run_full_demo.py
"""

from pathlib import Path

from src.agent import build_agent
from src.recovery import build_recovery_agent, send_advisory


# Where to send the advisory — set to your email to get a real send
ADVISORY_RECIPIENT = "sharvineeeducation@gmail.com"  # CHANGE THIS


def run_go_scenario():
    """Run the GO scenario via the agent."""
    print("\n" + "=" * 60)
    print("SCENARIO 1: GO — thin margin")
    print("=" * 60 + "\n")

    agent = build_agent()
    result = agent.invoke({
        "messages": [{
            "role": "user",
            "content": (
                "Evaluate my Santa Maria strawberry block for today's pick. "
                "Fetch live prices from both sources, get wage floors, "
                "compute the decision with these costs: pick rate 5.0 flats/hr, "
                "cooling $1.50/flat, commission 12%, freight $2.00/flat. "
                "Write the decision record. Then tell me what to do."
            ),
        }]
    })

    output = result["messages"][-1].content
    print("AGENT:\n")
    print(output)
    print()

    # Read band from record
    band = _read_band("decision_record.md")
    print(f"→ Decision: {band}")
    return band


def run_abandon_scenario():
    """Run the ABANDON scenario: decision agent + recovery agent + human gate."""
    print("\n" + "=" * 60)
    print("SCENARIO 2: ABANDON — costs exceed price")
    print("=" * 60 + "\n")

    # Step 1: Decision agent
    print("[Step 1] Decision agent evaluating block...\n")
    agent = build_agent()
    result = agent.invoke({
        "messages": [{
            "role": "user",
            "content": (
                "Evaluate my Santa Maria strawberry block for today's pick. "
                "Fetch live prices from both sources, get wage floors, "
                "compute the decision with these costs: pick rate 5.0 flats/hr, "
                "cooling $3.00/flat, commission 20%, freight $4.00/flat. "
                "Write the decision record. Then tell me what to do."
            ),
        }]
    })

    output = result["messages"][-1].content
    print("DECISION AGENT:\n")
    print(output)
    print()

    band = _read_band("decision_record.md")
    print(f"→ Decision: {band}")

    if band != "ABANDON":
        print(f"\nExpected ABANDON but got {band}. Skipping recovery.")
        return band

    # Step 2: Recovery agent
    print("\n" + "-" * 60)
    print("[Step 2] Recovery agent routing the standing crop...\n")

    recovery_agent = build_recovery_agent()
    recovery_result = recovery_agent.invoke({
        "messages": [{
            "role": "user",
            "content": (
                f"A grower in Santa Maria, CA is abandoning a strawberry pick. "
                f"48 acres, 9 picks remaining, fresh market strawberries in "
                f"flats of 8 one-pound containers. The price doesn't cover "
                f"harvest labour. Find food banks and processors that can "
                f"take the crop within the perishability window. Draft a "
                f"routing recommendation and advisory text."
            ),
        }]
    })

    recovery_output = recovery_result["messages"][-1].content
    print("RECOVERY AGENT:\n")
    print(recovery_output)
    print()

    # Step 3: Human approval gate
    print("-" * 60)
    print("[Step 3] HUMAN APPROVAL GATE\n")
    print("The agents have drafted an advisory but have NOT sent it.")
    print("You must explicitly confirm before anything is sent.\n")
    print(f"The advisory will be emailed to: {ADVISORY_RECIPIENT}")
    print("Type 'yes' to approve sending the advisory, or anything else to abort:")

    try:
        confirm = input("> ").strip().lower()
    except EOFError:
        confirm = "no"

    if confirm == "yes":
        print("\n✅ Approved. Calling send_advisory from outside the agent loop...")
        result = send_advisory(
            recipient=ADVISORY_RECIPIENT,
            subject="Harvest Advisory: Skip Pick — Recovery Routing Recommended",
            body=recovery_output,
        )
        print(result)
    else:
        print("\n❌ Aborted. No advisory sent.")
        print("   The decision record is still on disk as an audit trail.")

    return band


def _read_band(path: str) -> str:
    """Read the band from the decision record file — source of truth."""
    p = Path(path)
    if not p.exists():
        return "UNKNOWN"
    for line in p.read_text().splitlines():
        if line.startswith("## Decision:"):
            return line.replace("## Decision:", "").strip()
    return "UNKNOWN"


def main():
    print("=" * 60)
    print("GLEANY — Full Demo")
    print("Live USDA data · deterministic decisions · agent + recovery")
    print("=" * 60)

    # Scenario 1: GO
    run_go_scenario()

    # Scenario 2: ABANDON with recovery
    run_abandon_scenario()

    print("\n" + "=" * 60)
    print("Demo complete. Records on disk:")
    print("  - decision_record.md  (last scenario run)")
    print("=" * 60)


if __name__ == "__main__":
    main()
