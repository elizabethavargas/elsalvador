"""
twitter_collector.py — El Salvador government tweet collection via twitterapi.io

REQUIREMENTS:
  pip install requests

AUTHENTICATION (one of):
  1) Script will prompt you to paste your key on first run
  2) Create a .env file:  TWITTERAPI_IO_KEY=your_key_here
  3) Export in shell:     export TWITTERAPI_IO_KEY=your_key_here
  Get a key at: https://twitterapi.io/dashboard

HOW IT WORKS:
  Uses the /twitter/user/last_tweets endpoint (confirmed working).
  Paginates backwards (newest → oldest) using the cursor field.
  Stops as soon as tweets fall before START_YEAR.
  Filters retweets and (optionally) quote-tweets client-side.

RESTART SAFETY:
  - Appends to tweets.csv after every page of results.
  - twitter_progress.json tracks which accounts are fully done.
  - Re-running resumes: skips completed accounts, re-paginates
    the current one (duplicate tweet IDs are skipped automatically).

OUTPUT: tweets.csv
  tweet_id | handle | account | date | year | month |
  text | likes | retweets | replies | quotes | views | lang
"""

import csv
import datetime
import json
import os
import time

import requests

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
START_YEAR  = 2015
END_YEAR    = 2025

INCLUDE_QUOTES = False  # True → keep quote-tweets too
INCLUDE_REPLIES = False # True → keep replies

API_DELAY_SEC  = 5.5   # free tier: 1 req / 5 s  (drop to 0.5 on paid)
MAX_RETRIES    = 5
RETRY_BACKOFF  = 15    # seconds to wait on 429, multiplied by attempt number

REQUEST_TIMEOUT = 30
OUTPUT_CSV      = "tweets.csv"
PROGRESS_FILE   = "twitter_progress.json"

BASE_URL       = "https://api.twitterapi.io"
LAST_TWEETS_EP = f"{BASE_URL}/twitter/user/last_tweets"

CSV_FIELDS = [
    "tweet_id", "handle", "account", "date", "year", "month",
    "text", "likes", "retweets", "replies", "quotes", "views", "lang",
]

# ─────────────────────────────────────────────
# EL SALVADOR GOVERNMENT ACCOUNTS
# ─────────────────────────────────────────────
ACCOUNTS = {
    # ── Executive ──────────────────────────────────────────────────────────
    "presidencia_sv":   "Presidencia SV",
    "nayibbukele":      "Nayib Bukele",
    "GobiernodeSV":     "Gobierno de El Salvador",

    # ── Legislature ────────────────────────────────────────────────────────
    "AsambleaSV":       "Asamblea Legislativa SV",

    # ── Ministries ─────────────────────────────────────────────────────────
    "MJSP_SV":          "Min. Justicia y Seguridad",
    "MHFiscal_SV":      "Min. de Hacienda",
    "MINSALsv":         "Min. de Salud",
    "MEDUCsv":          "Min. de Educación",
    "MOP_SV":           "Min. Obras Públicas",
    "MREEElSalvador":   "Min. Relaciones Exteriores",
    "MTPS_SV":          "Min. de Trabajo",
    "MAG_SV":           "Min. de Agricultura",

    # ── Security / Military ────────────────────────────────────────────────
    "PNCElSalvador":    "Policía Nacional Civil",
    "FAES_SV":          "Fuerzas Armadas SV",

    # ── Justice / Oversight ───────────────────────────────────────────────
    "FGR_SV":           "Fiscalía General",
    "CSJ_SV":           "Corte Suprema de Justicia",
    "TSEElSalvador":    "Tribunal Supremo Electoral",
    "PDDH_SV":          "Procuraduría DDHH",

    # ── Economic / Other ──────────────────────────────────────────────────
    "BCR_SV":           "Banco Central de Reserva",
    "CEPA_sv":          "CEPA",
}


# ─────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────
def _load_env_file(path):
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except FileNotFoundError:
        pass


def get_headers():
    _load_env_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    api_key = os.environ.get("TWITTERAPI_IO_KEY", "").strip()
    if not api_key:
        print("\nNo API key found in environment or .env file.")
        print("Get your key at: https://twitterapi.io/dashboard")
        api_key = input("Paste your twitterapi.io API key: ").strip()
        if not api_key:
            raise EnvironmentError("No API key provided.")
        os.environ["TWITTERAPI_IO_KEY"] = api_key
    masked = api_key[:6] + "..." + api_key[-4:] if len(api_key) > 10 else "****"
    print(f"[auth] Key loaded: {masked}")
    # Use exact capitalisation confirmed working by user
    return {"X-API-Key": api_key}


# ─────────────────────────────────────────────
# CSV HELPERS
# ─────────────────────────────────────────────
def init_csv():
    if not os.path.exists(OUTPUT_CSV):
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=CSV_FIELDS).writeheader()
        print(f"[init] Created {OUTPUT_CSV}")


def load_existing_ids():
    if not os.path.exists(OUTPUT_CSV):
        return set()
    seen = set()
    with open(OUTPUT_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("tweet_id"):
                seen.add(row["tweet_id"])
    print(f"[resume] {len(seen):,} tweet IDs already in {OUTPUT_CSV}")
    return seen


def append_rows(rows):
    if not rows:
        return
    with open(OUTPUT_CSV, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=CSV_FIELDS).writerows(rows)


# ─────────────────────────────────────────────
# PROGRESS
# ─────────────────────────────────────────────
def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"done": []}


def mark_done(progress, handle):
    if handle not in progress["done"]:
        progress["done"].append(handle)
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=2)


# ─────────────────────────────────────────────
# API — fetch one page of a user's tweets
# ─────────────────────────────────────────────
def fetch_page(headers, handle, cursor=""):
    """
    GET /twitter/user/last_tweets
    Returns parsed JSON dict, or {} on unrecoverable error.
    """
    params = {
        "userName":      handle,
        "includeReplies": "true" if INCLUDE_REPLIES else "false",
    }
    if cursor:
        params["cursor"] = cursor

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(
                LAST_TWEETS_EP,
                headers=headers,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )
            if r.status_code == 429:
                wait = RETRY_BACKOFF * attempt
                print(f"\n    [429] rate limited — waiting {wait}s ...", flush=True)
                time.sleep(wait)
                continue
            if not r.ok:
                print(f"\n    [HTTP {r.status_code}] {r.text[:200]}")
                return {}
            return r.json()
        except Exception as exc:
            print(f"\n    [error] {exc}")
            return {}

    print(f"    [skip] gave up after {MAX_RETRIES} retries")
    return {}


# ─────────────────────────────────────────────
# TWEET PARSING
# ─────────────────────────────────────────────
def parse_dt(raw):
    """Parse 'Mon Jan 01 00:00:00 +0000 2024' → datetime, or None."""
    try:
        return datetime.datetime.strptime(raw, "%a %b %d %H:%M:%S +0000 %Y")
    except (ValueError, TypeError):
        return None


def parse_tweet(raw, handle, account, seen_ids):
    tid = str(raw.get("id", ""))
    if not tid or tid in seen_ids:
        return None

    # Skip retweets
    if raw.get("retweeted_tweet"):
        return None

    # Skip quote-tweets if not wanted
    if not INCLUDE_QUOTES and raw.get("quoted_tweet"):
        return None

    seen_ids.add(tid)

    dt = parse_dt(raw.get("createdAt", ""))
    if dt:
        date_str  = dt.strftime("%Y-%m-%d %H:%M:%S")
        year_str  = str(dt.year)
        month_str = f"{dt.month:02d}"
    else:
        date_str = raw.get("createdAt", "")
        year_str = month_str = ""

    text = (raw.get("text") or "").replace("\r\n", " ").replace("\n", " ").replace("\r", " ")

    return {
        "tweet_id":  tid,
        "handle":    handle,
        "account":   account,
        "date":      date_str,
        "year":      year_str,
        "month":     month_str,
        "text":      text[:1000],
        "likes":     raw.get("likeCount",    0),
        "retweets":  raw.get("retweetCount", 0),
        "replies":   raw.get("replyCount",   0),
        "quotes":    raw.get("quoteCount",   0),
        "views":     raw.get("viewCount",    0),
        "lang":      raw.get("lang", ""),
    }


# ─────────────────────────────────────────────
# COLLECT ONE ACCOUNT
# ─────────────────────────────────────────────
def collect_account(headers, handle, account, seen_ids):
    """
    Paginate backwards through all of `handle`'s tweets.
    Stops once tweets fall before START_YEAR.
    Appends to CSV after every page.
    Returns total new tweets saved.
    """
    cursor    = ""
    page      = 0
    total_new = 0

    while True:
        page += 1
        data = fetch_page(headers, handle, cursor)

        if not data:
            print(f"    [!] empty response on page {page}, stopping")
            break

        tweets = data.get("tweets") or []
        if not tweets:
            print(f"    [!] no tweets on page {page}, stopping")
            break

        # Parse and date-filter this page
        page_rows = []
        oldest_dt = None

        for raw in tweets:
            dt = parse_dt(raw.get("createdAt", ""))
            if dt:
                if oldest_dt is None or dt < oldest_dt:
                    oldest_dt = dt

            # Date range filter
            if dt:
                if dt.year > END_YEAR:
                    continue   # newer than our range — skip but keep paginating
                if dt.year < START_YEAR:
                    continue   # older than our range — skip (will stop below)

            row = parse_tweet(raw, handle, account, seen_ids)
            if row:
                page_rows.append(row)

        append_rows(page_rows)
        total_new += len(page_rows)

        oldest_str = oldest_dt.strftime("%Y-%m-%d") if oldest_dt else "?"
        print(f"    page {page:3d} | +{len(page_rows):3d} tweets | "
              f"oldest on page: {oldest_str} | total new: {total_new:,}")

        # Stop if we've gone past the start of our date range
        if oldest_dt and oldest_dt.year < START_YEAR:
            print(f"    reached {oldest_dt.year} < {START_YEAR}, done with this account")
            break

        if not data.get("has_next_page"):
            break

        cursor = data.get("next_cursor", "")
        if not cursor:
            break

        time.sleep(API_DELAY_SEC)

    return total_new


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    init_csv()
    seen_ids = load_existing_ids()
    progress = load_progress()
    headers  = get_headers()
    done_set = set(progress.get("done", []))

    account_list = list(ACCOUNTS.items())
    print(f"\nCollecting tweets for {len(account_list)} accounts | "
          f"{START_YEAR}–{END_YEAR} | "
          f"retweets excluded | "
          f"quotes {'included' if INCLUDE_QUOTES else 'excluded'}")
    print(f"Output → {OUTPUT_CSV}   Progress → {PROGRESS_FILE}\n")

    for idx, (handle, account) in enumerate(account_list, 1):
        if handle in done_set:
            print(f"[{idx:2d}/{len(account_list)}] @{handle} — already done, skipping")
            continue

        print(f"\n{'='*70}")
        print(f"[{idx:2d}/{len(account_list)}] @{handle}  ({account})")
        print(f"{'='*70}")

        new_count = collect_account(headers, handle, account, seen_ids)

        mark_done(progress, handle)
        print(f"  ✓ @{handle} complete — {new_count:,} new tweets  "
              f"(running total: {len(seen_ids):,})")

        time.sleep(API_DELAY_SEC)

    print(f"\n{'='*70}")
    print(f"DONE.  {len(seen_ids):,} total tweets in {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
