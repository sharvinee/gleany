"""Wage floor selection.

Candidate wage floors come from the `wage_rates` table (src/db.py), not a
hardcoded Python dict — so adding a new state/year is a data insert, not a
code change and redeploy. Same public interface as before: this function
returns every candidate, which one binds, and why — never a bare float.

The employer must pay the **highest applicable** rate. A housing-adjusted
H-2A figure is never the floor when a higher rate applies to all workers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .db import get_conn


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


def get_wage_floors(state: str, year: int, skill_level: str) -> WageFloorResult:
    """Return every candidate wage floor, which one binds, and why.

    Args:
        state:       Two-letter state code, e.g. "CA".
        year:        Calendar year, e.g. 2026.
        skill_level: "entry" or "experienced".

    Returns:
        WageFloorResult with all candidates, the binding rate, and a
        human-readable reason string explaining the selection.
    """
    state = state.upper().strip()
    skill_level = skill_level.lower().strip()

    result = WageFloorResult(state=state, year=year, skill_level=skill_level)

    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT label, rate, source, applies_to FROM wage_rates "
            "WHERE state = ? AND year = ? AND skill_level = ?",
            (state, year, skill_level),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        result.reason = (
            f"No wage table loaded for state={state}, year={year}, "
            f"skill_level={skill_level}. Add rows to wage_rates before proceeding."
        )
        return result

    result.candidates = [
        WageCandidate(label=r["label"], rate=r["rate"], source=r["source"], applies_to=r["applies_to"])
        for r in rows
    ]

    # The employer must pay the highest applicable rate. A candidate whose
    # applies_to is "all" binds for everyone; an "h2a"-only candidate can
    # never be the binding rate for a crew that includes any domestic labour,
    # and even a purely H-2A crew is still subject to the "all" candidates.
    applicable = [c for c in result.candidates if c.applies_to == "all"]
    if not applicable:
        result.reason = (
            f"No state/AEWR-wide candidate found for state={state}, year={year}, "
            f"skill_level={skill_level} — only H-2A-specific rates are loaded. "
            f"Cannot determine a binding floor."
        )
        return result

    binding_candidate = max(applicable, key=lambda c: c.rate)
    result.binding_rate = binding_candidate.rate
    result.binding_label = binding_candidate.label

    other_candidates = [c for c in result.candidates if c is not binding_candidate]
    reason_parts = [
        f"Binding wage floor is {binding_candidate.label} at ${binding_candidate.rate:.2f}/hr "
        f"({binding_candidate.source}). "
        f"The employer must pay the highest applicable rate. "
    ]
    for c in other_candidates:
        if c.applies_to == "h2a":
            reason_parts.append(
                f"The {c.label} rate of ${c.rate:.2f}/hr applies only to H-2A workers "
                f"and is below the binding floor, so it does not bind. "
            )
        else:
            reason_parts.append(
                f"The {c.label} rate of ${c.rate:.2f}/hr is below the binding floor. "
            )
    result.reason = "".join(reason_parts).strip()

    for c in result.candidates:
        c.binding = (c is binding_candidate)

    return result
