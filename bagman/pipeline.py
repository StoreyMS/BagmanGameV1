"""The daily job: refresh settlements, search your evidence sources, queue matches for review."""
from __future__ import annotations

import logging
from datetime import date

from .db import Database
from .matcher import match_settlement
from .models import ClaimStatus, Settlement
from .sources.evidence import EvidenceSource

log = logging.getLogger(__name__)


def sync_settlements(db: Database, settlements: list[Settlement]) -> int:
    for s in settlements:
        db.upsert_settlement(s)
    return len(settlements)


def scan(db: Database, sources: list[EvidenceSource], threshold: int, today: date | None = None) -> list[int]:
    """Search each source for each open settlement. Returns ids of claims created or refreshed."""
    claim_ids = []
    for s in db.open_settlements(today):
        if not s.keywords:
            log.info("skipping %s: no keywords to search for (add some in the dashboard)", s.id)
            continue
        evidence = []
        for src in sources:
            try:
                evidence.extend(src.search(s.keywords, s.class_period_start, s.class_period_end))
            except Exception:  # one bad source/settlement shouldn't stop the run
                log.exception("search failed: source=%s settlement=%s", src.name, s.id)
        match = match_settlement(s, evidence)
        if match and match.score >= threshold:
            cid = db.record_match(match)
            if cid is not None:
                claim_ids.append(cid)
    return claim_ids


def expire_overdue(db: Database, today: date | None = None) -> int:
    today = today or date.today()
    n = 0
    for c in db.claims():
        if c["deadline"] and date.fromisoformat(c["deadline"]) < today and c["status"] in (
            ClaimStatus.PENDING_REVIEW.value, ClaimStatus.CONFIRMED.value, ClaimStatus.NEEDS_MANUAL.value
        ):
            db.transition(c["id"], ClaimStatus.EXPIRED, note="deadline passed")
            n += 1
    return n
