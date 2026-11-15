"""Command line entry point: `bagman <command>`."""
from __future__ import annotations

import argparse
import json
import logging
import sys

from .config import get_settings
from .db import Database
from .models import ClaimStatus

log = logging.getLogger("bagman")


def _sources(settings, use_gmail: bool = True):
    sources = []
    if use_gmail:
        from .sources.gmail import GmailSource
        sources.append(GmailSource(settings.google_credentials, settings.google_token))
    return sources


def cmd_sync(args, settings, db):
    from .pipeline import sync_settlements
    from .sources.topclassactions import fetch_open_settlements
    n = sync_settlements(db, fetch_open_settlements(limit=args.limit))
    print(f"Saved {n} open settlements.")


def cmd_scan(args, settings, db):
    from .pipeline import expire_overdue, scan
    expired = expire_overdue(db)
    ids = scan(db, _sources(settings), settings.match_threshold)
    print(f"{len(ids)} claims waiting for review; {expired} expired.")


def cmd_file(args, settings, db):
    from .filer import file_claim
    for c in db.claims(ClaimStatus.CONFIRMED):
        r = file_claim(db, c["id"], settings.load_profile(), settings.data_dir / "screenshots",
                       dry_run=settings.filer_dry_run, browser_path=settings.browser_path)
        print(f"#{c['id']} {c['title']}: {r.status.value} ({r.note})")


def cmd_daily(args, settings, db):
    """What the scheduler runs once a day."""
    for step in (cmd_sync, cmd_scan, cmd_file):
        try:
            step(args, settings, db)
        except Exception:
            log.exception("%s failed; continuing", step.__name__)
    pending = db.claims(ClaimStatus.PENDING_REVIEW)
    if pending:
        print(f"\n{len(pending)} claim(s) need your confirmation. Open the dashboard: bagman serve")


def cmd_gmail_auth(args, settings, db):
    from .sources.gmail import authorize
    authorize(settings.google_credentials, settings.google_token, manual=args.manual)
    print(f"Gmail connected (read-only). Token saved to {settings.google_token}.")


def cmd_serve(args, settings, db):
    import uvicorn
    from .web import create_app
    uvicorn.run(create_app(settings, db), host=args.host, port=args.port)


def cmd_profile(args, settings, db):
    if settings.profile_path.exists():
        print(f"{settings.profile_path} already exists; edit it directly.")
        return
    template = {k: "" for k in ("first_name", "last_name", "email", "phone",
                                "address1", "address2", "city", "state", "zip")}
    settings.profile_path.write_text(json.dumps(template, indent=2) + "\n")
    settings.profile_path.chmod(0o600)
    print(f"Wrote {settings.profile_path}. Fill in the details claim forms ask for.")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="bagman", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync", help="fetch open settlements")
    s.add_argument("--limit", type=int, default=None)
    sub.add_parser("scan", help="search Gmail for evidence and queue matches for review")
    sub.add_parser("file", help="file every confirmed claim")
    d = sub.add_parser("daily", help="sync + scan + file; run this once a day")
    d.add_argument("--limit", type=int, default=None)
    g = sub.add_parser("gmail-auth", help="connect Gmail (read-only)")
    g.add_argument("--manual", action="store_true", help="for machines without a browser")
    v = sub.add_parser("serve", help="open the review dashboard")
    v.add_argument("--host", default="127.0.0.1")
    v.add_argument("--port", type=int, default=8000)
    sub.add_parser("init-profile", help="create profile.json for your claim-form details")
    args = p.parse_args(argv)

    settings = get_settings()
    db = Database(settings.db_path)
    handlers = {"sync": cmd_sync, "scan": cmd_scan, "file": cmd_file, "daily": cmd_daily,
                "gmail-auth": cmd_gmail_auth, "serve": cmd_serve, "init-profile": cmd_profile}
    handlers[args.cmd](args, settings, db)
    return 0


if __name__ == "__main__":
    sys.exit(main())
