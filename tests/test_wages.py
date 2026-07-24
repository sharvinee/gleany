"""Tests for wage floor selection.

Per SPEC and AGENTS.md:
- CA 2026 entry level has three candidates: 16.45, 13.45, 16.90.
- Binding is the highest applicable: 16.90 (state minimum wage).
- The housing-adjusted 13.45 must be present but must NOT bind.
"""

import pytest

from src.wages import get_wage_floors


class TestEntryLevelBinding:
    """Entry-level CA 2026 wage floor selection."""

    def test_binds_at_state_minimum(self):
        result = get_wage_floors("CA", 2026, "entry")
        assert result.binding_rate == pytest.approx(16.90), (
            f"Expected binding rate 16.90, got {result.binding_rate}"
        )

    def test_reason_names_minimum_wage_as_binding(self):
        result = get_wage_floors("CA", 2026, "entry")
        assert "minimum wage" in result.reason.lower(), (
            f"Reason should name the minimum wage as the binding constraint. "
            f"Got: {result.reason}"
        )
        assert "highest applicable" in result.reason.lower(), (
            f"Reason should explain that the employer pays the highest applicable rate. "
            f"Got: {result.reason}"
        )

    def test_housing_adjusted_present_but_not_binding(self):
        result = get_wage_floors("CA", 2026, "entry")
        h2a_candidates = [c for c in result.candidates if "housing" in c.label.lower()]
        assert len(h2a_candidates) == 1, "Should have exactly one housing-adjusted candidate"
        h2a = h2a_candidates[0]
        assert h2a.rate == pytest.approx(13.45), (
            f"H-2A housing-adjusted rate should be 13.45, got {h2a.rate}"
        )
        assert h2a.binding is False, (
            "H-2A housing-adjusted rate must NOT be the binding floor"
        )

    def test_oews_rate_present(self):
        result = get_wage_floors("CA", 2026, "entry")
        oews = [c for c in result.candidates if "oews" in c.label.lower()]
        assert len(oews) == 1
        assert oews[0].rate == pytest.approx(16.45)

    def test_three_candidates_total(self):
        result = get_wage_floors("CA", 2026, "entry")
        assert len(result.candidates) == 3, (
            f"Expected 3 candidates, got {len(result.candidates)}"
        )

    def test_binding_candidate_flagged(self):
        result = get_wage_floors("CA", 2026, "entry")
        binding = [c for c in result.candidates if c.binding]
        assert len(binding) == 1, "Exactly one candidate should be flagged binding"
        assert binding[0].rate == pytest.approx(16.90)


class TestExperiencedLevel:
    """Experienced-level CA 2026 — sanity checks."""

    def test_oews_experienced_present(self):
        result = get_wage_floors("CA", 2026, "experienced")
        oews = [c for c in result.candidates if "oews" in c.label.lower()]
        assert oews[0].rate == pytest.approx(18.71)

    def test_binds_at_oews_experienced(self):
        """Experienced OEWS rate (18.71) exceeds state minimum (16.90)."""
        result = get_wage_floors("CA", 2026, "experienced")
        assert result.binding_rate == pytest.approx(18.71)
