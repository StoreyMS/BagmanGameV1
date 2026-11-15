"""Local dashboard for reviewing matches, confirming claims and choosing payout accounts.

It has no login, so it only listens on 127.0.0.1 by default. Don't expose it to the internet.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .config import Settings, get_settings
from .db import Database, InvalidTransition
from .models import ClaimStatus

PAYOUT_METHODS = ["paypal", "venmo", "zelle", "check", "direct_deposit", "other"]


def create_app(settings: Settings | None = None, db: Database | None = None) -> FastAPI:
    settings = settings or get_settings()
    db = db or Database(settings.db_path)
    app = FastAPI(title="Bagman")
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

    def back(url: str) -> RedirectResponse:
        return RedirectResponse(url, status_code=303)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        claims = db.claims()
        groups = {s: [c for c in claims if c["status"] == s.value] for s in ClaimStatus}
        return templates.TemplateResponse(request, "index.html", {"groups": groups, "Status": ClaimStatus})

    @app.get("/claims/{claim_id}", response_class=HTMLResponse)
    def claim_detail(request: Request, claim_id: int):
        claim = db.get_claim(claim_id)
        if not claim:
            raise HTTPException(404)
        settlement = db.get_settlement(claim["settlement_id"])
        return templates.TemplateResponse(request, "claim.html", {
            "c": claim, "s": settlement, "accounts": db.payout_accounts(),
            "events": db.claim_events(claim_id), "Status": ClaimStatus,
            "payout": db.get_payout_account(claim["payout_account_id"]) if claim["payout_account_id"] else None,
            "dry_run": settings.filer_dry_run,
        })

    @app.post("/claims/{claim_id}/confirm")
    def confirm(claim_id: int, payout_account_id: int = Form(...), attest: str = Form("")):
        if attest != "yes":
            raise HTTPException(400, "You must confirm the eligibility statement is true.")
        if not db.get_payout_account(payout_account_id):
            raise HTTPException(400, "Choose a payout account.")
        from datetime import datetime, timezone
        _transition(claim_id, ClaimStatus.CONFIRMED, "you confirmed eligibility",
                    payout_account_id=payout_account_id,
                    confirmed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        return back(f"/claims/{claim_id}")

    @app.post("/claims/{claim_id}/dismiss")
    def dismiss(claim_id: int):
        _transition(claim_id, ClaimStatus.DISMISSED, "you dismissed it")
        return back("/")

    @app.post("/claims/{claim_id}/reopen")
    def reopen(claim_id: int):
        _transition(claim_id, ClaimStatus.PENDING_REVIEW, "reopened")
        return back(f"/claims/{claim_id}")

    @app.post("/claims/{claim_id}/file")
    def file(claim_id: int):
        from .filer import file_claim
        try:
            file_claim(db, claim_id, settings.load_profile(), settings.data_dir / "screenshots",
                       dry_run=settings.filer_dry_run, browser_path=settings.browser_path)
        except PermissionError as e:
            raise HTTPException(400, str(e))
        return back(f"/claims/{claim_id}")

    @app.post("/claims/{claim_id}/mark-filed")
    def mark_filed(claim_id: int, confirmation_number: str = Form("")):
        from datetime import datetime, timezone
        _transition(claim_id, ClaimStatus.FILED, "you filed it yourself",
                    filed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    confirmation_number=confirmation_number or None)
        return back(f"/claims/{claim_id}")

    @app.post("/claims/{claim_id}/mark-paid")
    def mark_paid(claim_id: int, notes: str = Form("")):
        _transition(claim_id, ClaimStatus.PAID, "payout received", notes=notes or None)
        return back(f"/claims/{claim_id}")

    @app.post("/settlements/{settlement_id}/keywords")
    def keywords(settlement_id: str, keywords: str = Form(...), claim_id: int | None = Form(None)):
        db.set_keywords(settlement_id, [k.strip() for k in keywords.split(",") if k.strip()])
        return back(f"/claims/{claim_id}" if claim_id else "/settlements")

    @app.get("/settlements", response_class=HTMLResponse)
    def settlements(request: Request):
        return templates.TemplateResponse(request, "settlements.html", {"settlements": db.open_settlements()})

    @app.get("/payouts", response_class=HTMLResponse)
    def payouts(request: Request):
        return templates.TemplateResponse(request, "payouts.html",
                                          {"accounts": db.payout_accounts(), "methods": PAYOUT_METHODS})

    @app.post("/payouts")
    def add_payout(label: str = Form(...), method: str = Form(...), handle: str = Form(...)):
        if method not in PAYOUT_METHODS:
            raise HTTPException(400, "unknown payout method")
        db.add_payout_account(label.strip(), method, handle.strip())
        return back("/payouts")

    def _transition(claim_id: int, to: ClaimStatus, note: str, **fields):
        try:
            db.transition(claim_id, to, note=note, **fields)
        except KeyError:
            raise HTTPException(404)
        except InvalidTransition as e:
            raise HTTPException(409, str(e))

    return app
