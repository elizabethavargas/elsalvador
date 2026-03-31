"""
twitter_collector.py — El Salvador government tweet collection via twitterapi.io

REQUIREMENTS:
  pip install requests

AUTHENTICATION:
  Set your API key in the environment variable:
    export TWITTERAPI_IO_KEY="your_api_key_here"
  Or create a .env file and load it yourself before running.
  Get a key at: https://twitterapi.io

HOW IT WORKS:
  Uses the advanced_search endpoint with query operators:
    from:<handle> since:YYYY-MM-DD until:YYYY-MM-DD -filter:nativeretweets
  Queries one month at a time per account to stay under page limits.
  Paginates through all results using the cursor field.

RESTART SAFETY:
  - Tweets are appended to tweets.csv after each (account × month) batch.
  - twitter_progress.json records the last completed (handle, year, month).
  - Re-running the script resumes from where it left off automatically.

OUTPUT: tweets.csv
  Columns: tweet_id | handle | account | date | year | month | text |
           likes | retweets | replies | quotes | views | lang

COST ESTIMATE (twitterapi.io pricing):
  $0.15 per 1,000 tweets fetched.  A typical government account posts
  ~100-500 tweets/year, so 20 accounts × 10 years ≈ 20,000-100,000 tweets
  ≈ $3–$15 total.
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

INCLUDE_QUOTES = False   # Set True to also keep quote-tweets
API_DELAY_SEC  = 5.5     # free tier: 1 request per 5 seconds (paid: drop to 0.5)
REQUEST_TIMEOUT = 30

# 429 retry settings
MAX_RETRIES    = 5
RETRY_BACKOFF  = 10      # extra seconds added per retry (10s, 20s, 30s …)

OUTPUT_CSV    = "tweets.csv"
PROGRESS_FILE = "twitter_progress.json"

BASE_URL      = "https://api.twitterapi.io"
SEARCH_EP     = f"{BASE_URL}/twitter/tweet/advanced_search"

CSV_FIELDS = [
    "tweet_id", "handle", "account", "date", "year", "month",
    "text", "likes", "retweets", "replies", "quotes", "views", "lang",
]

# ─────────────────────────────────────────────
# EL SALVADOR GOVERNMENT ACCOUNTS
#
# Format: { "twitter_handle": "display_name" }
# Handles are used in the query; display name goes into the CSV.
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
# AUTH HEADER
# ─────────────────────────────────────────────
def _load_env_file(path: str):
    """Parse a simple KEY=value .env file and populate os.environ."""
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


def get_headers() -> dict:
    # Try loading from a .env file in the same directory as this script
    _load_env_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

    api_key = os.environ.get("TWITTERAPI_IO_KEY", "")
    if not api_key:
        raise EnvironmentError(
            "API key not found. Do one of:\n"
            "  1) Create a .env file next to this script:  TWITTERAPI_IO_KEY=your_key_here\n"
            "  2) Export it in your shell:  export TWITTERAPI_IO_KEY='your_key_here'\n"
            "Get a key at: https://twitterapi.io"
        )
    return {"X-API-Key": api_key}


# ─────────────────────────────────────────────
# CSV HELPERS
# ─────────────────────────────────────────────
def init_csv():
    """Create CSV with header row if it doesn't already exist."""
    if not os.path.exists(OUTPUT_CSV):
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=CSV_FIELDS).writeheader()
        print(f"[init] Created {OUTPUT_CSV}")


def load_existing_ids() -> set:
    """Read all tweet IDs already saved so we can skip duplicates on resume."""
    if not os.path.exists(OUTPUT_CSV):
        return set()
    seen = set()
    with open(OUTPUT_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("tweet_id"):
                seen.add(row["tweet_id"])
    print(f"[resume] Loaded {len(seen):,} existing tweet IDs from {OUTPUT_CSV}")
    return seen


def append_rows(rows: list):
    """Append a list of row dicts to the CSV (no header)."""
    if not rows:
        return
    with open(OUTPUT_CSV, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=CSV_FIELDS).writerows(rows)


# ─────────────────────────────────────────────
# PROGRESS / RESUME
# ─────────────────────────────────────────────
def load_progress() -> dict:
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_progress(handle: str, year: int, month: int):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"last_handle": handle, "last_year": year, "last_month": month},
            f, indent=2,
        )


# ─────────────────────────────────────────────
# API CALL
# ─────────────────────────────────────────────
def search_tweets(headers: dict, query: str, cursor: str = "") -> dict:
    """
    Single call to advanced_search with 429-aware retry.
    Returns the parsed JSON dict, or {} on unrecoverable error.
    """
    params = {
        "query":     query,
        "queryType": "Latest",
    }
    if cursor:
        params["cursor"] = cursor

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(
                SEARCH_EP,
                headers=headers,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )
            if r.status_code == 429:
                wait = RETRY_BACKOFF * attempt
                print(f"\n  [429] Rate limited. Waiting {wait}s (attempt {attempt}/{MAX_RETRIES})...",
                      end=" ", flush=True)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except requests.HTTPError as exc:
            print(f"\n  [HTTP {exc.response.status_code}] {exc}")
            return {}
        except Exception as exc:
            print(f"\n  [API error] {exc}")
            return {}

    print(f"\n  [skip] Gave up after {MAX_RETRIES} retries.")
    return {}


# ─────────────────────────────────────────────
# TWEET PARSING
# ─────────────────────────────────────────────
def parse_tweet(raw: dict, handle: str, account: str, seen_ids: set) -> dict | None:
    """
    Convert a raw tweet dict from the API into a CSV row dict.
    Returns None if the tweet should be skipped (duplicate, retweet, quote).
    """
    tid = str(raw.get("id", ""))
    if not tid or tid in seen_ids:
        return None

    # Skip native retweets (belt-and-suspenders — query already excludes them)
    if raw.get("retweeted_tweet"):
        return None

    # Skip quote-tweets if not wanted
    if not INCLUDE_QUOTES and raw.get("quoted_tweet"):
        return None

    seen_ids.add(tid)

    # createdAt format: "Mon Jan 01 00:00:00 +0000 2024"
    created_raw = raw.get("createdAt", "")
    try:
        created = datetime.datetime.strptime(created_raw, "%a %b %d %H:%M:%S +0000 %Y")
        date_str  = created.strftime("%Y-%m-%d %H:%M:%S")
        year_str  = str(created.year)
        month_str = f"{created.month:02d}"
    except ValueError:
        date_str  = created_raw
        year_str  = ""
        month_str = ""

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
# MONTH ITERATOR
# ─────────────────────────────────────────────
def iter_months(start_year: int, end_year: int):
    """Yield (year, month) for every month in the range."""
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            yield year, month


def month_window(year: int, month: int) -> tuple[str, str]:
    """
    Return (since_str, until_str) in YYYY-MM-DD format.
    until is the first day of the next month (exclusive in Twitter search).
    """
    since = datetime.date(year, month, 1).strftime("%Y-%m-%d")
    if month == 12:
        until = datetime.date(year + 1, 1, 1).strftime("%Y-%m-%d")
    else:
        until = datetime.date(year, month + 1, 1).strftime("%Y-%m-%d")
    return since, until


# ─────────────────────────────────────────────
# COLLECT ONE (ACCOUNT × MONTH) BATCH
# ─────────────────────────────────────────────
def collect_month(
    headers: dict,
    handle: str,
    account: str,
    year: int,
    month: int,
    seen_ids: set,
) -> list:
    """
    Fetch all tweets from `handle` in the given month.
    Paginates until has_next_page is False.
    Returns a list of CSV-ready row dicts.
    """
    since, until = month_window(year, month)

    # Build query:
    #   from:handle          — only this account's tweets
    #   since:YYYY-MM-DD     — on or after
    #   until:YYYY-MM-DD     — before (exclusive)
    #   -filter:nativeretweets — no native RTs
    quote_filter = "" if INCLUDE_QUOTES else " -filter:quote"
    query = (
        f"from:{handle} since:{since} until:{until}"
        f" -filter:nativeretweets{quote_filter}"
    )

    new_rows  = []
    cursor    = ""
    page      = 0

    while True:
        page += 1
        data = search_tweets(headers, query, cursor)

        if not data:
            break

        for raw in data.get("tweets") or []:
            row = parse_tweet(raw, handle, account, seen_ids)
            if row:
                new_rows.append(row)

        if not data.get("has_next_page"):
            break

        cursor = data.get("next_cursor", "")
        if not cursor:
            break

        time.sleep(API_DELAY_SEC)

    return new_rows


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    init_csv()
    seen_ids = load_existing_ids()
    progress = load_progress()
    headers  = get_headers()

    last_handle = progress.get("last_handle", "")
    last_year   = progress.get("last_year",   START_YEAR - 1)
    last_month  = progress.get("last_month",  0)

    account_list = list(ACCOUNTS.items())   # [(handle, display_name), ...]
    all_months   = list(iter_months(START_YEAR, END_YEAR))
    total_batches = len(account_list) * len(all_months)
    batch_num     = 0

    # Determine which account index to resume from
    resume_account_idx = 0
    if last_handle:
        handles = [h for h, _ in account_list]
        if last_handle in handles:
            resume_account_idx = handles.index(last_handle)

    print(f"\nTwitter collection: {len(account_list)} accounts × "
          f"{len(all_months)} months = {total_batches:,} batches")
    print(f"Date range: {START_YEAR}-01 → {END_YEAR}-12")
    print(f"Retweets: excluded  |  Quote-tweets: {'included' if INCLUDE_QUOTES else 'excluded'}")
    print(f"Output → {OUTPUT_CSV}   Progress → {PROGRESS_FILE}\n")

    for acct_idx, (handle, account) in enumerate(account_list):

        # Skip fully-completed accounts before the resume point
        if acct_idx < resume_account_idx:
            batch_num += len(all_months)
            continue

        print(f"\n{'='*70}")
        print(f"Account {acct_idx+1}/{len(account_list)}: @{handle}  ({account})")
        print(f"{'='*70}")

        for year, month in all_months:

            batch_num += 1

            # Skip months already completed within the resume account
            if acct_idx == resume_account_idx and (year, month) <= (last_year, last_month):
                continue

            pct = batch_num / total_batches * 100
            print(
                f"  [{pct:5.1f}%]  {year}-{month:02d}  ...",
                end="  ", flush=True,
            )

            new_rows = collect_month(headers, handle, account, year, month, seen_ids)

            append_rows(new_rows)
            save_progress(handle, year, month)

            print(
                f"+{len(new_rows):3d} tweets  "
                f"(total saved: {len(seen_ids):,})"
            )

            time.sleep(API_DELAY_SEC)

    print(f"\n{'='*70}")
    print(f"DONE.  {len(seen_ids):,} total tweets saved to {OUTPUT_CSV}")
    print(f"\nTo restart from scratch: delete {OUTPUT_CSV} and {PROGRESS_FILE}")
    print(f"To resume after interruption: just re-run the script.")


if __name__ == "__main__":
    main()
