"""Score how strongly your evidence shows you're in a settlement's class."""
from __future__ import annotations

import re

from .models import Evidence, Match, Settlement

TRANSACTIONAL = re.compile(
    r"\b(receipt|order|purchase|invoice|payment|subscription|renewal|membership|shipped|shipping|"
    r"your account|welcome to|account created|confirm your|billing|statement|booking|reservation|"
    r"security incident|data breach|unauthori[sz]ed access)\b",
    re.IGNORECASE,
)
SETTLEMENT_NOTICE = re.compile(
    r"\b(notice of (proposed )?(class action )?settlement|class action settlement|legal notice|"
    r"you may be eligible|claim id|settlement administrator)\b",
    re.IGNORECASE,
)
MARKETING = re.compile(r"\b(\d+% off|sale ends|newsletter|deals? of the|limited time|promo code)\b", re.IGNORECASE)
# Emails from settlement news sites aren't evidence that you used the product.
IGNORED_SENDERS = re.compile(r"topclassactions|classaction\.org|claimdepot|openclassactions", re.IGNORECASE)


def score_evidence(e: Evidence, s: Settlement) -> tuple[int, list[str]]:
    kws = [k.lower() for k in s.keywords if k.strip()]
    sender, subject, snippet = e.sender.lower(), e.subject.lower(), e.snippet.lower()
    text = f"{subject} {snippet}"
    score, reasons = 0, []

    hit = next((k for k in kws if k in sender or k.replace(" ", "") in sender), None)
    if hit:
        score += 40
        reasons.append(f"email is from {hit}")
    elif any(k in subject for k in kws):
        score += 20
        reasons.append("company named in subject")
    elif any(k in snippet for k in kws):
        score += 10
        reasons.append("company named in message")
    else:
        return 0, []

    if SETTLEMENT_NOTICE.search(text):
        score += 50
        reasons.append("looks like a settlement notice addressed to you")
    elif TRANSACTIONAL.search(text):
        score += 25
        reasons.append("receipt / account / order email")
    elif MARKETING.search(text):
        score -= 15
        reasons.append("marketing email only")

    if e.sent_at and s.class_period_start and s.class_period_end:
        if s.class_period_start <= e.sent_at.date() <= s.class_period_end:
            score += 15
            reasons.append("dated inside the class period")
    return max(0, min(score, 100)), reasons


def match_settlement(s: Settlement, evidence: list[Evidence]) -> Match | None:
    scored = []
    for e in evidence:
        if IGNORED_SENDERS.search(e.sender):
            continue
        sc, why = score_evidence(e, s)
        if sc > 0:
            scored.append((sc, why, e))
    if not scored:
        return None
    scored.sort(key=lambda t: t[0], reverse=True)
    best_score, best_why, _ = scored[0]
    total = min(100, best_score + min(10, 2 * (len(scored) - 1)))
    reasons = list(best_why)
    if len(scored) > 1:
        reasons.append(f"{len(scored)} related emails")
    return Match(settlement_id=s.id, score=total, evidence=[e for _, _, e in scored[:10]], reasons=reasons)
