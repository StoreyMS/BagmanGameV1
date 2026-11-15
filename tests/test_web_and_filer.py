import os
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bagman.config import Settings
from bagman.filer import file_claim
from bagman.models import ClaimStatus
from bagman.pipeline import scan
from bagman.sources.evidence import StaticSource
from bagman.web import create_app

from .conftest import ev

FIX = Path(__file__).parent / "fixtures"
PROFILE = {"first_name": "Sam", "last_name": "Tester", "email": "sam@example.com", "zip": "27601"}


def _browser():
    for p in sorted(Path("/opt/pw-browsers").glob("chromium-*/chrome-linux*/chrome")):
        return str(p)
    return os.environ.get("BAGMAN_BROWSER_PATH")


def _claim(db, acme, claim_url=None):
    acme.claim_url = claim_url
    db.upsert_settlement(acme)
    [cid] = scan(db, [StaticSource([ev("Acme Widgets <b@acmewidgets.com>", "Your receipt")])], 50, date(2026, 1, 1))
    return cid


def test_confirm_requires_attestation_and_payout(db, acme, tmp_path):
    cid = _claim(db, acme)
    client = TestClient(create_app(Settings(data_dir=tmp_path), db))
    assert client.get("/").status_code == 200
    assert "Acme Widgets" in client.get(f"/claims/{cid}").text

    r = client.post(f"/claims/{cid}/confirm", data={"payout_account_id": 1})
    assert r.status_code == 400  # no attestation, no account
    client.post("/payouts", data={"label": "PayPal", "method": "paypal", "handle": "me@example.com"})
    r = client.post(f"/claims/{cid}/confirm", data={"payout_account_id": 1, "attest": "yes"}, follow_redirects=False)
    assert r.status_code == 303
    assert db.get_claim(cid)["status"] == "confirmed"


def test_filer_refuses_unconfirmed(db, acme, tmp_path):
    cid = _claim(db, acme, claim_url="https://example.com")
    with pytest.raises(PermissionError):
        file_claim(db, cid, PROFILE, tmp_path)


@pytest.mark.skipif(not _browser(), reason="no Chromium available")
@pytest.mark.parametrize("dry_run", [True, False])
def test_filer_fills_and_submits(db, acme, tmp_path, dry_run):
    cid = _claim(db, acme, claim_url=(FIX / "claim_form.html").as_uri())
    acct = db.add_payout_account("PayPal", "paypal", "me@example.com")
    db.transition(cid, ClaimStatus.CONFIRMED, payout_account_id=acct)
    r = file_claim(db, cid, PROFILE, tmp_path, dry_run=dry_run, browser_path=_browser())
    if dry_run:
        assert r.status == ClaimStatus.CONFIRMED and "did not submit" in r.note
        assert db.get_claim(cid)["status"] == "confirmed"
    else:
        assert r.status == ClaimStatus.FILED, r.note
        claim = db.get_claim(cid)
        assert claim["status"] == "filed" and claim["confirmation_number"] == "ACM-778812"


@pytest.mark.skipif(not _browser(), reason="no Chromium available")
def test_filer_stops_at_captcha(db, acme, tmp_path):
    cid = _claim(db, acme, claim_url=(FIX / "captcha_form.html").as_uri())
    acct = db.add_payout_account("PayPal", "paypal", "me@example.com")
    db.transition(cid, ClaimStatus.CONFIRMED, payout_account_id=acct)
    r = file_claim(db, cid, PROFILE, tmp_path, dry_run=False, browser_path=_browser())
    assert r.status == ClaimStatus.NEEDS_MANUAL and "CAPTCHA" in r.note
