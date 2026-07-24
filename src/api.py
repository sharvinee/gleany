"""FastAPI backend for the Gleany demo frontend.

Exposes endpoints that run the deterministic decision pipeline and return
structured JSON. The frontend is a single HTML page that calls these.

Endpoints:
  GET  /                    → serves the frontend
  POST /api/evaluate        → runs the decision pipeline (GO or ABANDON)
  POST /api/send-advisory   → sends the advisory email via Composio (after approval)
  GET  /api/health          → health check
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from src.ams import get_ams_price as _get_ams_price
from src.config import DEMO_BLOCK, SLUG_SHIPPING_POINT, SLUG_LA_TERMINAL
from src.decision import decide as _decide, GrowerCosts
from src.record import write_decision_record as _write_record
from src.wages import get_wage_floors as _get_wage_floors
from src.recovery import build_recovery_agent, send_advisory

load_dotenv()

app = FastAPI(title="Gleany", version="0.1.0")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------
class EvaluateRequest(BaseModel):
    commodity: str = "Strawberries"
    district: str = "Santa Maria"
    flats_per_person_hour: float = 5.0
    cooling_pack_per_flat: float = 1.50
    commission_pct: float = 12.0
    freight_per_flat: float = 2.00
    # Set higher costs to trigger ABANDON
    abandon_mode: bool = False


class SendAdvisoryRequest(BaseModel):
    recipient: str = "sharvineeeducation@gmail.com"
    subject: str = "Harvest Advisory: Skip Pick — Recovery Routing Recommended"
    body: str = ""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "gleany"}


@app.post("/api/evaluate")
async def evaluate(req: EvaluateRequest) -> dict[str, Any]:
    """Run the full decision pipeline and return structured results."""

    # If abandon_mode, use higher costs
    if req.abandon_mode:
        cooling = 3.00
        commission = 20.0
        freight = 4.00
    else:
        cooling = req.cooling_pack_per_flat
        commission = req.commission_pct
        freight = req.freight_per_flat

    # 1. Fetch live prices from both sources
    price_shipping = _get_ams_price(
        SLUG_SHIPPING_POINT, req.commodity, req.district
    )
    price_terminal = _get_ams_price(
        SLUG_LA_TERMINAL, req.commodity, "Central Coast"
    )

    shipping_rows = []
    for row in price_shipping.rows:
        shipping_rows.append({
            "district": row.district,
            "organic": row.organic,
            "low_price": row.low_price,
            "high_price": row.high_price,
            "mostly_low": row.mostly_low_price,
            "mostly_high": row.mostly_high_price,
            "published_date": row.published_date,
            "data_age_hours": row.data_age_hours,
            "rep_cmt": row.rep_cmt,
            "source": "Fresno Shipping Point (FR_FV110)",
        })

    terminal_rows = []
    for row in price_terminal.rows:
        terminal_rows.append({
            "district": row.district,
            "organic": row.organic,
            "low_price": row.low_price,
            "high_price": row.high_price,
            "mostly_low": row.mostly_low_price,
            "mostly_high": row.mostly_high_price,
            "published_date": row.published_date,
            "data_age_hours": row.data_age_hours,
            "rep_cmt": row.rep_cmt,
            "source": "LA Terminal Market (HC_FV010)",
        })

    # 2. Wage floors
    wages = _get_wage_floors("CA", 2026, "entry")

    wage_candidates = []
    for c in wages.candidates:
        wage_candidates.append({
            "label": c.label,
            "rate": c.rate,
            "source": c.source,
            "applies_to": c.applies_to,
            "binding": c.binding,
        })

    # 3. Grower costs
    grower_costs = GrowerCosts(
        flats_per_person_hour=req.flats_per_person_hour,
        cooling_pack_per_flat=cooling,
        commission_pct=commission,
        freight_per_flat=freight,
        costs_are_placeholders=True,
        notes=["ALL grower-side costs are placeholders for the demo."],
    )

    # 4. Decide
    result = _decide(
        DEMO_BLOCK, [price_shipping, price_terminal], wages, grower_costs
    )

    # 5. Write decision record
    record_path = Path("decision_record.md")
    _write_record(result, record_path)

    # 6. If ABANDON, run recovery agent
    recovery_text = None
    if result.band.value == "ABANDON":
        try:
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
            recovery_text = recovery_result["messages"][-1].content
        except Exception as e:
            recovery_text = f"Recovery agent error: {e}"

    return {
        "band": result.band.value,
        "band_reason": result.band_reason,
        "net_per_flat": round(result.net_per_flat, 2),
        "expected_price": round(result.expected_price, 2),
        "total_cost": round(result.cost_floor.total_cost_per_flat, 2),
        "harvest_labour": round(result.cost_floor.harvest_labour_per_flat, 2),
        "cooling_pack": round(result.cost_floor.cooling_pack_per_flat, 2),
        "commission": round(result.cost_floor.commission_per_flat, 2),
        "freight": round(result.cost_floor.freight_per_flat, 2),
        "binding_wage": wages.binding_rate,
        "binding_wage_label": wages.binding_label,
        "wage_reason": wages.reason,
        "wage_candidates": wage_candidates,
        "independent_sources": result.input_trace.independent_source_count,
        "confidence_gated": result.confidence_gated,
        "confidence_reason": result.confidence_reason,
        "shipping_prices": shipping_rows,
        "terminal_prices": terminal_rows,
        "block_config": {
            "grower_id": DEMO_BLOCK.grower_id,
            "region": DEMO_BLOCK.region,
            "crop": DEMO_BLOCK.crop,
            "acres_standing": DEMO_BLOCK.acres_standing,
            "picks_remaining": DEMO_BLOCK.picks_remaining,
            "pick_interval": DEMO_BLOCK.pick_interval,
            "unit": DEMO_BLOCK.unit,
        },
        "recovery": recovery_text,
        "summary": result.summary,
        "record_path": str(record_path.resolve()),
    }


@app.post("/api/send-advisory")
async def send_advisory_endpoint(req: SendAdvisoryRequest) -> dict[str, str]:
    """Send the advisory email via Composio. Called only after human approval."""
    result = send_advisory(
        recipient=req.recipient,
        subject=req.subject,
        body=req.body,
    )
    return {"result": result}


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the frontend."""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(index_path.read_text())
    return HTMLResponse("<h1>Frontend not found</h1>", status_code=404)
