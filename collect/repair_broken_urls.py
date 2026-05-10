"""
repair_broken_urls.py — Re-fetch broken/404 articles from articles_text.csv.

STRATEGY:
  1. Identify broken rows (error pages, <80 words, or 404 signals in text).
  2. Re-fetch each URL with redirect following enabled.
     - elmundo.sv    → 301-redirects to diario.elmundo.sv  ✓ confirmed
     - lapagina      → 301-redirects to new URL structure   ✓ confirmed
  3. For elsalvador.com /eldiariodehoy/ articles (redirect to homepage, not
     article): fall back to Wayback Machine CDX lookup.
  4. Write successfully recovered articles to repaired_articles.csv.
     These can then be merged into articles_text_clean.csv.

OUTPUT:
  output/repaired_articles.csv   — same columns as articles_text.csv

USAGE:
  python3 collect/repair_broken_urls.py
  python3 collect/repair_broken_urls.py --limit 500   # test run
  python3 collect/repair_broken_urls.py --domain elmundo.sv  # one domain
"""

import argparse
import concurrent.futures
import csv
import datetime
import os
import re
import sys
import time
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

REPO_ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_CSV   = os.path.join(REPO_ROOT, "output", "articles_text.csv")
OUTPUT_CSV  = os.path.join(REPO_ROOT, "output", "repaired_articles.csv")

OUTPUT_FIELDS = ["url", "year", "month", "title", "domain",
                 "text", "word_count", "scraped_date", "repaired_from"]

REQUEST_TIMEOUT = 20
WORKERS         = 8
WB_DELAY        = 1.5   # seconds between Wayback Machine calls

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-SV,es;q=0.9,en;q=0.8",
}

_SESSION = requests.Session()
_SESSION.headers.update(HEADERS)
_SESSION.max_redirects = 10

# ─────────────────────────────────────────────
# ERROR PAGE DETECTION  (mirrors clean_articles.py)
# ─────────────────────────────────────────────
ERROR_RE = re.compile(
    r"(404|not found|no encontramos|página que buscas|"
    r"regresando|page not found|lo sentimos)",
    re.IGNORECASE,
)

def is_broken(row: dict) -> bool:
    wc = int(row.get("word_count") or 0)
    text = row.get("text", "")
    return wc < 80 or bool(ERROR_RE.search(text[:400]))


# ─────────────────────────────────────────────
# ARTICLE TEXT EXTRACTION
# ─────────────────────────────────────────────
def extract_text(html: str) -> tuple:
    """Return (title, body_text) from HTML."""
    s = BeautifulSoup(html, "html.parser")

    # Title
    title = ""
    for sel in ["h1.entry-title", "h1.post-title", "h1.article-title",
                "h1.titulo", ".entry-header h1", "article h1", "h1"]:
        tag = s.select_one(sel)
        if tag:
            title = tag.get_text(strip=True)
            break
    if not title:
        og = s.find("meta", property="og:title")
        title = og["content"].strip() if og and og.get("content") else ""
    if not title:
        t = s.find("title")
        title = t.get_text(strip=True) if t else ""

    # Body
    text = ""
    for sel in ["article .entry-content", "article .post-content",
                ".article-body", ".entry-content", ".post-content",
                ".content-article", ".nota-cuerpo", ".field-items",
                "article", ".ArticleBody", ".article__body"]:
        tag = s.select_one(sel)
        if tag:
            for junk in tag(["script", "style", "nav", "aside",
                              "figure", "figcaption", ".tags", ".related",
                              ".share", ".comments"]):
                junk.decompose()
            candidate = re.sub(r"\s{2,}", " ", tag.get_text(separator=" ", strip=True))
            if len(candidate.split()) >= 40:
                text = candidate
                break

    return title.strip(), text.strip()


def is_homepage(url: str, original_domain: str) -> bool:
    """True if the final URL is just the homepage of a different site."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    return path == "" and parsed.netloc not in original_domain


# ─────────────────────────────────────────────
# WAYBACK MACHINE FALLBACK
# ─────────────────────────────────────────────
def wayback_fetch(url: str) -> str:
    """
    Query Wayback Machine CDX for the most recent good snapshot,
    return the HTML or None.
    """
    CDX = "https://web.archive.org/cdx/search/cdx"
    WB  = "https://web.archive.org/web"
    try:
        params = {
            "url": url, "output": "json", "limit": 1,
            "fl": "timestamp,statuscode",
            "filter": "statuscode:200",
            "from": "20180101",   # Bukele era only
        }
        r = _SESSION.get(CDX, params=params, timeout=20)
        data = r.json()
        if len(data) <= 1:
            return None
        ts = data[1][0]
        wb_url = f"{WB}/{ts}/{url}"
        time.sleep(WB_DELAY)
        page = _SESSION.get(wb_url, timeout=30, allow_redirects=True)
        if page.status_code == 200 and len(page.text) > 500:
            return page.text
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────
# REPAIR ONE ROW
# ─────────────────────────────────────────────
def repair_row(row: dict) -> dict:
    """
    Attempt to repair a broken article row.
    Returns a new output dict, or None if unrecoverable.
    """
    orig_url   = row.get("url", "").strip()
    orig_domain = urlparse(orig_url).netloc

    # ── Strategy 1: re-fetch with redirects ──
    html         = None
    resolved_url = orig_url
    repair_note  = ""

    try:
        resp = _SESSION.get(orig_url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if resp.status_code == 200 and len(resp.text) > 500:
            if not is_homepage(resp.url, orig_domain):
                html         = resp.text
                resolved_url = resp.url
                repair_note  = "redirect"
    except Exception:
        pass

    # ── Strategy 2: Wayback Machine (all URLs that failed redirect) ──
    if not html:
        html         = wayback_fetch(orig_url)
        repair_note  = "wayback"
        resolved_url = orig_url

    if not html:
        return None

    # ── Extract article ──
    title, text = extract_text(html)
    wc = len(text.split())
    if wc < 40:
        return None

    # Verify it's not still a 404 page
    if ERROR_RE.search(text[:400]):
        return None

    # Parse year/month from resolved URL or original row
    year  = row.get("year", "")
    month = row.get("month", "")
    if not year:
        m = re.search(r"/(\d{4})/(\d{2})/", resolved_url)
        if m:
            year, month = m.group(1), m.group(2)

    return {
        "url":          resolved_url,
        "year":         year,
        "month":        month,
        "title":        (title or row.get("title", ""))[:400],
        "domain":       urlparse(resolved_url).netloc,
        "text":         text,
        "word_count":   wc,
        "scraped_date": datetime.date.today().isoformat(),
        "repaired_from": orig_url if resolved_url != orig_url else "",
    }


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Re-fetch broken articles via redirects.")
    parser.add_argument("--limit",   type=int, default=0)
    parser.add_argument("--domain",  default="",
                        help="Only repair articles from this domain substring")
    parser.add_argument("--workers", type=int, default=WORKERS)
    args = parser.parse_args()

    # ── Load broken rows ──
    print(f"Loading {INPUT_CSV} ...")
    with open(INPUT_CSV, encoding="utf-8-sig", errors="replace") as f:
        all_rows = list(csv.DictReader(f))

    broken = [r for r in all_rows if is_broken(r)]
    if args.domain:
        broken = [r for r in broken
                  if args.domain.lower() in (r.get("domain","") + r.get("url","")).lower()]

    print(f"  Total rows:  {len(all_rows):,}")
    print(f"  Broken rows: {len(broken):,}")

    # ── Load already-repaired URLs ──
    done: set = set()
    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    if os.path.exists(OUTPUT_CSV):
        with open(OUTPUT_CSV, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                # Track by original URL (repaired_from OR url)
                done.add(r.get("repaired_from") or r.get("url",""))
        print(f"  Already repaired: {len(done):,}")

    todo = [r for r in broken if r.get("url") not in done]
    if args.limit:
        todo = todo[:args.limit]

    print(f"  To repair: {len(todo):,}")

    if not todo:
        print("Nothing to do.")
        return

    # ── Init output ──
    if not os.path.exists(OUTPUT_CSV):
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=OUTPUT_FIELDS).writeheader()

    # All URLs try redirect first; Wayback is the fallback inside repair_row().
    # Split only for display — the logic is unified inside repair_row().
    redir_rows = todo
    wb_rows    = []   # handled as fallback inside repair_row()

    print(f"\n  To attempt: {len(redir_rows):,} URLs")
    print(f"  Strategy: redirect → Wayback Machine fallback for failures")

    repaired   = 0
    failed     = 0
    batch      = []
    start      = time.time()

    def flush():
        if batch:
            with open(OUTPUT_CSV, "a", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=OUTPUT_FIELDS).writerows(batch)
            batch.clear()

    # ── Parallel redirect re-fetch ──
    if redir_rows:
        print(f"\nRe-fetching via redirects ({args.workers} workers)...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(repair_row, r): r for r in redir_rows}
            for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
                result = future.result()
                if result:
                    batch.append(result)
                    repaired += 1
                else:
                    failed += 1
                if len(batch) >= 100:
                    flush()
                if i % 500 == 0:
                    elapsed = time.time() - start
                    rate    = i / elapsed if elapsed > 0 else 1
                    eta     = (len(redir_rows) - i) / rate
                    print(f"  {i}/{len(redir_rows)}  repaired={repaired:,}  "
                          f"failed={failed:,}  {rate:.1f}/s  ETA {eta/60:.0f}min")
        flush()

    # (Wayback Machine is called automatically as fallback inside repair_row)

    elapsed = time.time() - start
    print(f"\n{'='*60}")
    print(f"Done in {elapsed/60:.1f} min")
    print(f"  Repaired: {repaired:,}")
    print(f"  Failed:   {failed:,}  (genuinely deleted / no archive)")
    print(f"  Output → {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
