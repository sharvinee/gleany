"""Configuration for the harvest-decision agent.

Block config from SPEC section 3: California strawberries, Santa Maria district.
AMS slugs are hardcoded — never discovered at runtime.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# AMS report slugs (hardcoded per AGENTS.md)
# ---------------------------------------------------------------------------
SLUG_SHIPPING_POINT = 2390   # FR_FV110 — Fresno Shipping Point Fruit Prices
SLUG_NATIONAL_FOB = 3130     # National FOB Review (cross-check) — 404s, not available
SLUG_LA_TERMINAL = 2306      # HC_FV010 — Los Angeles Terminal Market Fruit Prices
                              # Used as the cross-check source since 3130 is down.

# ---------------------------------------------------------------------------
# Required environment keys
# ---------------------------------------------------------------------------
REQUIRED_KEYS = (
    "MARS_API_KEY",
    "OPENAI_API_KEY",
    "OCTEN_API_KEY",
    "COMPOSIO_API_KEY",
)


def load_env() -> dict[str, str]:
    """Load .env from the project root and validate every required key.

    Fails loudly — raises SystemExit listing every missing key — rather than
    silently proceeding with None values.
    """
    project_root = Path(__file__).resolve().parent.parent
    load_dotenv(project_root / ".env")

    missing = [k for k in REQUIRED_KEYS if not os.environ.get(k)]
    if missing:
        sys.exit(
            f"FATAL: missing required environment keys: {', '.join(missing)}.\n"
            f"Check .env at {project_root / '.env'}."
        )

    return {k: os.environ[k] for k in REQUIRED_KEYS}


# ---------------------------------------------------------------------------
# Block config (SPEC section 3)
# ---------------------------------------------------------------------------
@dataclass
class BlockConfig:
    """A single block of standing crop that the agent evaluates."""

    grower_id: str
    region: str
    crop: str
    acres_standing: int
    picks_remaining: int
    pick_interval: str
    unit: str
    # Extra fields populated as placeholders per SPEC section 3 cost-floor table.
    # All marked placeholder — to be filled by grower input.
    flats_per_person_hour: float | None = None       # placeholder
    piece_rate_per_flat: float | None = None          # placeholder
    cooling_pack_per_flat: float | None = None        # placeholder
    commission_pct: float | None = None               # placeholder
    freight_per_flat: float | None = None             # placeholder
    # Crew composition for blended wage: {"domestic": pct, "h2a": pct}
    crew_composition: dict[str, float] = field(default_factory=lambda: {"domestic": 1.0, "h2a": 0.0})


DEMO_BLOCK = BlockConfig(
    grower_id="demo-ca-001",
    region="Santa Maria, Santa Barbara County, CA",
    crop="strawberry, fresh market",
    acres_standing=48,
    picks_remaining=9,
    pick_interval="every 2 to 3 days",
    unit="flat, 8 x 1 lb containers",
)


# ---------------------------------------------------------------------------
# Convenience: load env + return block on import (for tool use)
# ---------------------------------------------------------------------------
_env = None


def get_env() -> dict[str, str]:
    global _env
    if _env is None:
        _env = load_env()
    return _env
