"""Deterministic harvest-decision logic — pure Python, no LLM, no network.

Takes a block config, AMS price rows, wage floors, and grower costs, computes
the cost floor via cost_floor.compute_cost_floor, applies the confidence gate,
and returns the decision band (GO / PARTIAL / ABANDON / SILENT), the net per
flat, and the full input trace for the audit record.

Per SPEC section 4:

  Three bands:
    GO      — net positive                            → pick as planned
    PARTIAL — net near zero AND external signal       → first-grade-only pick
    ABANDON — net below zero by more than labour term → skip pick, recovery

  Confidence gate:
    - Fewer than two independent price sources → SILENT
    - data_age_hours above threshold           → SILENT
    A demo that correctly stays silent is worth more than one that always fires.

The model extracts, summarises, and drafts. It does not compute the answer.
This module is the answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .ams import AMSPriceResult, AMSPriceRow
from .config import BlockConfig
from .cost_floor import CostFloorResult, compute_cost_floor
from .wages import WageFloorResult


# ---------------------------------------------------------------------------
# Constants — thresholds from SPEC
# ---------------------------------------------------------------------------

# data_age_hours above this gates the decision to SILENT.  AMS publishes on a
# batch schedule; 1–2 days of lag is normal, 3 across a weekend.  At 72 hours
# the signal is too stale to act on.
DATA_AGE_THRESHOLD_HOURS = 72.0

# PARTIAL band: net within this many dollars of zero (either side) is "near
# zero".  The external trigger (import surge, buyer cancellation) is a separate
# signal not available in this deterministic layer; the band is set to PARTIAL
# only when near-zero AND the caller passes external_signals_triggered=True.
PARTIAL_NEAR_ZERO_BAND = 2.0  # USD per flat

# ABANDON band: net must be below zero by more than the labour term alone.
# This means the price doesn't even cover harvest labour, never mind the other
# costs.  If only cooling/freight/commission pushes it negative, that's PARTIAL.


# ---------------------------------------------------------------------------
# Band enum
# ---------------------------------------------------------------------------
class Band(str, Enum):
    GO = "GO"
    PARTIAL = "PARTIAL"
    ABANDON = "ABANDON"
    SILENT = "SILENT"


# ---------------------------------------------------------------------------
# Input trace — every claim carries its source and data age
# ---------------------------------------------------------------------------
@dataclass
class PriceSource:
    """A single independent price source in the input trace."""
    slug_id: int
    slug_name: str
    report_title: str
    district: str
    organic: bool
    low_price: float | None
    high_price: float | None
    mostly_low: float | None
    mostly_high: float | None
    published_date: str
    data_age_hours: float
    rep_cmt: str | None
    source_row: dict = field(default_factory=dict, repr=False)


@dataclass
class InputTrace:
    """Full provenance trail for the decision record."""
    block_config: dict = field(default_factory=dict)
    price_sources: list[PriceSource] = field(default_factory=list)
    independent_source_count: int = 0
    wage_floors: dict = field(default_factory=dict)
    grower_costs: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Decision result
# ---------------------------------------------------------------------------
@dataclass
class DecisionResult:
    """The full output of decide()."""
    band: Band
    band_reason: str
    net_per_flat: float
    expected_price: float
    cost_floor: CostFloorResult
    input_trace: InputTrace
    # Human-readable summary for the record
    summary: str = ""
    # Whether confidence gate fired
    confidence_gated: bool = False
    confidence_reason: str = ""


# ---------------------------------------------------------------------------
# Grower costs input
# ---------------------------------------------------------------------------
@dataclass
class GrowerCosts:
    """Grower-side costs, all per flat unless noted.  Any None is a placeholder.

    These are the inputs the agent cannot determine — they come from the grower.
    The SPEC marks them as placeholders for the demo.
    """
    flats_per_person_hour: float | None = None     # pick rate
    cooling_pack_per_flat: float | None = None
    commission_pct: float | None = None            # percentage of price
    freight_per_flat: float | None = None
    # External signal flags (from Octen or other unstructured sources)
    external_signals_triggered: bool = False
    # Any extra note about these costs (e.g. "all placeholders for demo")
    notes: list[str] = field(default_factory=list)
    # When True, all non-None costs above are demo placeholders, not real grower
    # inputs.  The record writer must mark them as such.
    costs_are_placeholders: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _price_row_to_source(row: AMSPriceRow) -> PriceSource:
    """Convert an AMSPriceRow into an InputTrace PriceSource."""
    return PriceSource(
        slug_id=row.slug_id,
        slug_name=row.slug_name,
        report_title=row.report_title,
        district=row.district,
        organic=row.organic,
        low_price=row.low_price,
        high_price=row.high_price,
        mostly_low=row.mostly_low_price,
        mostly_high=row.mostly_high_price,
        published_date=row.published_date,
        data_age_hours=row.data_age_hours,
        rep_cmt=row.rep_cmt,
        source_row=row.source_row,
    )


def _select_price_for_net(rows: list[AMSPriceRow]) -> tuple[float | None, str]:
    """Choose the price to use in the net calculation.

    For the demo block (conventional strawberries, Santa Maria), we use the
    conventional row's mostly_low_price — the lower end of the "mostly" range
    is the conservative estimate.  If only organic is available, use that.

    Returns (price, rationale).
    """
    conventional = [r for r in rows if not r.organic]
    organic = [r for r in rows if r.organic]

    if conventional:
        row = conventional[0]
        price = row.mostly_low_price
        if price is None:
            price = row.low_price
        if price is None:
            return None, (
                f"Conventional row has no price (low={row.low_price}, "
                f"mostly_low={row.mostly_low_price}). Market may not be established."
            )
        return price, (
            f"Using conventional mostly_low_price ${price:.2f} from "
            f"{row.district} (published {row.published_date}). "
            f"Conservative: lower end of the 'mostly' range."
        )

    if organic:
        row = organic[0]
        price = row.mostly_low_price
        if price is None:
            price = row.low_price
        if price is None:
            return None, "No price available from any row."
        return price, (
            f"No conventional row found; using organic mostly_low_price "
            f"${price:.2f} from {row.district}."
        )

    return None, "No price rows available."


def _count_independent_sources(
    price_results: list[AMSPriceResult],
) -> int:
    """Count independent price sources.

    Two AMS slugs (e.g. 2390 shipping point + 3130 national FOB) are two
    independent sources.  Multiple rows from the same slug/report are one
    source — they share a published_date and report.
    """
    slugs_seen: set[int] = set()
    for result in price_results:
        if result.row_count > 0 and result.slug_id not in slugs_seen:
            slugs_seen.add(result.slug_id)
    return len(slugs_seen)


# ---------------------------------------------------------------------------
# The decision function
# ---------------------------------------------------------------------------
def decide(
    block_config: BlockConfig,
    price_results: list[AMSPriceResult],
    wage_floors: WageFloorResult,
    grower_costs: GrowerCosts,
) -> DecisionResult:
    """Compute the harvest decision deterministically.

    Args:
        block_config:   The standing-crop block (acres, picks, unit, etc.).
        price_results:  One or more AMSPriceResult objects from get_ams_price.
                         Multiple results = multiple independent sources.
        wage_floors:    Result of get_wage_floors() — binding rate and candidates.
        grower_costs:   Grower-side costs (pick rate, cooling, freight, etc.).
                         Any None is a placeholder.

    Returns:
        DecisionResult with the band, net per flat, cost floor breakdown, and
        the full input trace for the audit record.
    """
    # --- Build the input trace ---
    trace = InputTrace()

    # Block config
    trace.block_config = {
        "grower_id": block_config.grower_id,
        "region": block_config.region,
        "crop": block_config.crop,
        "acres_standing": block_config.acres_standing,
        "picks_remaining": block_config.picks_remaining,
        "pick_interval": block_config.pick_interval,
        "unit": block_config.unit,
    }

    # Price sources — flatten all rows from all results into the trace
    all_rows: list[AMSPriceRow] = []
    for result in price_results:
        for row in result.rows:
            trace.price_sources.append(_price_row_to_source(row))
            all_rows.append(row)

    trace.independent_source_count = _count_independent_sources(price_results)

    # Wage floors
    trace.wage_floors = {
        "state": wage_floors.state,
        "year": wage_floors.year,
        "skill_level": wage_floors.skill_level,
        "binding_rate": wage_floors.binding_rate,
        "binding_label": wage_floors.binding_label,
        "reason": wage_floors.reason,
        "candidates": [
            {"label": c.label, "rate": c.rate, "source": c.source,
             "applies_to": c.applies_to, "binding": c.binding}
            for c in wage_floors.candidates
        ],
    }

    # Grower costs
    trace.grower_costs = {
        "flats_per_person_hour": grower_costs.flats_per_person_hour,
        "cooling_pack_per_flat": grower_costs.cooling_pack_per_flat,
        "commission_pct": grower_costs.commission_pct,
        "freight_per_flat": grower_costs.freight_per_flat,
        "external_signals_triggered": grower_costs.external_signals_triggered,
        "costs_are_placeholders": grower_costs.costs_are_placeholders,
    }
    trace.notes.extend(grower_costs.notes)

    # --- Confidence gate (SPEC section 4) ---
    # 1. Fewer than two independent price sources → SILENT
    # 2. data_age_hours above threshold → SILENT
    confidence_reasons: list[str] = []

    if trace.independent_source_count < 2:
        confidence_reasons.append(
            f"Only {trace.independent_source_count} independent price source(s). "
            f"SPEC requires at least two. Staying silent — a demo that correctly "
            f"stays silent is worth more than one that always fires."
        )

    # Check data age across all sources
    max_age = 0.0
    for src in trace.price_sources:
        if src.data_age_hours is not None and src.data_age_hours > max_age:
            max_age = src.data_age_hours
    if max_age > DATA_AGE_THRESHOLD_HOURS:
        confidence_reasons.append(
            f"Data age {max_age:.1f} hours exceeds threshold "
            f"of {DATA_AGE_THRESHOLD_HOURS:.0f} hours. "
            f"Structured input is too stale to act on."
        )

    # If no price rows at all
    if not all_rows:
        confidence_reasons.append(
            "No price rows returned from any source. Cannot compute a decision."
        )

    if confidence_reasons:
        return DecisionResult(
            band=Band.SILENT,
            band_reason="; ".join(confidence_reasons),
            net_per_flat=0.0,
            expected_price=0.0,
            cost_floor=CostFloorResult(),
            input_trace=trace,
            summary="SILENT — confidence gate fired.",
            confidence_gated=True,
            confidence_reason="; ".join(confidence_reasons),
        )

    # --- Select the price for the net calculation ---
    expected_price, price_rationale = _select_price_for_net(all_rows)
    trace.notes.append(price_rationale)

    if expected_price is None:
        return DecisionResult(
            band=Band.SILENT,
            band_reason=f"No usable price: {price_rationale}",
            net_per_flat=0.0,
            expected_price=0.0,
            cost_floor=CostFloorResult(),
            input_trace=trace,
            summary="SILENT — no usable price.",
            confidence_gated=True,
            confidence_reason=f"No usable price: {price_rationale}",
        )

    # --- Update block config with grower costs for cost_floor computation ---
    # We create a temporary copy of the block config with the grower costs
    # merged in, rather than mutating the original.
    from dataclasses import replace
    block_with_costs = replace(
        block_config,
        flats_per_person_hour=grower_costs.flats_per_person_hour,
        cooling_pack_per_flat=grower_costs.cooling_pack_per_flat,
        commission_pct=grower_costs.commission_pct,
        freight_per_flat=grower_costs.freight_per_flat,
    )

    # --- Compute the cost floor (deterministic arithmetic) ---
    cost = compute_cost_floor(block_with_costs, wage_floors, expected_price)

    # Carry over any notes from grower_costs
    cost.notes.extend(grower_costs.notes)

    net = cost.net_per_flat
    labour_term = cost.harvest_labour_per_flat

    # --- Apply decision bands (SPEC section 4) ---
    #
    # GO:      net positive
    # PARTIAL: net near zero AND external signal triggered
    # ABANDON: net below zero by more than the labour term alone
    #
    # "By more than the labour term alone" means:
    #   net < -labour_term
    # i.e. the price doesn't even cover harvest labour, never mind the rest.
    # If net is negative but |net| <= labour_term, the other costs (cooling,
    # freight, commission) are what push it under — that's PARTIAL territory
    # if external signals are present, otherwise still GO with a warning.

    if net > 0:
        band = Band.GO
        reason = (
            f"Net ${net:.2f}/flat is positive. "
            f"Price ${expected_price:.2f} covers total cost "
            f"${cost.total_cost_per_flat:.2f}. Pick as planned."
        )
    elif net > -labour_term and net <= 0:
        # Net is near zero or slightly negative but within the labour term
        if grower_costs.external_signals_triggered:
            band = Band.PARTIAL
            reason = (
                f"Net ${net:.2f}/flat is near zero (within labour term "
                f"${labour_term:.2f}) and external signals triggered. "
                f"Advise first-grade-only pick, shorten crew day, reassess next pick."
            )
        else:
            # Near zero but no external trigger — still GO, but flag the margin
            band = Band.GO
            reason = (
                f"Net ${net:.2f}/flat is near zero but positive cost coverage "
                f"from labour alone. No external signals triggered. "
                f"Pick as planned, but margin is thin — monitor."
            )
    elif net <= -labour_term:
        # Net is below zero by more than the labour term
        band = Band.ABANDON
        reason = (
            f"Net ${net:.2f}/flat is below zero by more than the labour term "
            f"(${labour_term:.2f}). Price ${expected_price:.2f} does not even "
            f"cover harvest labour ${labour_term:.2f}/flat. "
            f"Advise skipping this pick. Trigger recovery routing."
        )
    else:
        # Should not reach here, but be defensive
        band = Band.GO
        reason = f"Net ${net:.2f}/flat. Defaulting to GO."

    # Check if near-zero band for PARTIAL even without external signals
    if abs(net) <= PARTIAL_NEAR_ZERO_BAND and net <= 0:
        if grower_costs.external_signals_triggered:
            band = Band.PARTIAL
            reason = (
                f"Net ${net:.2f}/flat is within the near-zero band "
                f"(±${PARTIAL_NEAR_ZERO_BAND:.2f}) and external signals triggered. "
                f"Advise first-grade-only pick, shorten crew day, reassess next pick."
            )

    summary = (
        f"Band: {band.value}. "
        f"Expected price: ${expected_price:.2f}/flat. "
        f"Total cost: ${cost.total_cost_per_flat:.2f}/flat. "
        f"Net: ${net:.2f}/flat. "
        f"Binding wage: ${wage_floors.binding_rate:.2f}/hr ({wage_floors.binding_label}). "
        f"Sources: {trace.independent_source_count} independent. "
        f"Max data age: {max_age:.1f} hours."
    )

    return DecisionResult(
        band=band,
        band_reason=reason,
        net_per_flat=net,
        expected_price=expected_price,
        cost_floor=cost,
        input_trace=trace,
        summary=summary,
        confidence_gated=False,
        confidence_reason="",
    )
