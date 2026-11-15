"""Open settlements from Top Class Actions (topclassactions.com).

Reads the "open lawsuit settlements" category feed, then each article for the summary box
(deadline, class period, proof required, payout, claim-form link).
"""
from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import feedparser
import httpx
from bs4 import BeautifulSoup

from ..models import Settlement
from ..textutil import keywords_from, parse_date, parse_dates

FEED_URL = "https://topclassactions.com/category/lawsuit-settlements/open-lawsuit-settlements/feed/"
SOURCE = "topclassactions"
USER_AGENT = "bagman-settlement-finder/0.1 (personal use)"

# Labels Top Class Actions uses in its settlement summary box.
LABELS = {
    "deadline": r"(?:claim form )?deadline",
    "class_period": r"class period",
    "eligibility": r"who'?s eligible|who is eligible|eligibility",
    "payout": r"potential award|award|payment",
    "proof": r"proof of purchase|proof",
    "case_name": r"case name",
    "settlement_website": r"settlement website",
}


def fetch_feed(client: httpx.Client, url: str = FEED_URL) -> list[dict]:
    resp = client.get(url)
    resp.raise_for_status()
    feed = feedparser.parse(resp.text)
    return [{"title": e.get("title", ""), "link": e.get("link", "")} for e in feed.entries]


def parse_article(html: str, url: str, title: str | None = None) -> Settlement:
    soup = BeautifulSoup(html, "html.parser")
    if not title:
        h1 = soup.find("h1")
        title = h1.get_text(" ", strip=True) if h1 else url
    body = soup.find("article") or soup.find(class_=re.compile("entry-content|post-content")) or soup
    lines = [ln.strip() for ln in body.get_text("\n").splitlines() if ln.strip()]
    fields = _labelled_fields(lines)

    period = parse_dates(fields.get("class_period", ""))
    proof_text = fields.get("proof", "").lower()
    proof_required = None
    if proof_text:
        proof_required = not proof_text.startswith(("no", "none", "n/a"))

    case_name = fields.get("case_name")
    description_el = body.find("p")
    return Settlement(
        id=f"tca:{_slug(url)}",
        title=title,
        url=url,
        source=SOURCE,
        claim_url=_claim_link(body, fields),
        deadline=parse_date(fields.get("deadline", "")),
        class_period_start=period[0] if period else None,
        class_period_end=period[1] if len(period) > 1 else None,
        proof_required=proof_required,
        payout_text=fields.get("payout"),
        eligibility_text=fields.get("eligibility"),
        description=description_el.get_text(" ", strip=True) if description_el else None,
        keywords=keywords_from(title, case_name),
        fetched_at=datetime.now(timezone.utc),
    )


def _labelled_fields(lines: list[str]) -> dict[str, str]:
    """Find "Label: value" lines, also handling the label and value on separate lines."""
    out: dict[str, str] = {}
    for i, line in enumerate(lines):
        for key, pattern in LABELS.items():
            if key in out:
                continue
            m = re.match(rf"^(?:{pattern})\s*:\s*(.*)$", line, re.IGNORECASE)
            if not m:
                continue
            value = m.group(1).strip()
            if not value and i + 1 < len(lines):
                value = lines[i + 1]
            out[key] = value
            break
    return out


def _claim_link(body, fields: dict[str, str]) -> str | None:
    for a in body.find_all("a", href=True):
        text = a.get_text(" ", strip=True).lower()
        host = urlparse(a["href"]).netloc.lower()
        if "topclassactions.com" in host or not host:
            continue
        if any(k in text for k in ("claim form", "file a claim", "submit a claim", "file claim", "file your claim")):
            return a["href"]
    site = fields.get("settlement_website", "")
    m = re.search(r"https?://\S+|\b[\w.-]+\.(?:com|net|org|info)\S*", site)
    if m:
        link = m.group(0).rstrip(".,)")
        return link if link.startswith("http") else f"https://{link}"
    return None


def _slug(url: str) -> str:
    path = urlparse(url).path.strip("/").split("/")
    slug = path[-1] if path and path[-1] else ""
    return slug or hashlib.sha1(url.encode()).hexdigest()[:12]


def fetch_open_settlements(limit: int | None = None, delay: float = 1.0) -> list[Settlement]:
    """Fetch the feed and parse each article. A short delay keeps the load on the site polite."""
    out: list[Settlement] = []
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True) as client:
        entries = fetch_feed(client)
        for entry in entries[:limit]:
            resp = client.get(entry["link"])
            if resp.status_code != 200:
                continue
            out.append(parse_article(resp.text, entry["link"], entry["title"]))
            time.sleep(delay)
    return out
