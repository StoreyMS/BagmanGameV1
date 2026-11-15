"""Small parsing helpers shared by the settlement sources."""
from __future__ import annotations

import re
from datetime import date, datetime

MONTHS = {
    m: i for i, names in enumerate(
        [("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",),
         ("jun", "june"), ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"),
         ("oct", "october"), ("nov", "november"), ("dec", "december")], start=1)
    for m in names
}

_MONTH_NAME = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
DATE_RE = re.compile(
    rf"(?P<numeric>\b\d{{1,2}}/\d{{1,2}}/\d{{2,4}}\b)"
    rf"|(?P<named>\b{_MONTH_NAME}\s+\d{{1,2}},?\s+\d{{4}}\b)"
    rf"|(?P<monthyear>\b{_MONTH_NAME}\s+\d{{4}}\b)",
    re.IGNORECASE,
)


def parse_date(text: str) -> date | None:
    m = DATE_RE.search(text or "")
    return _to_date(m) if m else None


def parse_dates(text: str) -> list[date]:
    return [d for m in DATE_RE.finditer(text or "") if (d := _to_date(m))]


def _to_date(m: re.Match) -> date | None:
    try:
        if m.group("numeric"):
            mo, d, y = (int(x) for x in m.group("numeric").split("/"))
            if y < 100:
                y += 2000
            return date(y, mo, d)
        if m.group("named"):
            parts = re.split(r"[\s,]+", m.group("named").strip())
            mo = MONTHS[parts[0].rstrip(".").lower()]
            return date(int(parts[2]), mo, int(parts[1]))
        if m.group("monthyear"):
            parts = m.group("monthyear").split()
            return date(int(parts[1]), MONTHS[parts[0].rstrip(".").lower()], 1)
    except (KeyError, ValueError, IndexError):
        return None
    return None


_CORP_SUFFIX = re.compile(
    r",?\s+\b(inc|incorporated|corp|corporation|co|company|llc|l\.l\.c|ltd|limited|plc|lp|l\.p|n\.a|na|holdings|group)\b\.?",
    re.IGNORECASE,
)
_STOP = {
    "the", "a", "an", "and", "of", "in", "re", "for", "to", "settlement", "class", "action", "lawsuit",
    "data", "breach", "privacy", "litigation", "million", "billion", "consumers", "customers", "users",
    "claim", "claims", "open", "new", "proposed", "agrees", "pay", "pays", "resolves", "over", "fees",
    "et", "al", "v", "vs", "who", "with", "from", "by", "on", "deal", "case", "faces", "ends",
}


def clean_company(name: str) -> str:
    name = re.sub(r"\(.*?\)", "", name)
    name = re.sub(r"\bet al\.?", "", name, flags=re.IGNORECASE)
    prev = None
    while prev != name:
        prev = name
        name = _CORP_SUFFIX.sub("", name).strip(" ,.;:")
    name = re.sub(r"^(the)\s+", "", name, flags=re.IGNORECASE)
    return name.strip()


def keywords_from(title: str, case_name: str | None) -> list[str]:
    """Guess the company/brand names to search your email for.

    These are a starting point; you can edit them per settlement in the dashboard.
    """
    out: list[str] = []
    if case_name:
        cn = re.sub(r"^\s*in\s+re:?\s*", "", case_name, flags=re.IGNORECASE)
        if re.search(r"\s+v[s]?\.?\s+", cn):
            defendant = re.split(r"\s+v[s]?\.?\s+", cn, maxsplit=1)[1]
        else:
            defendant = re.split(r"\b(data|consumer|privacy|security|litigation|marketing|sales|products)\b",
                                 cn, maxsplit=1, flags=re.IGNORECASE)[0]
        defendant = clean_company(defendant.split(",")[0] if " v" in cn else defendant)
        if defendant and defendant.lower() not in _STOP:
            out.append(defendant)
    # Leading run of capitalised words in the headline, e.g. "Acme Bank $5M settlement ..."
    lead = re.match(r"^((?:[A-Z0-9][\w&'.\-]*\s+){0,3}[A-Z0-9][\w&'.\-]*)", title.strip())
    if lead:
        words = [w for w in lead.group(1).split() if w.lower().strip(".'") not in _STOP and not w.startswith("$")]
        candidate = clean_company(" ".join(words))
        if candidate and candidate.lower() not in {k.lower() for k in out} and not candidate[0].isdigit():
            out.append(candidate)
    return out
