from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum


class ClaimStatus(str, Enum):
    PENDING_REVIEW = "pending_review"  # Found a match; waiting for you to confirm.
    CONFIRMED = "confirmed"            # You confirmed eligibility and picked a payout account.
    FILED = "filed"                    # Submitted to the claims administrator.
    NEEDS_MANUAL = "needs_manual"      # Form needs you (CAPTCHA, unusual fields). Data is pre-filled for you.
    DISMISSED = "dismissed"            # You said you're not eligible / not interested.
    EXPIRED = "expired"                # Deadline passed before filing.
    PAID = "paid"                      # Payout received.


# Transitions allowed by the state machine. Filing is only possible from CONFIRMED.
ALLOWED_TRANSITIONS: dict[ClaimStatus, set[ClaimStatus]] = {
    ClaimStatus.PENDING_REVIEW: {ClaimStatus.CONFIRMED, ClaimStatus.DISMISSED, ClaimStatus.EXPIRED},
    ClaimStatus.CONFIRMED: {ClaimStatus.FILED, ClaimStatus.NEEDS_MANUAL, ClaimStatus.PENDING_REVIEW, ClaimStatus.EXPIRED},
    ClaimStatus.NEEDS_MANUAL: {ClaimStatus.FILED, ClaimStatus.DISMISSED, ClaimStatus.EXPIRED},
    ClaimStatus.FILED: {ClaimStatus.PAID},
    ClaimStatus.DISMISSED: {ClaimStatus.PENDING_REVIEW},
    ClaimStatus.EXPIRED: set(),
    ClaimStatus.PAID: set(),
}


@dataclass
class Settlement:
    id: str                      # Stable slug, e.g. "tca:acme-data-breach-settlement"
    title: str
    url: str                     # Article / listing URL
    source: str                  # e.g. "topclassactions"
    claim_url: str | None = None
    deadline: date | None = None
    class_period_start: date | None = None
    class_period_end: date | None = None
    proof_required: bool | None = None
    payout_text: str | None = None
    eligibility_text: str | None = None
    description: str | None = None
    keywords: list[str] = field(default_factory=list)  # Company / product names to search evidence for
    fetched_at: datetime | None = None


@dataclass
class Evidence:
    source: str          # e.g. "gmail"
    external_id: str     # e.g. Gmail message id
    sender: str
    subject: str
    sent_at: datetime | None
    snippet: str = ""
    link: str | None = None


@dataclass
class Match:
    settlement_id: str
    score: int
    evidence: list[Evidence]
    reasons: list[str]
