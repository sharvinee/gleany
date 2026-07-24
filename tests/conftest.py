"""Shared test fixtures — ensure the SQLite schema and seed data exist before
any test touches wages.py / repo.py, which now read from the DB instead of a
hardcoded Python dict."""

from src.db import init_db

init_db()
