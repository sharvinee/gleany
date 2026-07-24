"""Wage floor selection.

California has three candidate wage floors under the October 2025 IFR:
  - OEWS-derived AEWR (entry: $16.45/hr)
  - H-2A housing-adjusted rate (entry: $13.45/hr, after $3.00 offset)
  - California state minimum wage ($16.90/hr in 2026)

The employer must pay the **highest applicable** rate. The housing-adjusted
figure is never the floor when a higher rate applies. This function returns
every candidate, which one binds, and why — never a bare float.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WageCandidate:
    """A single candidate wage floor with provenance."""
    label: str
    rate: float
    source: str
    applies_to: str          # "domestic", "h2a", or "all"
    binding: bool = False


@dataclass
class WageFloorResult:
    """Full result of wage-floor selection."""
    state: str
    year: int
    skill_level: str
    candidates: list[WageCandidate] = field(default_factory=list)
    binding_rate: float = 0.0
    binding_label: str = ""
    reason: str = ""


# ---------------------------------------------------------------------------
# Static wage tables — CA 2026
# Values from SPEC section 3 cost-floor table and AGENTS.md pitfalls.
# These are real figures from the DOL IFR and CA DIR. Verify before the demo.
# ---------------------------------------------------------------------------
_CA_2026_WAGES = {
    "entry": {
        "oews_aewr": (16.45, "DOL IFR (Oct 2025), OEWS-derived AEWR, entry level"),
        "h2a_adjusted": (13.45, "DOL IFR, H-2A adverse compensation adjustment (-$3.00/hr)"),
        "state_minimum": (16.90, "CA DIR, 2026 state minimum wage"),
    },
    "experienced": {
        "oews_aewr": (18.71, "DOL IFR (Oct 2025), OEWS-derived AEWR, experienced level"),
        "h2a_adjusted": (15.71, "DOL IFR, H-2A adjusted (-$3.00/hr from experienced)"),
        "state_minimum": (16.90, "CA DIR, 2026 state minimum wage"),
    },
}


def get_wage_floors(state: str, year: int, skill_level: str) -> WageFloorResult:
    """Return every candidate wage floor, which one binds, and why.

    Args:
        state:     Two-letter state code, e.g. "CA".
        year:      Calendar year, e.g. 2026.
        skill_level: "entry" or "experienced".

    Returns:
        WageFloorResult with all candidates, the binding rate, and a
        human-readable reason string explaining the selection.
    """
    state = state.upper().strip()
    skill_level = skill_level.lower().strip()

    result = WageFloorResult(state=state, year=year, skill_level=skill_level)

    if state != "CA" or year != 2026:
        result.reason = (
            f"No wage table loaded for state={state}, year={year}. "
            f"Only CA 2026 is configured. Add the table before proceeding."
        )
        return result

    table = _CA_2026_WAGES.get(skill_level)
    if table is None:
        result.reason = (
            f"Unknown skill_level='{skill_level}'. "
            f"Supported: {', '.join(_CA_2026_WAGES.keys())}."
        )
        return result

    oews_rate, oews_src = table["oews_aewr"]
    h2a_rate, h2a_src = table["h2a_adjusted"]
    min_rate, min_src = table["state_minimum"]

    result.candidates = [
        WageCandidate(
            label="OEWS-derived AEWR",
            rate=oews_rate,
            source=oews_src,
            applies_to="all",
        ),
        WageCandidate(
            label="H-2A housing-adjusted",
            rate=h2a_rate,
            source=h2a_src,
            applies_to="h2a",
        ),
        WageCandidate(
            label="California state minimum wage",
            rate=min_rate,
            source=min_src,
            applies_to="all",
        ),
    ]

    # The employer must pay the highest applicable rate. The state minimum wage
    # applies to all workers (domestic and H-2A). The OEWS AEWR also applies to
    # all. The H-2A adjusted rate applies only to H-2A workers and is lower.
    # Binding = highest rate that applies to all workers.
    # If a crew is purely H-2A, the H-2A-adjusted rate is a candidate but the
    # state minimum still binds because it's higher and applies to all.
    applicable = [c for c in result.candidates if c.applies_to == "all"]
    binding_candidate = max(applicable, key=lambda c: c.rate)

    result.binding_rate = binding_candidate.rate
    result.binding_label = binding_candidate.label

    # Build the reason string
    other_candidates = [c for c in result.candidates if c is not binding_candidate]
    reason_parts = [
        f"Binding wage floor is {binding_candidate.label} at ${binding_candidate.rate:.2f}/hr "
        f"({binding_candidate.source}). "
        f"The employer must pay the highest applicable rate. "
    ]

    for c in other_candidates:
        if c.label == "H-2A housing-adjusted":
            reason_parts.append(
                f"The {c.label} rate of ${c.rate:.2f}/hr applies only to H-2A workers "
                f"and is below the state minimum, so it does not bind. "
            )
        else:
            reason_parts.append(
                f"The {c.label} rate of ${c.rate:.2f}/hr is below the binding floor. "
            )

    result.reason = "".join(reason_parts).strip()

    # Mark binding flag on the candidate
    for c in result.candidates:
        c.binding = (c is binding_candidate)

    return result
