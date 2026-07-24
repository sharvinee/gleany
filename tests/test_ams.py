"""Tests for the AMS market data layer.

Tests run against a saved fixture of a live MARS API response (slug 2390,
Report Details, 2026-07-23), not against the live API. The fixture is in
tests/fixtures/ams_2390_report_details.json.

Per AGENTS.md / SPEC:
  - Filter inside the function on commodity and district fields, not report name.
  - Never return the full payload.
  - data_age_hours computed from the report's published_date, not fetch time.
  - Every signal carries its source through to the decision record.
"""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.ams import (
    get_ams_price,
    AMSPriceResult,
    AMSPriceRow,
    _parse_price,
    _compute_data_age_hours,
    _matches,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ams_2390_report_details.json"


def _load_fixture() -> dict:
    """Load the saved live response fixture."""
    with open(FIXTURE_PATH) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Fixture verification — make sure the fixture itself is sound
# ---------------------------------------------------------------------------
class TestFixtureIntegrity:
    """The fixture is our stand-in for the live API. Verify it's real."""

    def test_fixture_exists(self):
        assert FIXTURE_PATH.exists(), (
            f"Fixture not found at {FIXTURE_PATH}. "
            f"Run dump_ams.py to regenerate it."
        )

    def test_fixture_has_results(self):
        data = _load_fixture()
        results = data.get("results", [])
        assert len(results) > 0, "Fixture should have results"
        # The live response had 53 rows
        assert len(results) == 53, (
            f"Expected 53 rows in fixture, got {len(results)}"
        )

    def test_fixture_contains_strawberries(self):
        data = _load_fixture()
        commodities = {r["commodity"] for r in data["results"]}
        assert "Strawberries" in commodities

    def test_fixture_contains_santa_maria(self):
        data = _load_fixture()
        districts = {r["district"] for r in data["results"]}
        assert "SANTA MARIA CALIFORNIA" in districts


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------
class TestParsePrice:
    def test_parses_numeric_string(self):
        assert _parse_price("6") == 6.0
        assert _parse_price("14.00") == 14.0

    def test_returns_none_for_null(self):
        assert _parse_price(None) is None

    def test_returns_none_for_empty(self):
        assert _parse_price("") is None

    def test_returns_none_for_na(self):
        assert _parse_price("N/A") is None

    def test_returns_none_for_garbage(self):
        assert _parse_price("abc") is None


class TestMatches:
    def test_matches_exact(self):
        row = {"commodity": "Strawberries", "district": "SANTA MARIA CALIFORNIA"}
        assert _matches(row, "Strawberries", "Santa Maria")

    def test_matches_case_insensitive(self):
        row = {"commodity": "Strawberries", "district": "SANTA MARIA CALIFORNIA"}
        assert _matches(row, "strawberries", "santa maria")

    def test_matches_substring(self):
        row = {"commodity": "Strawberries", "district": "SANTA MARIA CALIFORNIA"}
        assert _matches(row, "strawberry", "Santa Maria")

    def test_does_not_match_wrong_district(self):
        row = {"commodity": "Strawberries", "district": "SALINAS-WATSONVILLE CALIFORNIA"}
        assert not _matches(row, "Strawberries", "Santa Maria")

    def test_does_not_match_wrong_commodity(self):
        row = {"commodity": "Grapes", "district": "SANTA MARIA CALIFORNIA"}
        assert not _matches(row, "Strawberries", "Santa Maria")

    def test_handles_missing_fields(self):
        assert not _matches({}, "Strawberries", "Santa Maria")


class TestDataAge:
    def test_computes_age_from_recent_date(self):
        # A date a few hours ago should produce a small positive age
        age = _compute_data_age_hours("07/23/2026 15:18:39")
        # On 2026-07-23 this could be 0+ hours depending on current time
        # Just verify it's a number and non-negative (fixture date is today)
        assert age is not None
        assert isinstance(age, float)
        assert age >= 0

    def test_returns_none_for_empty(self):
        assert _compute_data_age_hours("") is None
        assert _compute_data_age_hours(None) is None

    def test_returns_none_for_bad_format(self):
        assert _compute_data_age_hours("not a date") is None


# ---------------------------------------------------------------------------
# Integration tests against the saved fixture (mocked httpx, no live call)
# ---------------------------------------------------------------------------
class TestGetAmsPrice:
    """Test get_ams_price with mocked httpx returning the saved fixture."""

    @patch("src.ams.httpx.get")
    def test_returns_only_matching_rows(self, mock_get):
        """The function must filter inside the tool and return only
        Strawberry/Santa Maria rows, never the full 53-row payload."""
        fixture = _load_fixture()
        mock_resp = MagicMock()
        mock_resp.json.return_value = fixture
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = get_ams_price(2390, "Strawberries", "Santa Maria")

        assert isinstance(result, AMSPriceResult)
        assert result.row_count == 2, (
            f"Expected 2 strawberry rows for Santa Maria (conv + organic), "
            f"got {result.row_count}"
        )
        # Never return the full payload
        for row in result.rows:
            assert "Strawberries" in row.commodity
            assert "SANTA MARIA" in row.district.upper()

    @patch("src.ams.httpx.get")
    def test_does_not_return_salinas_rows(self, mock_get):
        """Salinas-Watsonville strawberries are in the same report but must
        be filtered out when we ask for Santa Maria."""
        fixture = _load_fixture()
        mock_resp = MagicMock()
        mock_resp.json.return_value = fixture
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = get_ams_price(2390, "Strawberries", "Santa Maria")

        for row in result.rows:
            assert "SALINAS" not in row.district.upper(), (
                f"Salinas rows leaked into Santa Maria filter: {row.district}"
            )

    @patch("src.ams.httpx.get")
    def test_prices_are_parsed_as_floats(self, mock_get):
        """Prices come as strings ('6') and must be parsed to floats."""
        fixture = _load_fixture()
        mock_resp = MagicMock()
        mock_resp.json.return_value = fixture
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = get_ams_price(2390, "Strawberries", "Santa Maria")

        for row in result.rows:
            # Conventional rows should have real prices
            if not row.organic:
                assert row.low_price == 6.0, f"Expected low_price 6.0, got {row.low_price}"
                assert row.high_price == 12.0
                assert row.mostly_low_price == 8.0
                assert row.mostly_high_price == 8.0

    @patch("src.ams.httpx.get")
    def test_organic_flag_parsed(self, mock_get):
        """The organic field is 'Y'/'N' string and must become a bool."""
        fixture = _load_fixture()
        mock_resp = MagicMock()
        mock_resp.json.return_value = fixture
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = get_ams_price(2390, "Strawberries", "Santa Maria")

        organics = [r.organic for r in result.rows]
        assert True in organics, "Should have at least one organic row"
        assert False in organics, "Should have at least one conventional row"

    @patch("src.ams.httpx.get")
    def test_data_age_hours_computed(self, mock_get):
        """Every row must carry data_age_hours from the report's published_date."""
        fixture = _load_fixture()
        mock_resp = MagicMock()
        mock_resp.json.return_value = fixture
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = get_ams_price(2390, "Strawberries", "Santa Maria")

        assert result.data_age_hours is not None, (
            "Result should carry data_age_hours at the report level"
        )
        assert result.data_age_hours >= 0
        for row in result.rows:
            assert row.data_age_hours == result.data_age_hours, (
                "All rows in a report share the same data_age_hours"
            )

    @patch("src.ams.httpx.get")
    def test_published_date_carried_through(self, mock_get):
        """The report's published_date must be present for provenance."""
        fixture = _load_fixture()
        mock_resp = MagicMock()
        mock_resp.json.return_value = fixture
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = get_ams_price(2390, "Strawberries", "Santa Maria")

        assert result.published_date == "07/23/2026 15:18:39"
        for row in result.rows:
            assert row.published_date == "07/23/2026 15:18:39"

    @patch("src.ams.httpx.get")
    def test_source_row_preserved_for_provenance(self, mock_get):
        """SPEC requires every claim to carry its source sentence through to
        the decision record. The source_row dict must be present."""
        fixture = _load_fixture()
        mock_resp = MagicMock()
        mock_resp.json.return_value = fixture
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = get_ams_price(2390, "Strawberries", "Santa Maria")

        for row in result.rows:
            assert isinstance(row.source_row, dict)
            assert "commodity" in row.source_row
            assert "low_price" in row.source_row
            assert "rep_cmt" in row.source_row

    @patch("src.ams.httpx.get")
    def test_hits_report_details_endpoint(self, mock_get):
        """Must hit /reports/{slug_id}/Report Details, not just /reports/{slug_id}.
        The default endpoint returns only the header, not commodity rows."""
        fixture = _load_fixture()
        mock_resp = MagicMock()
        mock_resp.json.return_value = fixture
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        get_ams_price(2390, "Strawberries", "Santa Maria")

        call_args = mock_get.call_args
        url = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
        assert "Report%20Details" in url, (
            f"Must hit the Report Details sub-path. URL was: {url}"
        )

    @patch("src.ams.httpx.get")
    def test_uses_basic_auth_with_key_as_username(self, mock_get):
        """Per SPEC: HTTP basic auth with the key as username and blank password."""
        fixture = _load_fixture()
        mock_resp = MagicMock()
        mock_resp.json.return_value = fixture
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        with patch("src.ams._get_api_key", return_value="test-key"):
            get_ams_price(2390, "Strawberries", "Santa Maria")

        call_args = mock_get.call_args
        auth = call_args[1].get("auth") or (call_args[0][1] if len(call_args[0]) > 1 else None)
        # auth might be passed as positional if the call structure changed,
        # but in our code it's a kwarg
        if auth is None:
            # Check kwargs
            auth = call_args.kwargs.get("auth")
        assert auth is not None, "auth must be passed to httpx.get"
        assert auth[0] == "test-key", f"Username should be the API key, got {auth[0]}"
        assert auth[1] == "", f"Password should be blank, got {auth[1]}"

    @patch("src.ams.httpx.get")
    def test_lastreports_param_when_no_date(self, mock_get):
        """When date is None, should pass lastReports=1 to get the latest report."""
        fixture = _load_fixture()
        mock_resp = MagicMock()
        mock_resp.json.return_value = fixture
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        with patch("src.ams._get_api_key", return_value="test-key"):
            get_ams_price(2390, "Strawberries", "Santa Maria")

        call_args = mock_get.call_args
        params = call_args[1].get("params", {})
        assert params.get("lastReports") == 1
        assert "reportDate" not in params

    @patch("src.ams.httpx.get")
    def test_reportdate_param_when_date_given(self, mock_get):
        """When a date is given, should pass reportDate instead of lastReports."""
        fixture = _load_fixture()
        mock_resp = MagicMock()
        mock_resp.json.return_value = fixture
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        with patch("src.ams._get_api_key", return_value="test-key"):
            get_ams_price(2390, "Strawberries", "Santa Maria", date="07/23/2026")

        call_args = mock_get.call_args
        params = call_args[1].get("params", {})
        assert params.get("reportDate") == "07/23/2026"
        assert "lastReports" not in params

    @patch("src.ams.httpx.get")
    def test_no_matching_rows_returns_empty(self, mock_get):
        """If no rows match the commodity/district filter, return empty —
        not the full payload."""
        fixture = _load_fixture()
        mock_resp = MagicMock()
        mock_resp.json.return_value = fixture
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = get_ams_price(2390, "Kiwis", "Antarctica")

        assert result.row_count == 0
        assert result.rows == []
        # But metadata should still be present
        assert result.published_date is not None

    @patch("src.ams.httpx.get")
    def test_package_field_matches_flat_spec(self, mock_get):
        """The SPEC's trade unit is 'flat, 8 x 1 lb containers'. The API
        package field should say 'flats 8 1-lb containers with lids'."""
        fixture = _load_fixture()
        mock_resp = MagicMock()
        mock_resp.json.return_value = fixture
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = get_ams_price(2390, "Strawberries", "Santa Maria")

        for row in result.rows:
            assert "flats 8 1-lb containers" in row.package, (
                f"Package should be flats 8 1-lb containers, got: {row.package}"
            )
