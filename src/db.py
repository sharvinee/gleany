"""SQLite data layer.

Replaces the single hardcoded DEMO_BLOCK / hardcoded wage dict / hardcoded AMS
slug constants with real tables a farmer's data lives in:

  farmers          — one row per signed-up farmer
  sessions         — cookie session tokens -> farmer
  blocks           — a farmer's fields (region, crop, acreage, unit, ...)
  cost_profiles    — versioned grower-side costs for a block (farmer keys these in)
  wage_rates       — wage floor table, data instead of a Python constant
  ams_slugs        — commodity -> USDA AMS report slug mapping, data instead of
                     a Python constant
  decision_runs    — audit trail of every evaluate() call, per block

Every table is created with CREATE TABLE IF NOT EXISTS so init_db() is safe to
call on every process start.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "gleany.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS farmers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    farmer_id  INTEGER NOT NULL REFERENCES farmers(id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS blocks (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    farmer_id        INTEGER NOT NULL REFERENCES farmers(id),
    grower_label     TEXT NOT NULL,
    state            TEXT NOT NULL,
    region           TEXT NOT NULL,
    district         TEXT NOT NULL,
    crosscheck_district TEXT,
    commodity        TEXT NOT NULL,
    crop_label       TEXT NOT NULL,
    acres_standing   REAL,
    picks_remaining  INTEGER,
    pick_interval    TEXT,
    unit             TEXT NOT NULL,
    skill_level      TEXT NOT NULL DEFAULT 'entry',
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cost_profiles (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    block_id               INTEGER NOT NULL REFERENCES blocks(id),
    flats_per_person_hour  REAL,
    piece_rate_per_flat    REAL,
    cooling_pack_per_flat  REAL,
    commission_pct         REAL,
    freight_per_flat       REAL,
    domestic_pct           REAL NOT NULL DEFAULT 1.0,
    h2a_pct                REAL NOT NULL DEFAULT 0.0,
    created_at             TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS wage_rates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    state       TEXT NOT NULL,
    year        INTEGER NOT NULL,
    skill_level TEXT NOT NULL,
    label       TEXT NOT NULL,
    rate        REAL NOT NULL,
    source      TEXT NOT NULL,
    applies_to  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ams_slugs (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    commodity            TEXT NOT NULL,
    slug_id              INTEGER NOT NULL,
    report_name          TEXT NOT NULL,
    role                 TEXT NOT NULL,   -- 'primary' or 'crosscheck'
    default_district     TEXT
);

CREATE TABLE IF NOT EXISTS decision_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    block_id        INTEGER NOT NULL REFERENCES blocks(id),
    cost_profile_id INTEGER,
    band            TEXT,
    net_per_flat    REAL,
    expected_price  REAL,
    record_path     TEXT,
    created_at      TEXT NOT NULL
);
"""

# Seed data — the same real figures that used to live in wages.py as a
# hardcoded dict, now rows a future admin (or ingestion job) can add to
# without touching code.
_SEED_WAGE_RATES = [
    ("CA", 2026, "entry", "OEWS-derived AEWR", 16.45,
     "DOL IFR (Oct 2025), OEWS-derived AEWR, entry level", "all"),
    ("CA", 2026, "entry", "H-2A housing-adjusted", 13.45,
     "DOL IFR, H-2A adverse compensation adjustment (-$3.00/hr)", "h2a"),
    ("CA", 2026, "entry", "California state minimum wage", 16.90,
     "CA DIR, 2026 state minimum wage", "all"),
    ("CA", 2026, "experienced", "OEWS-derived AEWR", 18.71,
     "DOL IFR (Oct 2025), OEWS-derived AEWR, experienced level", "all"),
    ("CA", 2026, "experienced", "H-2A housing-adjusted", 15.71,
     "DOL IFR, H-2A adjusted (-$3.00/hr from experienced)", "h2a"),
    ("CA", 2026, "experienced", "California state minimum wage", 16.90,
     "CA DIR, 2026 state minimum wage", "all"),
]

_SEED_AMS_SLUGS = [
    ("Strawberries", 2390, "Fresno Shipping Point Fruit Prices (FR_FV110)",
     "primary", "Santa Maria"),
    ("Strawberries", 2306, "Los Angeles Terminal Market Fruit Prices (HC_FV010)",
     "crosscheck", "Central Coast"),
]


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM wage_rates").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO wage_rates (state, year, skill_level, label, rate, source, applies_to) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                _SEED_WAGE_RATES,
            )
        if conn.execute("SELECT COUNT(*) FROM ams_slugs").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO ams_slugs (commodity, slug_id, report_name, role, default_district) "
                "VALUES (?, ?, ?, ?, ?)",
                _SEED_AMS_SLUGS,
            )
        conn.commit()
    finally:
        conn.close()
