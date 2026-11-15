from datetime import date

import pytest

from bagman.db import InvalidTransition
from bagman.matcher import match_settlement
from bagman.models import ClaimStatus
from bagman.pipeline import expire_overdue, scan
from bagman.sources.evidence import StaticSource

from .conftest import ev


def test_receipt_scores_high(acme):
    m = match_settlement(acme, [ev("Acme Widgets <billing@acmewidgets.com>", "Your receipt for order #123")])
    assert m.score >= 75
    assert "receipt / account / order email" in m.reasons


def test_settlement_notice_is_strongest(acme):
    m = match_settlement(acme, [ev("Settlement Administrator <info@acmesettlement.com>",
                                   "Legal Notice: Acme Widgets class action settlement")])
    assert m.score >= 70


def test_marketing_only_is_weak(acme):
    m = match_settlement(acme, [ev("Acme <news@acme.com>", "Weekly newsletter: 20% off widgets")])
    assert m.score < 50


def test_news_sites_ignored(acme):
    assert match_settlement(acme, [ev("Top Class Actions <news@topclassactions.com>", "Acme Widgets receipt")]) is None


def test_unrelated_ignored(acme):
    assert match_settlement(acme, [ev("Globex <a@globex.com>", "Your receipt")]) is None


def test_scan_queues_and_refreshes(db, acme):
    db.upsert_settlement(acme)
    src = StaticSource([ev("Acme Widgets <billing@acmewidgets.com>", "Your receipt"),
                        ev("Acme Widgets <billing@acmewidgets.com>", "Your receipt", when=(2015, 1, 1))])
    ids = scan(db, [src], threshold=50, today=date(2026, 1, 1))
    assert len(ids) == 1
    claim = db.get_claim(ids[0])
    assert claim["status"] == "pending_review"
    assert len(claim["evidence"]) == 1  # the 2015 email is outside the class period
    assert scan(db, [src], threshold=50, today=date(2026, 1, 1)) == ids  # refreshed, not duplicated


def test_confirmed_claims_not_overwritten(db, acme):
    db.upsert_settlement(acme)
    src = StaticSource([ev("Acme Widgets <billing@acmewidgets.com>", "Your receipt")])
    [cid] = scan(db, [src], threshold=50, today=date(2026, 1, 1))
    acct = db.add_payout_account("PayPal", "paypal", "me@example.com")
    db.transition(cid, ClaimStatus.CONFIRMED, payout_account_id=acct)
    assert scan(db, [src], threshold=50, today=date(2026, 1, 1)) == []
    assert db.get_claim(cid)["status"] == "confirmed"


def test_state_machine(db, acme):
    db.upsert_settlement(acme)
    [cid] = scan(db, [StaticSource([ev("Acme Widgets <b@acmewidgets.com>", "Your receipt")])], 50, date(2026, 1, 1))
    with pytest.raises(InvalidTransition):
        db.transition(cid, ClaimStatus.FILED)  # can't file without confirming
    with pytest.raises(InvalidTransition):
        db.transition(cid, ClaimStatus.PAID)


def test_expire(db, acme):
    db.upsert_settlement(acme)
    [cid] = scan(db, [StaticSource([ev("Acme Widgets <b@acmewidgets.com>", "Your receipt")])], 50, date(2026, 1, 1))
    assert expire_overdue(db, today=date(2027, 4, 1)) == 1
    assert db.get_claim(cid)["status"] == "expired"


def test_locked_keywords_survive_resync(db, acme):
    db.upsert_settlement(acme)
    db.set_keywords(acme.id, ["acmewidgets.com"])
    db.upsert_settlement(acme)
    assert db.get_settlement(acme.id).keywords == ["acmewidgets.com"]
