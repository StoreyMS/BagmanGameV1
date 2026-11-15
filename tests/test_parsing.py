from datetime import date
from pathlib import Path

from bagman.sources.gmail import build_query
from bagman.sources.topclassactions import parse_article
from bagman.textutil import keywords_from, parse_date, parse_dates

FIX = Path(__file__).parent / "fixtures"


def test_dates():
    assert parse_date("Deadline: 03/15/27") == date(2027, 3, 15)
    assert parse_date("by December 5, 2026.") == date(2026, 12, 5)
    assert parse_date("Sept. 9, 2025") == date(2025, 9, 9)
    assert parse_dates("between Jan. 1, 2019 and Dec. 31, 2023") == [date(2019, 1, 1), date(2023, 12, 31)]
    assert parse_date("no date here") is None


def test_keywords():
    assert keywords_from("Acme Widgets $4.5M class action settlement", "Smith v. Acme Widgets Inc.") == ["Acme Widgets"]
    assert keywords_from("Data breach settlement", "In re: Globex Corp. Data Security Incident Litigation") == ["Globex"]
    assert keywords_from("Initech Bank $2M overdraft fee settlement", None) == ["Initech Bank"]


def test_parse_article():
    s = parse_article((FIX / "tca_article.html").read_text(), "https://topclassactions.com/x/acme-widgets-settlement/")
    assert s.id == "tca:acme-widgets-settlement"
    assert s.title.startswith("Acme Widgets")
    assert s.deadline == date(2027, 3, 15)
    assert (s.class_period_start, s.class_period_end) == (date(2019, 1, 1), date(2023, 12, 31))
    assert s.proof_required is False
    assert s.payout_text == "Up to $75"
    assert s.claim_url == "https://www.acmewidgetssettlement.com/claim"
    assert s.keywords[0] == "Acme Widgets"


def test_gmail_query():
    q = build_query(["Acme Widgets", "acme.com"], date(2019, 1, 1), date(2023, 12, 31))
    assert q == '("Acme Widgets" OR acme.com) after:2019/01/01 before:2024/01/01'
