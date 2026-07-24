"""Run the harvest-decision agent end to end.

Invokes the LangChain agent, which calls tools to gather live market signals,
compute the deterministic decision, and write the record. On the ABANDON
branch, the agent drafts an advisory but does NOT send it — the program
prints the draft and requires typed confirmation before calling send_advisory
from outside the agent loop.

Usage:
    uv run python run_agent.py
"""

import json
import re
from pathlib import Path

from src.agent import build_agent


def extract_decision_info(agent_output: str) -> dict:
    """Extract the band from the decision record on disk.

    The agent's text is free-form prose, but the decision_record.md file is
    the deterministic source of truth. We read the band from there.
    """
    info = {"band": "UNKNOWN", "advisory_text": agent_output}

    # Read the band from the decision record — the source of truth
    record_path = Path("decision_record.md")
    if record_path.exists():
        text = record_path.read_text()
        for line in text.splitlines():
            # The record has: ## Decision: GO  (or ABANDON, PARTIAL, SILENT)
            if line.startswith("## Decision:"):
                band = line.replace("## Decision:", "").strip()
                info["band"] = band
                break

    return info


def main():
    print("=" * 60)
    print("HARVEST DECISION AGENT — Live Agent Run")
    print("LangChain create_agent + OpenAI + deterministic tools")
    print("=" * 60)
    print()

    # Build the agent
    print("Building agent...")
    agent = build_agent()
    print("Agent ready.")
    print()

    # The user prompt — what the grower asks
    user_prompt = (
        "Evaluate my Santa Maria strawberry block for today's pick decision. "
        "Fetch live prices from both sources, get the wage floors, compute the "
        "decision, and write the record. Then tell me what to do."
    )

    print(f"User: {user_prompt}")
    print()
    print("-" * 60)
    print("Agent working...")
    print("-" * 60)
    print()

    # Invoke the agent
    result = agent.invoke({
        "messages": [{"role": "user", "content": user_prompt}]
    })

    # Extract the agent's final response
    final_msg = result["messages"][-1]
    agent_output = final_msg.content if hasattr(final_msg, "content") else str(final_msg)

    print("AGENT RESPONSE:")
    print()
    print(agent_output)
    print()
    print("-" * 60)

    # Check for ABANDON — requires human approval
    info = extract_decision_info(agent_output)

    if info["band"] == "ABANDON":
        print()
        print("⚠️  ABANDON BRANCH — HUMAN APPROVAL REQUIRED")
        print()
        print("The agent has drafted an advisory but has NOT sent it.")
        print("You must explicitly confirm before any message is sent.")
        print()
        print("Type 'yes' to approve sending, or anything else to abort:")
        try:
            confirmation = input("> ").strip().lower()
        except EOFError:
            confirmation = "no"

        if confirmation == "yes":
            print()
            print("✅ Approved. Calling send_advisory from outside the agent loop...")
            # send_advisory would be called here via Composio.
            # For now, just print the confirmation.
            print("   (Composio send_advisory not yet wired — this is the gate.)")
            print("   Advisory would be sent to the gleaning organisation.")
        else:
            print()
            print("❌ Aborted. No advisory sent. The decision record is still on disk.")
    elif info["band"] == "SILENT":
        print()
        print("🔇 SILENT — confidence gate fired. No action taken.")
    else:
        print()
        print(f"Decision: {info['band']}")

    print()
    print("=" * 60)
    print("Done. Check decision_record.md for the full audit trail.")
    print("=" * 60)


if __name__ == "__main__":
    main()
