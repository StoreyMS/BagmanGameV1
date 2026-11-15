"""Fill in and submit claim forms in a headless browser — only for claims you confirmed.

Claim sites differ a lot, so this is cautious:
- It refuses to run on a claim that isn't CONFIRMED.
- If it sees a CAPTCHA, a login wall, or required fields it can't fill, it stops and marks the
  claim NEEDS_MANUAL so you can finish it yourself with the details shown in the dashboard.
- In dry-run mode (the default) it fills the form and saves a screenshot but never presses submit.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .db import Database
from .models import ClaimStatus

# Profile keys -> patterns matched against a field's label, name, id or placeholder.
FIELD_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("first_name", re.compile(r"first.?name|given.?name|fname", re.I)),
    ("last_name", re.compile(r"last.?name|surname|family.?name|lname", re.I)),
    ("full_name", re.compile(r"^(full.?)?name$|your name|claimant name", re.I)),
    ("email", re.compile(r"e-?mail", re.I)),
    ("phone", re.compile(r"phone|telephone|mobile", re.I)),
    ("address1", re.compile(r"address.?(line)?.?1|street|^address$|mailing address", re.I)),
    ("address2", re.compile(r"address.?(line)?.?2|apt|suite|unit", re.I)),
    ("city", re.compile(r"city|town", re.I)),
    ("state", re.compile(r"^state|province|region", re.I)),
    ("zip", re.compile(r"zip|postal", re.I)),
]
CAPTCHA = re.compile(r"recaptcha|hcaptcha|captcha|cf-turnstile", re.I)
ATTEST = re.compile(r"penalty of perjury|i (certify|attest|declare|affirm)|true and correct", re.I)
CONFIRMATION_NO = re.compile(r"(claim|confirmation|reference)\s*(id|number|#|no\.?)\s*[:#]?\s*([A-Z0-9-]{5,})", re.I)


@dataclass
class FileResult:
    status: ClaimStatus
    note: str
    confirmation_number: str | None = None
    screenshot: Path | None = None


def file_claim(db: Database, claim_id: int, profile: dict, out_dir: Path, dry_run: bool = True,
               browser_path: str | None = None) -> FileResult:
    claim = db.get_claim(claim_id)
    if claim is None:
        raise KeyError(claim_id)
    if claim["status"] != ClaimStatus.CONFIRMED.value:
        raise PermissionError(f"claim {claim_id} is {claim['status']}; only confirmed claims are filed")
    if not claim["payout_account_id"]:
        raise PermissionError(f"claim {claim_id} has no payout account chosen")
    if not claim["claim_url"]:
        result = FileResult(ClaimStatus.NEEDS_MANUAL, "no claim form link found; open the settlement page")
        db.transition(claim_id, result.status, note=result.note)
        return result

    payout = db.get_payout_account(claim["payout_account_id"])
    result = _run_browser(claim["claim_url"], profile, payout, out_dir / f"claim-{claim_id}.png", dry_run, browser_path)
    if result.status == ClaimStatus.CONFIRMED:  # dry run: nothing submitted, stay confirmed
        return result
    extra = {}
    if result.status == ClaimStatus.FILED:
        extra = {"filed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "confirmation_number": result.confirmation_number}
    db.transition(claim_id, result.status, note=result.note, **extra)
    return result


def _run_browser(url: str, profile: dict, payout: dict | None, shot: Path, dry_run: bool,
                 browser_path: str | None) -> FileResult:
    from playwright.sync_api import sync_playwright

    shot.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=browser_path) if browser_path else p.chromium.launch()
        page = browser.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            html = page.content()
            if CAPTCHA.search(html):
                page.screenshot(path=str(shot), full_page=True)
                return FileResult(ClaimStatus.NEEDS_MANUAL, "form has a CAPTCHA; finish it yourself", screenshot=shot)

            filled, missing = _fill_fields(page, profile, payout)
            page.screenshot(path=str(shot), full_page=True)
            if missing:
                return FileResult(ClaimStatus.NEEDS_MANUAL,
                                  f"couldn't fill required fields: {', '.join(missing[:6])}", screenshot=shot)
            if not filled:
                return FileResult(ClaimStatus.NEEDS_MANUAL, "no form fields recognised on the claim page",
                                  screenshot=shot)
            if dry_run:
                return FileResult(ClaimStatus.CONFIRMED,
                                  f"dry run: filled {len(filled)} fields, did not submit", screenshot=shot)

            submit = page.locator("button[type=submit], input[type=submit], button:has-text('Submit')").first
            if submit.count() == 0:
                return FileResult(ClaimStatus.NEEDS_MANUAL, "no submit button found", screenshot=shot)
            submit.click()
            page.wait_for_load_state("networkidle", timeout=45_000)
            page.screenshot(path=str(shot), full_page=True)
            text = page.inner_text("body")
            m = CONFIRMATION_NO.search(text)
            if m or re.search(r"thank you|claim (has been )?(submitted|received)", text, re.I):
                return FileResult(ClaimStatus.FILED, "submitted", m.group(3) if m else None, shot)
            return FileResult(ClaimStatus.NEEDS_MANUAL, "submitted but no confirmation seen; check the page",
                              screenshot=shot)
        finally:
            browser.close()


def _describe(el) -> str:
    parts = [el.get_attribute(a) or "" for a in ("name", "id", "placeholder", "aria-label", "autocomplete")]
    el_id = el.get_attribute("id")
    if el_id:
        label = el.page.locator(f"label[for='{el_id}']")
        if label.count():
            parts.append(label.first.inner_text())
    return " ".join(parts)


def _fill_fields(page, profile: dict, payout: dict | None) -> tuple[list[str], list[str]]:
    values = dict(profile)
    if "full_name" not in values and values.get("first_name"):
        values["full_name"] = f"{values['first_name']} {values.get('last_name', '')}".strip()
    filled, missing = [], []
    for el in page.locator("input:not([type=hidden]):not([type=submit]):not([type=button]), select, textarea").all():
        if not el.is_visible():
            continue
        kind = (el.get_attribute("type") or "").lower()
        desc = _describe(el)
        if kind == "checkbox":
            # Tick the sworn-statement box: you confirmed eligibility in the dashboard before this ran.
            if ATTEST.search(desc) or ATTEST.search(_nearby_text(el)):
                el.check()
                filled.append("attestation")
            continue
        if kind == "radio":
            continue
        key = next((k for k, pat in FIELD_PATTERNS if pat.search(desc)), None)
        if key is None and payout and re.search(r"paypal|venmo|zelle|payment (email|handle)", desc, re.I):
            el.fill(payout["handle"])
            filled.append("payout")
            continue
        if key and values.get(key):
            tag = el.evaluate("e => e.tagName").lower()
            if tag == "select":
                try:
                    el.select_option(label=values[key])
                except Exception:
                    el.select_option(value=values[key])
            else:
                el.fill(values[key])
            filled.append(key)
        elif el.get_attribute("required") is not None and not el.input_value():
            missing.append(desc.strip() or "unlabelled field")
    return filled, missing


def _nearby_text(el) -> str:
    try:
        return el.evaluate("e => (e.closest('label, div, p') || e.parentElement).innerText || ''")
    except Exception:
        return ""
