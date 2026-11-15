"""Gmail evidence source. Read-only: the app can search and read message headers, nothing else."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from ..models import Evidence

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def build_query(keywords: list[str], start: date | None, end: date | None) -> str:
    terms = [f'"{k}"' if " " in k else k for k in keywords if k.strip()]
    if not terms:
        raise ValueError("no keywords to search for")
    q = "(" + " OR ".join(terms) + ")"
    if start:
        q += f" after:{start:%Y/%m/%d}"
    if end:
        # Gmail's before: is exclusive, so add a day to include the last day of the class period.
        q += f" before:{end + timedelta(days=1):%Y/%m/%d}"
    return q


def authorize(credentials_path: Path, token_path: Path, manual: bool = False):
    """Run Google's sign-in once and save the token. Returns Credentials.

    manual=True is for machines without a browser: open the printed link anywhere, approve,
    then paste the full address your browser lands on (it will fail to load; that's expected).
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not credentials_path.exists():
            raise FileNotFoundError(
                f"{credentials_path} not found. Create an OAuth client (Desktop app) in Google Cloud "
                "Console with the Gmail API enabled and download its JSON here. See README."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
        if manual:
            flow.redirect_uri = "http://localhost:8765/"
            url, _ = flow.authorization_url(access_type="offline", prompt="consent")
            print("Open this link, approve read-only Gmail access, then paste the address you land on:\n")
            print(url)
            redirected = input("\nPaste the full address here: ").strip()
            flow.fetch_token(authorization_response=redirected.replace("http://", "https://", 1))
            creds = flow.credentials
        else:
            creds = flow.run_local_server(port=0)
    token_path.write_text(creds.to_json())
    token_path.chmod(0o600)
    return creds


class GmailSource:
    name = "gmail"

    def __init__(self, credentials_path: Path, token_path: Path):
        from googleapiclient.discovery import build

        creds = authorize(credentials_path, token_path)
        self.service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    def search(self, keywords: list[str], start: date | None, end: date | None, limit: int = 25) -> list[Evidence]:
        q = build_query(keywords, start, end)
        resp = self.service.users().messages().list(userId="me", q=q, maxResults=limit).execute()
        out: list[Evidence] = []
        for m in resp.get("messages", []):
            msg = self.service.users().messages().get(
                userId="me", id=m["id"], format="metadata", metadataHeaders=["From", "Subject", "Date"]
            ).execute()
            headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
            out.append(Evidence(
                source=self.name,
                external_id=m["id"],
                sender=headers.get("from", ""),
                subject=headers.get("subject", ""),
                sent_at=_parse_date(headers.get("date"), msg.get("internalDate")),
                snippet=msg.get("snippet", ""),
                link=f"https://mail.google.com/mail/u/0/#all/{m['id']}",
            ))
        return out


def _parse_date(header: str | None, internal_ms: str | None) -> datetime | None:
    if internal_ms:
        return datetime.fromtimestamp(int(internal_ms) / 1000, tz=timezone.utc)
    if header:
        try:
            return parsedate_to_datetime(header)
        except (TypeError, ValueError):
            return None
    return None
