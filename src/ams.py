"""USDA AMS Market News (MARS) client — market data layer.

Fetches shipping-point price rows from the MARS API and filters inside the
function so the large payload never reaches the model. Returns only matching
commodity/district rows plus a data_age_hours field computed from the report's
own published date, never from fetch time.

Per AGENTS.md / SPEC:
  - HTTP basic auth: API key as username, blank password.
  - Slugs are hardcoded config, never discovered at runtime.
  - Filter on commodity and district fields, never on report name.
  - Every signal carries data_age_hours from the report's published_date.
  - Never return the full payload.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MARS_BASE_URL = "https://marsapi.ams.usda.gov/services/v1.2"

# The default /reports/{slug_id} endpoint returns only the Report Header
# (metadata, weather).  The actual commodity/district/price rows live in the
# "Report Details" section, which is a sub-path.
_REPORT_DETAILS_PATH = "Report Details"  # URL-encode the space

# Fields we extract from each matching row.  These names are confirmed against
# a live response (slug 2390, 2026-07-23), not guessed from the PDF.
_DETAIL_FIELDS = (
    "report_date",
    "published_date",
    "commodity",
    "district",
    "organic",
    "var",
    "pkg",
    "grade",
    "item_size",
    "low_price",
    "high_price",
    "mostly_low_price",
    "mostly_high_price",
    "rep_cmt",
    "slug_id",
    "slug_name",
    "report_title",
    "market_type",
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class AMSPriceRow:
    """A single matching price row, already filtered and typed."""
    commodity: str
    district: str
    organic: bool
    package: str
    item_size: str
    low_price: float | None
    high_price: float | None
    mostly_low_price: float | None
    mostly_high_price: float | None
    report_date: str
    published_date: str
    data_age_hours: float
    slug_id: int
    slug_name: str
    report_title: str
    rep_cmt: str | None
    # Keep the raw source row for provenance — the SPEC requires every claim to
    # carry its source sentence through to the decision record.
    source_row: dict = field(default_factory=dict, repr=False)


@dataclass
class AMSPriceResult:
    """Wrapper with metadata plus the filtered rows."""
    slug_id: int
    commodity_filter: str
    district_filter: str
    row_count: int
    published_date: str | None       # the report's published_date (for age calc)
    data_age_hours: float | None     # age of the *report*, not individual rows
    rows: list[AMSPriceRow] = field(default_factory=list)
    error: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_api_key() -> str:
    """Load the MARS API key from the environment."""
    load_dotenv()
    key = os.environ.get("MARS_API_KEY")
    if not key:
        raise RuntimeError(
            "MARS_API_KEY not set. Put it in .env — see AGENTS.md."
        )
    return key


def _parse_price(val) -> float | None:
    """Convert a price string like '6' or '14.00' to float. None if null/empty."""
    if val is None or val == "" or val == "N/A":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _parse_published_date(date_str: str) -> datetime | None:
    """Parse the MARS published_date format: 'MM/DD/YYYY HH:MM:SS'.

    The API does not include a timezone offset.  AMS is a US federal service
    publishing from the reporting office's local time.  We treat it as
    US/Pacific for age calculation because the Fresno office reports on
    California markets and publishes in that window.  The age is approximate by
    design — it gates confidence, it does not price an option.
    """
    if not date_str:
        return None
    try:
        # MARS format: "07/23/2026 15:18:39"
        dt = datetime.strptime(date_str, "%m/%d/%Y %H:%M:%S")
        # Treat as Pacific time (the reporting office's wall-clock).
        from zoneinfo import ZoneInfo
        return dt.replace(tzinfo=ZoneInfo("America/Los_Angeles"))
    except ValueError:
        return None


def _compute_data_age_hours(published_date_str: str) -> float | None:
    """Compute hours between the report's published_date and now.

    Clamped to a minimum of 0.  The API does not include a timezone offset and
    we treat the published timestamp as Pacific wall-clock, so a report
    published minutes ago can compute as slightly negative due to clock skew
    or rounding.  A negative age is meaningless — clamp it.
    """
    pub_dt = _parse_published_date(published_date_str)
    if pub_dt is None:
        return None
    now = datetime.now(timezone.utc)
    delta = now - pub_dt
    hours = round(delta.total_seconds() / 3600.0, 1)
    return max(hours, 0.0)


def _normalize_plural(s: str) -> str:
    """Collapse singular/plural forms to a common stem.

    Handles the common English patterns: -ies -> -y (strawberries ->
    strawberry), and trailing -s (apples -> apple).  This is deliberately
    simple — it only needs to bridge the gap between how a caller might
    phrase the commodity (singular, casual) and how AMS stores it (plural,
    Title Case).
    """
    if s.endswith("ies"):
        return s[:-3] + "y"
    return s.rstrip("s")


def _matches(row: dict, commodity: str, district: str) -> bool:
    """Check whether a row matches the commodity and district filters.

    Case-insensitive, plural-normalised substring matching because:
      - commodity in the API is "Strawberries" (plural, Title Case)
      - district is "SANTA MARIA CALIFORNIA" (ALL CAPS, no comma)
    We accept "strawberry" / "Strawberries" and "Santa Maria" / "SANTA MARIA".

    Empty row values never match (an empty string is a substring of
    everything, which would produce false positives on missing data).
    """
    row_commodity = (row.get("commodity") or "").lower().strip()
    row_district = (row.get("district") or "").lower().strip()
    f_commodity = commodity.lower().strip()
    f_district = district.lower().strip()

    if not row_commodity or not f_commodity:
        return False
    if not row_district or not f_district:
        return False

    # Normalise plurals then check substring in either direction.
    nc = _normalize_plural(f_commodity)
    nrc = _normalize_plural(row_commodity)
    commodity_match = nc in nrc or nrc in nc

    # Districts do not have plural issues; plain bidirectional substring.
    district_match = f_district in row_district or row_district in f_district

    return commodity_match and district_match


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def get_ams_price(
    slug_id: int,
    commodity: str,
    district: str,
    date: str | None = None,
) -> AMSPriceResult:
    """Fetch and filter AMS MARS price rows.

    Args:
        slug_id:    The report slug (e.g. 2390 for FR_FV110). Hardcoded config.
        commodity:  Commodity filter, case-insensitive (e.g. "Strawberries").
        district:   District filter, case-insensitive substring
                    (e.g. "Santa Maria").
        date:       Optional report date as "MM/DD/YYYY". If None, fetches the
                    most recent report (lastReports=1).

    Returns:
        AMSPriceResult with only the matching rows. The full payload is never
        returned. Each row carries data_age_hours computed from the report's
        own published_date.

    Raises:
        RuntimeError: if MARS_API_KEY is missing.
        httpx.HTTPError: on network/HTTP failure.
    """
    key = _get_api_key()

    # Build the URL.  The Report Details sub-path is where commodity/district/
    # price rows live.  The default /reports/{slug_id} returns only the header.
    from urllib.parse import quote
    url = f"{MARS_BASE_URL}/reports/{slug_id}/{quote(_REPORT_DETAILS_PATH)}"

    # Query params: lastReports=1 for the latest report, or reportDate for a
    # specific date.
    params: dict[str, str | int] = {}
    if date:
        params["reportDate"] = date
    else:
        params["lastReports"] = 1

    resp = httpx.get(
        url,
        params=params,
        auth=(key, ""),   # basic auth: key as username, blank password
        timeout=30,
    )
    resp.raise_for_status()

    data = resp.json()
    results: list[dict] = data.get("results", [])

    # Determine the report's published_date for data_age_hours.
    # All rows in a single report share the same published_date.
    published_date_str = None
    if results:
        # Note: lowercase 'd' in the Details section
        published_date_str = results[0].get("published_date")

    data_age_hours = None
    if published_date_str:
        data_age_hours = _compute_data_age_hours(published_date_str)

    # Filter inside the function — never return the full payload.
    matching_rows: list[AMSPriceRow] = []
    for row in results:
        if not _matches(row, commodity, district):
            continue
        matching_rows.append(
            AMSPriceRow(
                commodity=row.get("commodity", ""),
                district=row.get("district", ""),
                organic=(row.get("organic", "N") == "Y"),
                package=row.get("pkg", ""),
                item_size=row.get("item_size", ""),
                low_price=_parse_price(row.get("low_price")),
                high_price=_parse_price(row.get("high_price")),
                mostly_low_price=_parse_price(row.get("mostly_low_price")),
                mostly_high_price=_parse_price(row.get("mostly_high_price")),
                report_date=row.get("report_date", ""),
                published_date=published_date_str or "",
                data_age_hours=data_age_hours or 0.0,
                slug_id=row.get("slug_id", slug_id),
                slug_name=row.get("slug_name", ""),
                report_title=row.get("report_title", ""),
                rep_cmt=row.get("rep_cmt"),
                # Keep the raw source dict for provenance per SPEC.
                source_row={k: row.get(k) for k in _DETAIL_FIELDS if k in row},
            )
        )

    return AMSPriceResult(
        slug_id=slug_id,
        commodity_filter=commodity,
        district_filter=district,
        row_count=len(matching_rows),
        published_date=published_date_str,
        data_age_hours=data_age_hours,
        rows=matching_rows,
    )
