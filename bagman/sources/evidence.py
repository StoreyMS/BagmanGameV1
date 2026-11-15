"""Evidence sources: places to look for proof you used a product (Gmail today; more later).

To add a source, write a class with `name` and `search(...)` and register it in `build_sources`.
"""
from __future__ import annotations

from datetime import date
from typing import Protocol

from ..models import Evidence


class EvidenceSource(Protocol):
    name: str

    def search(self, keywords: list[str], start: date | None, end: date | None, limit: int = 25) -> list[Evidence]:
        """Return items that mention any keyword, dated within [start, end] when given."""
        ...


class StaticSource:
    """In-memory source, used by tests and for trying the app without connecting an account."""

    name = "static"

    def __init__(self, items: list[Evidence]):
        self.items = items

    def search(self, keywords, start, end, limit=25):
        kws = [k.lower() for k in keywords]
        out = []
        for e in self.items:
            text = f"{e.sender} {e.subject} {e.snippet}".lower()
            if not any(k in text for k in kws):
                continue
            if e.sent_at and start and e.sent_at.date() < start:
                continue
            if e.sent_at and end and e.sent_at.date() > end:
                continue
            out.append(e)
        return out[:limit]
