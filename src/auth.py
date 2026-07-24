"""Cookie-session auth for the self-serve farmer product.

No third-party auth dependency — PBKDF2 password hashing (stdlib hashlib) and
a server-side session table (src/db.py: sessions). A session token is set as
an httponly cookie; every authenticated endpoint reads it back via
require_farmer().
"""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
from datetime import datetime, timezone

from fastapi import HTTPException, Request

from .db import get_conn

SESSION_COOKIE = "gleany_session"
_PBKDF2_ITERATIONS = 200_000


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    """Returns (password_hash_hex, salt_hex)."""
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return digest.hex(), salt.hex()


def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    salt = bytes.fromhex(salt_hex)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return secrets.compare_digest(digest.hex(), hash_hex)


def create_farmer(email: str, password: str) -> sqlite3.Row:
    email = email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid email address.")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    password_hash, salt = hash_password(password)
    conn = get_conn()
    try:
        existing = conn.execute("SELECT id FROM farmers WHERE email = ?", (email,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="An account with this email already exists.")
        cur = conn.execute(
            "INSERT INTO farmers (email, password_hash, password_salt, created_at) VALUES (?, ?, ?, ?)",
            (email, password_hash, salt, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return conn.execute("SELECT * FROM farmers WHERE id = ?", (cur.lastrowid,)).fetchone()
    finally:
        conn.close()


def authenticate_farmer(email: str, password: str) -> sqlite3.Row:
    email = email.strip().lower()
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM farmers WHERE email = ?", (email,)).fetchone()
        if row is None or not verify_password(password, row["password_salt"], row["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid email or password.")
        return row
    finally:
        conn.close()


def create_session(farmer_id: int) -> str:
    token = secrets.token_urlsafe(32)
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO sessions (token, farmer_id, created_at) VALUES (?, ?, ?)",
            (token, farmer_id, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()
    return token


def destroy_session(token: str) -> None:
    conn = get_conn()
    try:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
    finally:
        conn.close()


def get_farmer_from_request(request: Request) -> sqlite3.Row | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT f.* FROM sessions s JOIN farmers f ON f.id = s.farmer_id WHERE s.token = ?",
            (token,),
        ).fetchone()
        return row
    finally:
        conn.close()


def require_farmer(request: Request) -> sqlite3.Row:
    farmer = get_farmer_from_request(request)
    if farmer is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return farmer
