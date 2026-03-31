"""
scrape_articles.py — Fetch full article text from a CSV of URLs.

INPUT:  Any CSV with a 'url' column (e.g. gdelt_urls.csv from GDELT.py,
        or a CSV exported from BigQuery).  Extra columns (year, month,
        title, domain) are carried through if present.

OUTPUT: articles_text.csv  (or --output path)
        Columns: url | year | month | title | domain | text | word_count | scraped_date

RESTART SAFE:
  Progress is saved every --batch-size articles.  Re-running the script
  automatically skips URLs already present in the output file.

USAGE:
  python scrape_articles.py                          # uses gdelt_urls.csv
  python scrape_articles.py --input my_urls.csv
  python scrape_articles.py --workers 10 --batch 200
  python scrape_articles.py --limit 500              # test with first 500 URLs
"""

import argparse
import concurrent.futures
import csv
import datetime
import os
import re
import time

import requests

import cleaning

# ─────────────────────────────────────────────
# DEFAULTS
# ─────────────────────────────────────────────
DEFAULT_INPUT   = "gdelt_urls.csv"
DEFAULT_OUTPUT  = "articles_text.csv"
DEFAULT_WORKERS = 8          # concurrent threads
DEFAULT_BATCH   = 25         # flush to disk every N articles (keep low for safety)
REQUEST_TIMEOUT = 15

OUTPUT_FIELDS = ["url", "year", "month", "title", "domain",
                 "text", "word_count", "scraped_date"]

# ─────────────────────────────────────────────
# HEADERS  (full Chrome fingerprint — reduces 403s)
# ─────────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language":  "es-SV,es;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding":  "gzip, deflate, br",
    "Connection":       "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest":   "document",
    "Sec-Fetch-Mode":   "navigate",
    "Sec-Fetch-Site":   "none",
    "Sec-Fetch-User":   "?1",
    "Cache-Control":    "max-age=0",
}

# ─────────────────────────────────────────────
# URL SECTION FILTER  (mirrors GDELT.py + config.py)
# ─────────────────────────────────────────────
_SKIP_SECTION_RE = re.compile(
    r"/("
    r"deportes|sports|futbol|deporte|entretenimiento|farandula|espectaculos|"
    r"internacional|mundo|global|tecnologia|salud|turismo|moda|"
    r"clasificados|horoscopo|recetas|vida|cocina|"
    r"h-deportes|h-internacional|h-entretenimiento|h-tecnologia|h-salud"
    r")/",
    re.IGNORECASE,
)

def is_political_url(url: str) -> bool:
    return not _SKIP_SECTION_RE.search(url)


# ─────────────────────────────────────────────
# HTTP FETCH
# ─────────────────────────────────────────────
_SESSION = requests.Session()
_SESSION.headers.update(HEADERS)

_ALTERNATE_UAS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]


def fetch_html(url: str):
    """
    Fetch URL, returning HTML string or None on failure.
    Retries once with an alternate User-Agent on 403.
    """
    for attempt, ua in enumerate([None] + _ALTERNATE_UAS):
        try:
            hdrs = {"User-Agent": ua} if ua else {}
            resp = _SESSION.get(url, timeout=REQUEST_TIMEOUT, headers=hdrs)
            if resp.status_code == 200:
                resp.encoding = resp.apparent_encoding or "utf-8"
                return resp.text
            if resp.status_code == 403 and attempt < len(_ALTERNATE_UAS):
                time.sleep(1)
                continue
            return None   # non-200 and not retrying
        except requests.RequestException:
            return None
    return None


# ─────────────────────────────────────────────
# SCRAPE ONE ROW
# ─────────────────────────────────────────────
def scrape_row(row: dict):
    """
    Fetch and extract text for one input row.
    Returns an output dict, or None if the article should be skipped.
    """
    url = row.get("url", "").strip()
    if not url:
        return None
    if not is_political_url(url):
        return None

    html = fetch_html(url)
    if not html or len(html) < 500:
        return None

    title = cleaning.extract_title_from_html(html) or row.get("title", "")
    text  = cleaning.extract_article_content(html)
    if len(text.strip()) < 150:
        return None   # not enough content

    return {
        "url":          url,
        "year":         row.get("year", ""),
        "month":        row.get("month", ""),
        "title":        title[:400],
        "domain":       row.get("domain", ""),
        "text":         text,
        "word_count":   len(text.split()),
        "scraped_date": datetime.date.today().isoformat(),
    }


# ─────────────────────────────────────────────
# CSV HELPERS
# ─────────────────────────────────────────────
def load_done_urls(output_path: str) -> set:
    if not os.path.exists(output_path):
        return set()
    done = set()
    with open(output_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("url"):
                done.add(row["url"])
    print(f"[resume] {len(done):,} URLs already scraped in {output_path}")
    return done


def init_output(output_path: str):
    if not os.path.exists(output_path):
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=OUTPUT_FIELDS).writeheader()


def flush_batch(output_path: str, batch: list):
    if not batch:
        return
    with open(output_path, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=OUTPUT_FIELDS).writerows(batch)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Scrape article text from a URL CSV.")
    parser.add_argument("--input",   default=DEFAULT_INPUT,  help="Input CSV with 'url' column")
    parser.add_argument("--output",  default=DEFAULT_OUTPUT, help="Output CSV path")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="Concurrent threads")
    parser.add_argument("--batch",   type=int, default=DEFAULT_BATCH,   help="Flush to disk every N articles")
    parser.add_argument("--limit",   type=int, default=0, help="Only process first N URLs (0 = all)")
    args = parser.parse_args()

    # ── Load input ──
    if not os.path.exists(args.input):
        print(f"ERROR: input file not found: {args.input}")
        return
    with open(args.input, newline="", encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))
    print(f"[load] {len(all_rows):,} rows in {args.input}")

    # ── Resume: skip already-done URLs ──
    init_output(args.output)
    done_urls = load_done_urls(args.output)
    todo = [r for r in all_rows if r.get("url") and r["url"] not in done_urls]

    if args.limit:
        todo = todo[:args.limit]

    print(f"[queue] {len(todo):,} URLs to scrape  ({len(done_urls):,} already done)")
    if not todo:
        print("Nothing to do.")
        return

    # ── Concurrent scraping ──
    total_saved   = len(done_urls)
    total_skipped = 0
    batch         = []
    start_time    = time.time()

    print(f"\nScraping with {args.workers} workers → {args.output}\n")

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(scrape_row, row): row for row in todo}

        for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
            result = future.result()

            if result:
                batch.append(result)
                total_saved += 1
            else:
                total_skipped += 1

            # Flush batch to disk
            if len(batch) >= args.batch:
                flush_batch(args.output, batch)
                batch = []

            # Progress every 50 completions
            if i % 50 == 0:
                elapsed   = time.time() - start_time
                rate      = i / elapsed if elapsed > 0 else 0
                remaining = (len(todo) - i) / rate if rate > 0 else 0
                print(
                    f"  {i:>6}/{len(todo)}  saved={total_saved:,}  "
                    f"skipped={total_skipped:,}  "
                    f"{rate:.1f}/s  ETA {remaining/60:.0f}min"
                )

    # Final flush
    flush_batch(args.output, batch)

    elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"Done in {elapsed/60:.1f} min")
    print(f"  Saved:   {total_saved:,} articles  → {args.output}")
    print(f"  Skipped: {total_skipped:,} (404/403/empty/non-political)")
    print(f"\nTo resume after interruption: just run again — already-scraped")
    print(f"URLs are skipped automatically.")


if __name__ == "__main__":
    main()
