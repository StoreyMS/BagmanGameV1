"""SQLite storage for settlements, evidence, claims and payout accounts."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterator

from .models import ALLOWED_TRANSITIONS, ClaimStatus, Evidence, Match, Settlement

SCHEMA = """
CREATE TABLE IF NOT EXISTS settlements (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    source TEXT NOT NULL,
    claim_url TEXT,
    deadline TEXT,
    class_period_start TEXT,
    class_period_end TEXT,
    proof_required INTEGER,
    payout_text TEXT,
    eligibility_text TEXT,
    description TEXT,
    keywords TEXT NOT NULL DEFAULT '[]',
    keywords_locked INTEGER NOT NULL DEFAULT 0,
    fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS payout_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    method TEXT NOT NULL,      -- paypal, venmo, zelle, check, direct_deposit, other
    handle TEXT NOT NULL,      -- email / username / mailing address. Never a full bank account number.
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    settlement_id TEXT NOT NULL UNIQUE REFERENCES settlements(id),
    status TEXT NOT NULL,
    score INTEGER NOT NULL,
    reasons TEXT NOT NULL DEFAULT '[]',
    evidence TEXT NOT NULL DEFAULT '[]',
    payout_account_id INTEGER REFERENCES payout_accounts(id),
    confirmed_at TEXT,
    filed_at TEXT,
    confirmation_number TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS claim_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id INTEGER NOT NULL REFERENCES claims(id),
    from_status TEXT,
    to_status TEXT NOT NULL,
    note TEXT,
    at TEXT NOT NULL
);
"""


class InvalidTransition(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _d(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _pd(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---- settlements -------------------------------------------------
    def upsert_settlement(self, s: Settlement) -> None:
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT keywords, keywords_locked FROM settlements WHERE id = ?", (s.id,)
            ).fetchone()
            keywords = s.keywords
            if existing and existing["keywords_locked"]:
                keywords = json.loads(existing["keywords"])  # keep your manual edits
            conn.execute(
                """
                INSERT INTO settlements (id, title, url, source, claim_url, deadline, class_period_start,
                    class_period_end, proof_required, payout_text, eligibility_text, description, keywords, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title, url=excluded.url, claim_url=excluded.claim_url,
                    deadline=excluded.deadline, class_period_start=excluded.class_period_start,
                    class_period_end=excluded.class_period_end, proof_required=excluded.proof_required,
                    payout_text=excluded.payout_text, eligibility_text=excluded.eligibility_text,
                    description=excluded.description, keywords=excluded.keywords, fetched_at=excluded.fetched_at
                """,
                (
                    s.id, s.title, s.url, s.source, s.claim_url, _d(s.deadline), _d(s.class_period_start),
                    _d(s.class_period_end), None if s.proof_required is None else int(s.proof_required),
                    s.payout_text, s.eligibility_text, s.description, json.dumps(keywords),
                    (s.fetched_at or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
                ),
            )

    def set_keywords(self, settlement_id: str, keywords: list[str]) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE settlements SET keywords = ?, keywords_locked = 1 WHERE id = ?",
                (json.dumps(keywords), settlement_id),
            )

    @staticmethod
    def _row_to_settlement(row: sqlite3.Row) -> Settlement:
        return Settlement(
            id=row["id"], title=row["title"], url=row["url"], source=row["source"], claim_url=row["claim_url"],
            deadline=_pd(row["deadline"]), class_period_start=_pd(row["class_period_start"]),
            class_period_end=_pd(row["class_period_end"]),
            proof_required=None if row["proof_required"] is None else bool(row["proof_required"]),
            payout_text=row["payout_text"], eligibility_text=row["eligibility_text"],
            description=row["description"], keywords=json.loads(row["keywords"]),
            fetched_at=datetime.fromisoformat(row["fetched_at"]) if row["fetched_at"] else None,
        )

    def get_settlement(self, settlement_id: str) -> Settlement | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM settlements WHERE id = ?", (settlement_id,)).fetchone()
        return self._row_to_settlement(row) if row else None

    def open_settlements(self, today: date | None = None) -> list[Settlement]:
        today = today or date.today()
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM settlements WHERE deadline IS NULL OR deadline >= ? ORDER BY deadline",
                (today.isoformat(),),
            ).fetchall()
        return [self._row_to_settlement(r) for r in rows]

    # ---- payout accounts ---------------------------------------------
    def add_payout_account(self, label: str, method: str, handle: str) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO payout_accounts (label, method, handle, created_at) VALUES (?, ?, ?, ?)",
                (label, method, handle, _now()),
            )
            return int(cur.lastrowid)

    def payout_accounts(self) -> list[dict]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM payout_accounts ORDER BY id")]

    def get_payout_account(self, account_id: int) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM payout_accounts WHERE id = ?", (account_id,)).fetchone()
        return dict(row) if row else None

    # ---- claims ------------------------------------------------------
    def record_match(self, match: Match) -> int | None:
        """Create a claim for review, or refresh the evidence on one still awaiting review.

        Returns the claim id, or None if a claim already exists past the review stage.
        """
        evidence = json.dumps([_evidence_to_dict(e) for e in match.evidence])
        reasons = json.dumps(match.reasons)
        with self.connect() as conn:
            row = conn.execute("SELECT id, status FROM claims WHERE settlement_id = ?", (match.settlement_id,)).fetchone()
            if row is None:
                now = _now()
                cur = conn.execute(
                    """INSERT INTO claims (settlement_id, status, score, reasons, evidence, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (match.settlement_id, ClaimStatus.PENDING_REVIEW.value, match.score, reasons, evidence, now, now),
                )
                claim_id = int(cur.lastrowid)
                conn.execute(
                    "INSERT INTO claim_events (claim_id, from_status, to_status, note, at) VALUES (?, NULL, ?, ?, ?)",
                    (claim_id, ClaimStatus.PENDING_REVIEW.value, "match found", now),
                )
                return claim_id
            if row["status"] == ClaimStatus.PENDING_REVIEW.value:
                conn.execute(
                    "UPDATE claims SET score = ?, reasons = ?, evidence = ?, updated_at = ? WHERE id = ?",
                    (match.score, reasons, evidence, _now(), row["id"]),
                )
                return int(row["id"])
            return None

    def claims(self, status: ClaimStatus | None = None) -> list[dict]:
        sql = """SELECT c.*, s.title, s.url, s.claim_url, s.deadline, s.proof_required, s.payout_text,
                        s.eligibility_text, s.class_period_start, s.class_period_end
                 FROM claims c JOIN settlements s ON s.id = c.settlement_id"""
        params: tuple = ()
        if status:
            sql += " WHERE c.status = ?"
            params = (status.value,)
        sql += " ORDER BY s.deadline IS NULL, s.deadline, c.score DESC"
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["reasons"] = json.loads(d["reasons"])
            d["evidence"] = json.loads(d["evidence"])
            out.append(d)
        return out

    def get_claim(self, claim_id: int) -> dict | None:
        for c in self.claims():
            if c["id"] == claim_id:
                return c
        return None

    def transition(self, claim_id: int, to: ClaimStatus, note: str | None = None, **fields) -> None:
        allowed_fields = {"payout_account_id", "confirmed_at", "filed_at", "confirmation_number", "notes"}
        bad = set(fields) - allowed_fields
        if bad:
            raise ValueError(f"unknown claim fields: {bad}")
        with self.connect() as conn:
            row = conn.execute("SELECT status FROM claims WHERE id = ?", (claim_id,)).fetchone()
            if row is None:
                raise KeyError(claim_id)
            current = ClaimStatus(row["status"])
            if to not in ALLOWED_TRANSITIONS[current]:
                raise InvalidTransition(f"claim {claim_id}: {current.value} -> {to.value} is not allowed")
            now = _now()
            sets = ["status = ?", "updated_at = ?"] + [f"{k} = ?" for k in fields]
            conn.execute(
                f"UPDATE claims SET {', '.join(sets)} WHERE id = ?",
                (to.value, now, *fields.values(), claim_id),
            )
            conn.execute(
                "INSERT INTO claim_events (claim_id, from_status, to_status, note, at) VALUES (?, ?, ?, ?, ?)",
                (claim_id, current.value, to.value, note, now),
            )

    def claim_events(self, claim_id: int) -> list[dict]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM claim_events WHERE claim_id = ? ORDER BY id", (claim_id,))]


def _evidence_to_dict(e: Evidence) -> dict:
    return {
        "source": e.source, "external_id": e.external_id, "sender": e.sender, "subject": e.subject,
        "sent_at": e.sent_at.isoformat() if e.sent_at else None, "snippet": e.snippet, "link": e.link,
    }
