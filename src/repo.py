"""Repository layer — blocks and cost profiles, scoped to the owning farmer.

Every read/write takes farmer_id and checks ownership. A farmer can never
read or write another farmer's block or costs through this layer.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from fastapi import HTTPException

from .db import get_conn


def create_block(farmer_id: int, data: dict) -> sqlite3.Row:
    conn = get_conn()
    try:
        cur = conn.execute(
            """
            INSERT INTO blocks
                (farmer_id, grower_label, state, region, district, crosscheck_district,
                 commodity, crop_label, acres_standing, picks_remaining, pick_interval,
                 unit, skill_level, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                farmer_id,
                data["grower_label"],
                data["state"],
                data["region"],
                data["district"],
                data.get("crosscheck_district"),
                data["commodity"],
                data["crop_label"],
                data.get("acres_standing"),
                data.get("picks_remaining"),
                data.get("pick_interval"),
                data["unit"],
                data.get("skill_level", "entry"),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        return conn.execute("SELECT * FROM blocks WHERE id = ?", (cur.lastrowid,)).fetchone()
    finally:
        conn.close()


def list_blocks(farmer_id: int) -> list[sqlite3.Row]:
    conn = get_conn()
    try:
        return conn.execute(
            "SELECT * FROM blocks WHERE farmer_id = ? ORDER BY created_at DESC", (farmer_id,)
        ).fetchall()
    finally:
        conn.close()


def get_owned_block(farmer_id: int, block_id: int) -> sqlite3.Row:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM blocks WHERE id = ? AND farmer_id = ?", (block_id, farmer_id)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Block not found.")
        return row
    finally:
        conn.close()


def save_cost_profile(block_id: int, costs: dict) -> sqlite3.Row:
    """Insert a new cost-profile version. Never overwrites — costs are versioned
    so a farmer's history (e.g. last season's freight rate) is never lost."""
    conn = get_conn()
    try:
        cur = conn.execute(
            """
            INSERT INTO cost_profiles
                (block_id, flats_per_person_hour, piece_rate_per_flat, cooling_pack_per_flat,
                 commission_pct, freight_per_flat, domestic_pct, h2a_pct, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                block_id,
                costs.get("flats_per_person_hour"),
                costs.get("piece_rate_per_flat"),
                costs.get("cooling_pack_per_flat"),
                costs.get("commission_pct"),
                costs.get("freight_per_flat"),
                costs.get("domestic_pct", 1.0),
                costs.get("h2a_pct", 0.0),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        return conn.execute("SELECT * FROM cost_profiles WHERE id = ?", (cur.lastrowid,)).fetchone()
    finally:
        conn.close()


def get_latest_cost_profile(block_id: int) -> sqlite3.Row | None:
    conn = get_conn()
    try:
        return conn.execute(
            "SELECT * FROM cost_profiles WHERE block_id = ? ORDER BY created_at DESC LIMIT 1",
            (block_id,),
        ).fetchone()
    finally:
        conn.close()


def list_cost_profile_history(block_id: int) -> list[sqlite3.Row]:
    conn = get_conn()
    try:
        return conn.execute(
            "SELECT * FROM cost_profiles WHERE block_id = ? ORDER BY created_at DESC", (block_id,)
        ).fetchall()
    finally:
        conn.close()


def record_decision_run(
    block_id: int,
    cost_profile_id: int | None,
    band: str,
    net_per_flat: float,
    expected_price: float,
    record_path: str,
) -> None:
    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT INTO decision_runs
                (block_id, cost_profile_id, band, net_per_flat, expected_price, record_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (block_id, cost_profile_id, band, net_per_flat, expected_price, record_path,
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()
