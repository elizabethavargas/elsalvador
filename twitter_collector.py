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
  Uses /twitter/tweet/advanced_search with daily since_time/until_time windows
  (Unix timestamps). Cursor pagination is broken platform-wide as of March 2026,
  so we avoid it entirely — one request per day, no pagination.

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

# Per-account override: earliest year to collect (inclusive).
# Accounts not listed here use START_YEAR.
ACCOUNT_START_YEARS = {
    "nayibbukele": 2019,   # politically prominent from ~2019 election
}

INCLUDE_QUOTES = False  # True → keep quote-tweets too
INCLUDE_REPLIES = False # True → keep replies

API_DELAY_SEC  = 0.5   # paid tier
MAX_RETRIES    = 5
RETRY_BACKOFF  = 15    # seconds to wait on 429, multiplied by attempt number

REQUEST_TIMEOUT = 30
OUTPUT_CSV      = "tweets.csv"
PROGRESS_FILE   = "twitter_progress.json"

BASE_URL   = "https://api.twitterapi.io"
SEARCH_EP  = f"{BASE_URL}/twitter/tweet/advanced_search"

CSV_FIELDS = [
    "tweet_id", "handle", "account", "date", "year", "month",
    "text", "likes", "retweets", "replies", "quotes", "views", "lang",
]

# ─────────────────────────────────────────────
# EL SALVADOR GOVERNMENT ACCOUNTS
# ─────────────────────────────────────────────
ACCOUNTS = {
    # ── Executive ──────────────────────────────────────────────────────────
    "PresidenciaSV":    "Casa Presidencial",
    "Gobierno_SV":      "Gobierno de El Salvador",
    "nayibbukele":      "Nayib Bukele",          # 2019+ per ACCOUNT_START_YEARS

    # ── Legislature ────────────────────────────────────────────────────────
    "AsambleaSV":       "Asamblea Legislativa",

    # ── Justice / Prosecution ─────────────────────────────────────────────
    "FGR_SV":           "Fiscalía General de la República",
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
            data = json.load(f)
        if "completed_months" not in data:
            data["completed_months"] = {}
        return data
    return {"done": [], "completed_months": {}}


def mark_month_done(progress, handle, year, month):
    """Record that a specific year-month has been fully fetched and saved."""
    key = f"{year}-{month:02d}"
    progress["completed_months"].setdefault(handle, [])
    if key not in progress["completed_months"][handle]:
        progress["completed_months"][handle].append(key)
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=2)


def mark_done(progress, handle):
    if handle not in progress["done"]:
        progress["done"].append(handle)
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=2)


# ─────────────────────────────────────────────
# API — fetch one page of a user's tweets
# ─────────────────────────────────────────────
def _get(headers, url, params):
    """Raw GET with 429 retry. Returns response object or None."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
            if r.status_code == 429:
                wait = RETRY_BACKOFF * attempt
                print(f"\n    [429] rate limited — waiting {wait}s (attempt {attempt}) ...", flush=True)
                time.sleep(wait)
                continue
            if not r.ok:
                print(f"\n    [HTTP {r.status_code}] {r.text[:300]}")
                return None
            return r
        except Exception as exc:
            print(f"\n    [error] {exc}")
            return None
    print(f"    [skip] gave up after {MAX_RETRIES} retries")
    return None


def fetch_window(headers, handle, since_ts, until_ts):
    """
    Fetch one day's worth of tweets via advanced_search using Unix timestamps.
    No pagination — cursor-based pagination is broken platform-wide (March 2026).
    Returns list of raw tweet dicts.
    """
    query = f"from:{handle} since_time:{since_ts} until_time:{until_ts} -filter:retweets -filter:quote"
    params = {"query": query, "queryType": "Latest"}

    r = _get(headers, SEARCH_EP, params)
    if not r:
        return []
    data = r.json()
    return data.get("tweets") or []


# ─────────────────────────────────────────────
# TWEET PARSING-
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

    seen_ids.add(tid)

    text = (raw.get("text") or "").replace("\r\n", " ").replace("\n", " ").replace("\r", " ")

    # Client-side backstop in case API filter leaks anything through
    if text.startswith("RT @") or raw.get("retweeted_status") or raw.get("retweetedTweet"):
        return None

    dt = parse_dt(raw.get("createdAt", ""))
    if dt:
        date_str  = dt.strftime("%Y-%m-%d %H:%M:%S")
        year_str  = str(dt.year)
        month_str = f"{dt.month:02d}"
    else:
        date_str = raw.get("createdAt", "")
        year_str = month_str = ""

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
def iter_days(month_start, month_end):
    """Yield (day_start, day_end) pairs covering a calendar month."""
    cur = month_start
    while cur < month_end:
        nxt = cur + datetime.timedelta(days=1)
        yield cur, nxt
        cur = nxt


def collect_account(headers, handle, account, seen_ids, progress):
    """
    Adaptive time-window collection (newest → oldest).

    1. Query one calendar month at a time.
    2. If the month returns a full page (20 tweets), drill into daily windows
       for that month — there are likely more tweets than one page can hold.
    3. If the month returns < 20, we got everything; no daily breakdown needed.

    Cost: quiet accounts ~12 req/year. Active months cost an extra ~30 req.
    Completed months are checkpointed so interrupted runs resume cleanly.
    """
    tz         = datetime.timezone.utc
    MAX_PAGE   = 20          # advanced_search returns at most 20 per call
    total_new  = 0
    acct_start = ACCOUNT_START_YEARS.get(handle, START_YEAR)
    done_months = set(progress["completed_months"].get(handle, []))

    # Walk months newest → oldest
    year  = END_YEAR
    month = 12
    while (year, month) >= (acct_start, 1):
        # Build month window
        mo_start = datetime.datetime(year, month, 1, tzinfo=tz)
        if month == 12:
            mo_end = datetime.datetime(year + 1, 1, 1, tzinfo=tz)
        else:
            mo_end = datetime.datetime(year, month + 1, 1, tzinfo=tz)

        mo_key = mo_start.strftime("%Y-%m")

        # Skip months already checkpointed
        if mo_key in done_months:
            print(f"    {mo_key}    | (already done, skipping)")
            month -= 1
            if month == 0:
                month = 12
                year -= 1
            continue

        since_ts = int(mo_start.timestamp())
        until_ts = int(mo_end.timestamp())

        mo_tweets = fetch_window(headers, handle, since_ts, until_ts)
        time.sleep(API_DELAY_SEC)

        if not mo_tweets:
            print(f"    {mo_key}    | (empty)")
            mark_month_done(progress, handle, year, month)
            done_months.add(mo_key)
            month -= 1
            if month == 0:
                month = 12
                year -= 1
            continue

        if len(mo_tweets) < MAX_PAGE:
            # Got everything for the month in one shot
            rows = [r for raw in mo_tweets
                    for r in [parse_tweet(raw, handle, account, seen_ids)] if r]
            if rows:
                append_rows(rows)
                total_new += len(rows)
            print(f"    {mo_key}    | "
                  f"+{len(rows):3d} tweets ({len(mo_tweets)} raw, 1 req) | total: {total_new:,}")
        else:
            # Full page returned — drill into days to avoid missing tweets
            mo_new = 0
            mo_req = 0
            for d_start, d_end in iter_days(mo_start, mo_end):
                d_tweets = fetch_window(headers, handle,
                                        int(d_start.timestamp()),
                                        int(d_end.timestamp()))
                mo_req += 1
                rows = [r for raw in d_tweets
                        for r in [parse_tweet(raw, handle, account, seen_ids)] if r]
                if rows:
                    append_rows(rows)
                    mo_new    += len(rows)
                    total_new += len(rows)
                time.sleep(API_DELAY_SEC)

            print(f"    {mo_key} (daily) | "
                  f"+{mo_new:3d} tweets ({mo_req} req) | total: {total_new:,}")

        # Checkpoint this month as done
        mark_month_done(progress, handle, year, month)
        done_months.add(mo_key)

        # Step back one month
        month -= 1
        if month == 0:
            month = 12
            year -= 1

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

        new_count = collect_account(headers, handle, account, seen_ids, progress)

        mark_done(progress, handle)
        print(f"  ✓ @{handle} complete — {new_count:,} new tweets  "
              f"(running total: {len(seen_ids):,})")

        time.sleep(API_DELAY_SEC)

    print(f"\n{'='*70}")
    print(f"DONE.  {len(seen_ids):,} total tweets in {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
