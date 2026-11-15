# Bagman

Bagman finds open class action settlements you qualify for and files the claims for you.

1. **Finds settlements.** Each day it reads the open-settlement list on Top Class Actions: deadline,
   class period, whether proof is needed, payout and claim-form link.
2. **Checks your email.** It searches Gmail (read-only) for receipts, account emails, data-breach notices
   and settlement notices from each company, dated within the class period.
3. **Asks you once per claim.** Matches show up in a local dashboard with the evidence it found.
   You tick the eligibility statement and pick which payout account gets the money.
4. **Files it.** Confirmed claims are filled in and submitted in a headless browser. If a form has a
   CAPTCHA or fields it doesn't recognise, it stops and marks the claim **Needs you to finish**.

Claim forms are sworn statements ("under penalty of perjury"), so Bagman never files a claim you
haven't confirmed, and never queues one it found no evidence for.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[filer,dev]"
playwright install chromium   # skip if you already have Chromium; set BAGMAN_BROWSER_PATH instead
bagman init-profile           # then fill in profile.json (name, address, email, phone)
```

### Connect Gmail (one time, read-only)

1. In [Google Cloud Console](https://console.cloud.google.com/), create a project and enable the **Gmail API**.
2. Under **APIs & Services → OAuth consent screen**, choose *External*, and add your own Gmail address as a test user.
3. Under **Credentials**, create an **OAuth client ID** of type **Desktop app**, download the JSON and save it as `credentials.json` in this folder.
4. Run `bagman gmail-auth` and approve. On a machine with no browser, use `bagman gmail-auth --manual`.

The only permission requested is `gmail.readonly`: Bagman can't send, delete or change mail.
`credentials.json`, `token.json`, `profile.json` and `data/` are git-ignored.

### Add a payout account

Run `bagman serve`, open http://127.0.0.1:8000/payouts and add e.g. your PayPal email.
You choose the account per claim when you confirm it. Don't store bank account numbers here.

## Daily use

```bash
bagman daily     # fetch settlements, scan Gmail, file confirmed claims
bagman serve     # review and confirm matches at http://127.0.0.1:8000
```

Schedule `bagman daily` once a day, e.g. with cron:

```
17 7 * * * cd /path/to/BagmanGameV1 && .venv/bin/bagman daily >> data/daily.log 2>&1
```

Individual steps: `bagman sync`, `bagman scan`, `bagman file`.

### Dry run (on by default)

The filer starts in dry-run mode: it fills each form and saves a screenshot to `data/screenshots/`,
but doesn't press submit. Check a few screenshots, then turn real submission on with
`BAGMAN_FILER_DRY_RUN=false`.

## Settings (environment variables)

| Variable | Default | |
|---|---|---|
| `BAGMAN_MATCH_THRESHOLD` | `50` | Minimum match score (0–100) before a claim is queued for review |
| `BAGMAN_FILER_DRY_RUN` | `true` | Fill forms without submitting |
| `BAGMAN_BROWSER_PATH` | – | Path to a Chromium binary, if Playwright's isn't installed |
| `BAGMAN_DATA_DIR` | `data` | Database, screenshots |

## Layout

| Path | |
|---|---|
| `bagman/sources/topclassactions.py` | Settlement list and article parser |
| `bagman/sources/gmail.py` | Gmail search (read-only) |
| `bagman/sources/evidence.py` | Interface for adding more evidence sources later |
| `bagman/matcher.py` | Scores how well your emails match a settlement |
| `bagman/pipeline.py` | The daily job |
| `bagman/filer.py` | Fills and submits claim forms |
| `bagman/web.py`, `bagman/templates/` | Review dashboard |
| `bagman/db.py` | SQLite storage and the claim state machine |

Run the tests with `pytest`.

## Known limits

- Search terms per settlement are guessed from the case name and headline. Fix any bad ones on the
  dashboard; your edits are kept on later syncs.
- Every claim site is different. The filer recognises common fields (name, address, email, phone,
  PayPal/Venmo, the sworn-statement checkbox). Anything else goes to **Needs you to finish** with the claim
  form link.
- The dashboard has no login and listens only on 127.0.0.1. Don't expose it to the internet.
