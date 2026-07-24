"""Cost floor arithmetic — pure deterministic computation.

No LLM call, no network call, no agent. This module takes a block config and
wage inputs and returns the per-flat cost breakdown and net return.

Per SPEC section 4:

    net = expected_price
          - harvest_labour_per_flat
          - cooling_pack_per_flat
          - commission_per_flat
          - freight_per_flat

    harvest_labour_per_flat = binding_wage / flats_per_person_hour

For a mixed crew, compute the labour term per group and blend by crew
composition. Never average the candidate wage figures directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import BlockConfig
from .wages import WageFloorResult


@dataclass
class CostFloorResult:
    """Full cost-floor breakdown for a single block."""
    # Wage inputs
    binding_wage: float = 0.0
    binding_label: str = ""
    wage_reason: str = ""

    # Per-flat costs (USD)
    harvest_labour_per_flat: float = 0.0
    cooling_pack_per_flat: float = 0.0
    commission_per_flat: float = 0.0
    freight_per_flat: float = 0.0
    total_cost_per_flat: float = 0.0

    # Blended labour (for mixed crews)
    blended_labour_per_flat: float | None = None
    crew_blended: bool = False

    # Market side
    expected_price: float = 0.0
    net_per_flat: float = 0.0

    # Provenance / placeholders
    notes: list[str] = field(default_factory=list)


def compute_cost_floor(
    block_config: BlockConfig,
    wage_inputs: WageFloorResult,
    expected_price: float = 0.0,
) -> CostFloorResult:
    """Compute the cost floor and net return per flat.

    Args:
        block_config:    The block of standing crop (from config.py).
        wage_inputs:     Result of get_wage_floors() — contains binding rate.
        expected_price:  Market price per flat (USD). Defaults to 0 — the
                         caller supplies this from a live AMS call. A value of
                         0 means "no price yet" and net will be negative.

    Returns:
        CostFloorResult with every component broken out. Any input that is a
        placeholder (None) is recorded in notes as such and treated as 0.
    """
    result = CostFloorResult()
    result.binding_wage = wage_inputs.binding_rate
    result.binding_label = wage_inputs.binding_label
    result.wage_reason = wage_inputs.reason
    result.expected_price = expected_price

    # --- Harvest labour ---
    flats_per_hr = block_config.flats_per_person_hour
    if flats_per_hr is None or flats_per_hr <= 0:
        result.harvest_labour_per_flat = 0.0
        result.notes.append(
            "flats_per_person_hour is a placeholder — harvest labour per flat "
            "is not yet computed. Fill from grower input."
        )
    else:
        result.harvest_labour_per_flat = result.binding_wage / flats_per_hr

    # --- Blended labour for mixed crews ---
    crew = block_config.crew_composition
    domestic_pct = crew.get("domestic", 1.0)
    h2a_pct = crew.get("h2a", 0.0)

    if h2a_pct > 0 and domestic_pct > 0 and h2a_pct < 1.0:
        # Mixed crew: compute labour per group, blend by composition.
        # Never average the wage rates — compute each group's per-flat cost
        # and weight by share of total output.
        result.crew_blended = True
        if flats_per_hr and flats_per_hr > 0:
            # Find the H-2A adjusted candidate rate from wage_inputs
            h2a_rate = None
            for c in wage_inputs.candidates:
                if c.label == "H-2A housing-adjusted":
                    h2a_rate = c.rate
                    break
            domestic_rate = result.binding_wage  # domestic pays binding floor
            if h2a_rate is not None:
                domestic_labour = domestic_rate / flats_per_hr
                h2a_labour = h2a_rate / flats_per_hr
                result.blended_labour_per_flat = (
                    domestic_labour * domestic_pct + h2a_labour * h2a_pct
                )
                result.harvest_labour_per_flat = result.blended_labour_per_flat
                result.notes.append(
                    f"Mixed crew: {domestic_pct:.0%} domestic at ${domestic_rate:.2f}/hr, "
                    f"{h2a_pct:.0%} H-2A at ${h2a_rate:.2f}/hr. "
                    f"Labour blended per group, not wage rates averaged."
                )
            else:
                result.notes.append(
                    "Mixed crew but H-2A adjusted rate not found in wage_inputs; "
                    "falling back to binding rate for all workers."
                )

    # --- Other per-flat costs ---
    if block_config.cooling_pack_per_flat is None:
        result.cooling_pack_per_flat = 0.0
        result.notes.append("cooling_pack_per_flat is a placeholder — treated as $0.00.")
    else:
        result.cooling_pack_per_flat = block_config.cooling_pack_per_flat

    if block_config.freight_per_flat is None:
        result.freight_per_flat = 0.0
        result.notes.append("freight_per_flat is a placeholder — treated as $0.00.")
    else:
        result.freight_per_flat = block_config.freight_per_flat

    # --- Commission ---
    if block_config.commission_pct is None:
        result.commission_per_flat = 0.0
        result.notes.append("commission_pct is a placeholder — treated as 0%.")
    else:
        result.commission_per_flat = expected_price * (block_config.commission_pct / 100.0)

    # --- Total cost and net ---
    result.total_cost_per_flat = (
        result.harvest_labour_per_flat
        + result.cooling_pack_per_flat
        + result.commission_per_flat
        + result.freight_per_flat
    )
    result.net_per_flat = result.expected_price - result.total_cost_per_flat

    return result
