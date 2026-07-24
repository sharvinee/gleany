"""FastAPI backend — self-serve harvest-decision product.

Each farmer signs up, creates blocks (their own fields), keys in and updates
their own costs, and evaluates a block against live USDA AMS prices. No
hardcoded single grower, no demo-only cost overrides — every cost floor
number here is either a live market price or a value the farmer entered.

Endpoints:
  POST /api/signup                       → create a farmer account
  POST /api/login                        → start a session
  POST /api/logout                       → end a session
  GET  /api/me                           → current farmer
  POST /api/blocks                       → create a block (a farmer's field)
  GET  /api/blocks                       → list the farmer's blocks
  GET  /api/blocks/{id}                  → block + latest cost profile
  POST /api/blocks/{id}/costs            → save a new cost-profile version
  GET  /api/blocks/{id}/costs/history    → cost-profile version history
  POST /api/blocks/{id}/evaluate         → run the decision pipeline
  POST /api/send-advisory                → send the advisory email (after approval)
  GET  /api/health                       → health check
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from src import auth, repo
from src.ams import get_ams_price as _get_ams_price
from src.config import BlockConfig, get_ams_sources
from src.db import init_db
from src.decision import decide as _decide, GrowerCosts
from src.record import write_decision_record as _write_record
from src.recovery import build_recovery_agent, send_advisory
from src.wages import get_wage_floors as _get_wage_floors

load_dotenv()
init_db()

app = FastAPI(title="Gleany", version="0.2.0")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
RECORDS_DIR = Path(__file__).resolve().parent.parent / "decision_records"


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------
class SignupRequest(BaseModel):
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class BlockCreateRequest(BaseModel):
    grower_label: str
    state: str
    region: str
    district: str
    crosscheck_district: str | None = None
    commodity: str
    crop_label: str
    acres_standing: float | None = None
    picks_remaining: int | None = None
    pick_interval: str | None = None
    unit: str
    skill_level: str = "entry"


class CostProfileRequest(BaseModel):
    flats_per_person_hour: float | None = None
    piece_rate_per_flat: float | None = None
    cooling_pack_per_flat: float | None = None
    commission_pct: float | None = None
    freight_per_flat: float | None = None
    domestic_pct: float = 1.0
    h2a_pct: float = 0.0


class EvaluateRequest(BaseModel):
    external_signals_triggered: bool = False


class SendAdvisoryRequest(BaseModel):
    subject: str = "Harvest Advisory: Skip Pick — Recovery Routing Recommended"
    body: str = ""
    recipient: str | None = None  # defaults to the current farmer's own email


def _farmer_dict(row) -> dict[str, Any]:
    return {"id": row["id"], "email": row["email"]}


def _block_dict(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "grower_label": row["grower_label"],
        "state": row["state"],
        "region": row["region"],
        "district": row["district"],
        "crosscheck_district": row["crosscheck_district"],
        "commodity": row["commodity"],
        "crop_label": row["crop_label"],
        "acres_standing": row["acres_standing"],
        "picks_remaining": row["picks_remaining"],
        "pick_interval": row["pick_interval"],
        "unit": row["unit"],
        "skill_level": row["skill_level"],
    }


def _cost_dict(row) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "flats_per_person_hour": row["flats_per_person_hour"],
        "piece_rate_per_flat": row["piece_rate_per_flat"],
        "cooling_pack_per_flat": row["cooling_pack_per_flat"],
        "commission_pct": row["commission_pct"],
        "freight_per_flat": row["freight_per_flat"],
        "domestic_pct": row["domestic_pct"],
        "h2a_pct": row["h2a_pct"],
        "created_at": row["created_at"],
    }


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "gleany"}


@app.post("/api/signup")
async def signup(req: SignupRequest, response: Response):
    farmer = auth.create_farmer(req.email, req.password)
    token = auth.create_session(farmer["id"])
    response.set_cookie(auth.SESSION_COOKIE, token, httponly=True, samesite="lax")
    return _farmer_dict(farmer)


@app.post("/api/login")
async def login(req: LoginRequest, response: Response):
    farmer = auth.authenticate_farmer(req.email, req.password)
    token = auth.create_session(farmer["id"])
    response.set_cookie(auth.SESSION_COOKIE, token, httponly=True, samesite="lax")
    return _farmer_dict(farmer)


@app.post("/api/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get(auth.SESSION_COOKIE)
    if token:
        auth.destroy_session(token)
    response.delete_cookie(auth.SESSION_COOKIE)
    return {"result": "logged out"}


@app.get("/api/me")
async def me(farmer=Depends(auth.require_farmer)):
    return _farmer_dict(farmer)


# ---------------------------------------------------------------------------
# Block endpoints
# ---------------------------------------------------------------------------
@app.post("/api/blocks")
async def create_block(req: BlockCreateRequest, farmer=Depends(auth.require_farmer)):
    block = repo.create_block(farmer["id"], req.model_dump())
    return _block_dict(block)


@app.get("/api/blocks")
async def list_blocks(farmer=Depends(auth.require_farmer)):
    return [_block_dict(b) for b in repo.list_blocks(farmer["id"])]


@app.get("/api/blocks/{block_id}")
async def get_block(block_id: int, farmer=Depends(auth.require_farmer)):
    block = repo.get_owned_block(farmer["id"], block_id)
    latest_costs = repo.get_latest_cost_profile(block_id)
    return {"block": _block_dict(block), "latest_costs": _cost_dict(latest_costs)}


# ---------------------------------------------------------------------------
# Cost-profile endpoints — this is where the farmer keys in and customizes costs
# ---------------------------------------------------------------------------
@app.post("/api/blocks/{block_id}/costs")
async def save_costs(block_id: int, req: CostProfileRequest, farmer=Depends(auth.require_farmer)):
    repo.get_owned_block(farmer["id"], block_id)  # 404s if not owned
    profile = repo.save_cost_profile(block_id, req.model_dump())
    return _cost_dict(profile)


@app.get("/api/blocks/{block_id}/costs/history")
async def cost_history(block_id: int, farmer=Depends(auth.require_farmer)):
    repo.get_owned_block(farmer["id"], block_id)
    return [_cost_dict(c) for c in repo.list_cost_profile_history(block_id)]


# ---------------------------------------------------------------------------
# Evaluate — the decision pipeline, run against a farmer's own block + costs
# ---------------------------------------------------------------------------
@app.post("/api/blocks/{block_id}/evaluate")
async def evaluate(block_id: int, req: EvaluateRequest, farmer=Depends(auth.require_farmer)) -> dict[str, Any]:
    block = repo.get_owned_block(farmer["id"], block_id)
    cost_row = repo.get_latest_cost_profile(block_id)
    if cost_row is None:
        raise HTTPException(
            status_code=400,
            detail="No cost profile saved for this block yet. Save your costs before evaluating.",
        )

    # 1. Fetch live prices from every AMS source registered for this commodity.
    ams_sources = get_ams_sources(block["commodity"])
    if not ams_sources:
        raise HTTPException(
            status_code=400,
            detail=f"No AMS report sources configured for commodity '{block['commodity']}'.",
        )

    price_results = []
    price_rows_out: list[dict] = []
    for source in ams_sources:
        district = block["district"] if source.role == "primary" else (
            block["crosscheck_district"] or source.default_district or block["district"]
        )
        result = _get_ams_price(source.slug_id, block["commodity"], district)
        price_results.append(result)
        for row in result.rows:
            price_rows_out.append({
                "district": row.district,
                "organic": row.organic,
                "low_price": row.low_price,
                "high_price": row.high_price,
                "mostly_low": row.mostly_low_price,
                "mostly_high": row.mostly_high_price,
                "published_date": row.published_date,
                "data_age_hours": row.data_age_hours,
                "rep_cmt": row.rep_cmt,
                "source": f"{source.report_name} [{source.role}]",
            })

    # 2. Wage floors — scoped to the block's own state and skill level.
    wages = _get_wage_floors(block["state"], datetime.now().year, block["skill_level"])

    wage_candidates = [
        {"label": c.label, "rate": c.rate, "source": c.source, "applies_to": c.applies_to, "binding": c.binding}
        for c in wages.candidates
    ]

    # 3. Grower costs — entirely the farmer's own saved values. Any field left
    #    blank is None and cost_floor.py records it as a placeholder; nothing
    #    here is a scripted demo override.
    grower_costs = GrowerCosts(
        flats_per_person_hour=cost_row["flats_per_person_hour"],
        cooling_pack_per_flat=cost_row["cooling_pack_per_flat"],
        commission_pct=cost_row["commission_pct"],
        freight_per_flat=cost_row["freight_per_flat"],
        external_signals_triggered=req.external_signals_triggered,
        costs_are_placeholders=False,
        notes=[],
    )

    block_config = BlockConfig(
        grower_id=block["grower_label"],
        region=block["region"],
        crop=block["crop_label"],
        acres_standing=block["acres_standing"] or 0,
        picks_remaining=block["picks_remaining"] or 0,
        pick_interval=block["pick_interval"] or "",
        unit=block["unit"],
        crew_composition={"domestic": cost_row["domestic_pct"], "h2a": cost_row["h2a_pct"]},
    )

    # 4. Decide
    result = _decide(block_config, price_results, wages, grower_costs)

    # 5. Write the decision record — one file per block, plus a DB audit row
    #    per run so a farmer's history isn't lost even though the file itself
    #    only reflects the latest run.
    RECORDS_DIR.mkdir(parents=True, exist_ok=True)
    record_path = RECORDS_DIR / f"block_{block_id}.md"
    _write_record(result, record_path)
    repo.record_decision_run(
        block_id=block_id,
        cost_profile_id=cost_row["id"],
        band=result.band.value,
        net_per_flat=result.net_per_flat,
        expected_price=result.expected_price,
        record_path=str(record_path.resolve()),
    )

    # 6. If ABANDON, run recovery agent parametrized by this block.
    recovery_text = None
    if result.band.value == "ABANDON":
        try:
            recovery_agent = build_recovery_agent(
                region=block["region"],
                crop=block["crop_label"],
                acres_standing=block["acres_standing"],
                picks_remaining=block["picks_remaining"],
            )
            recovery_result = recovery_agent.invoke({
                "messages": [{
                    "role": "user",
                    "content": (
                        f"A grower in {block['region']} is abandoning a "
                        f"{block['crop_label']} pick. {block['acres_standing']} acres, "
                        f"{block['picks_remaining']} picks remaining, unit {block['unit']}. "
                        f"The price doesn't cover harvest labour. Find food banks and "
                        f"processors that can take the crop within the perishability "
                        f"window. Draft a routing recommendation and advisory text."
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
        "price_rows": price_rows_out,
        "block_config": _block_dict(block),
        "recovery": recovery_text,
        "summary": result.summary,
        "record_path": str(record_path.resolve()),
    }


@app.post("/api/send-advisory")
async def send_advisory_endpoint(req: SendAdvisoryRequest, farmer=Depends(auth.require_farmer)) -> dict[str, str]:
    """Send the advisory email via Composio. Called only after human approval."""
    recipient = req.recipient or farmer["email"]
    result = send_advisory(recipient=recipient, subject=req.subject, body=req.body)
    return {"result": result}


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the frontend."""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(index_path.read_text())
    return HTMLResponse("<h1>Frontend not found</h1>", status_code=404)
