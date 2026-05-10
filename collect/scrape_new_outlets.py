"""
scrape_new_outlets.py — Crawl article URLs from Salvadoran outlets not in GDELT
and scrape their content directly.

OUTLETS:
  revistafactum.com   — investigative journalism, category-based URLs
  gatoencerrado.news  — investigative journalism, date-based URLs
  focostv.com         — news/investigations, slug-based URLs
  eldiariodehoy.com   — elsalvador.com, supplement beyond HuggingFace dataset

STRATEGY:
  1. Try sitemap.xml / sitemap_index.xml first (fastest)
  2. Fall back to crawling category/archive pages
  3. Deduplicate against already-scraped articles
  4. Write article content directly to output/new_outlets_articles.csv

OUTPUT: output/new_outlets_articles.csv
  columns: url, year, month, title, domain, text, word_count, scraped_date

USAGE:
  python3 collect/scrape_new_outlets.py                    # all outlets
  python3 collect/scrape_new_outlets.py --outlet factum    # one outlet
  python3 collect/scrape_new_outlets.py --urls-only        # just collect URLs, don't scrape
"""

import argparse
import concurrent.futures
import csv
import datetime
import os
import re
import sys
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

REPO_ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_CSV = os.path.join(REPO_ROOT, "output", "new_outlets_articles.csv")
URLS_CSV   = os.path.join(REPO_ROOT, "output", "new_outlet_urls.csv")

OUTPUT_FIELDS  = ["url", "year", "month", "title", "domain",
                  "text", "word_count", "scraped_date"]
URLS_FIELDS    = ["url", "domain", "year", "month"]

REQUEST_TIMEOUT = 20
CRAWL_DELAY     = 0.8     # seconds between crawl requests (be polite)
SCRAPE_WORKERS  = 6

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-SV,es;q=0.9,en;q=0.8",
}

# ─────────────────────────────────────────────
# SECTION / CATEGORY SKIP LIST
# ─────────────────────────────────────────────
_SKIP_RE = re.compile(
    r"/("
    r"deportes|sports|futbol|entretenimiento|farandula|espectaculos|"
    r"internacional|mundo|global|tecnologia|salud|turismo|moda|"
    r"cine|musica|television|estilo|recetas|horoscopo|cocina|"
    r"guia-mundialista|clasificados|vida"
    r")(/|$)",
    re.IGNORECASE,
)

def is_political_url(url: str) -> bool:
    return not _SKIP_RE.search(url)


# ─────────────────────────────────────────────
# HTTP HELPERS
# ─────────────────────────────────────────────
_SESSION = requests.Session()
_SESSION.headers.update(HEADERS)


def fetch(url: str, timeout: int = REQUEST_TIMEOUT):
    try:
        r = _SESSION.get(url, timeout=timeout, allow_redirects=True)
        if r.status_code == 200:
            r.encoding = r.apparent_encoding or "utf-8"
            return r.text
    except Exception:
        pass
    return None


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


# ─────────────────────────────────────────────
# URL YEAR/MONTH EXTRACTION
# ─────────────────────────────────────────────
def extract_date_from_url(url: str):
    """Return (year_str, month_str) or ("", "")."""
    clean = url.split("?")[0].rstrip("/")
    m = re.search(r"/(\d{4})/(\d{2})/", clean)
    if m:
        return m.group(1), m.group(2)
    m = re.search(r"(\d{4})-(\d{2})-\d{2}", clean)
    if m:
        return m.group(1), m.group(2)
    return "", ""


# ─────────────────────────────────────────────
# SITEMAP PARSER
# ─────────────────────────────────────────────
def urls_from_sitemap(base_url: str, domain_filter: str = "") -> set:
    """
    Try sitemap.xml and sitemap_index.xml; recurse into sub-sitemaps.
    Returns set of article URLs.
    """
    candidates = [
        base_url.rstrip("/") + "/sitemap.xml",
        base_url.rstrip("/") + "/sitemap_index.xml",
        base_url.rstrip("/") + "/sitemap-news.xml",
        base_url.rstrip("/") + "/news-sitemap.xml",
        base_url.rstrip("/") + "/sitemap/",
    ]
    found: set = set()
    visited: set = set()

    def parse_sitemap(url: str):
        if url in visited:
            return
        visited.add(url)
        html = fetch(url, timeout=30)
        if not html:
            return
        s = BeautifulSoup(html, "xml")
        # Sub-sitemaps
        for loc in s.find_all("sitemap"):
            sub = loc.find("loc")
            if sub:
                time.sleep(0.3)
                parse_sitemap(sub.get_text(strip=True))
        # Article URLs
        for loc in s.find_all("url"):
            loctag = loc.find("loc")
            if loctag:
                u = loctag.get_text(strip=True)
                if domain_filter and domain_filter not in u:
                    continue
                if is_political_url(u):
                    found.add(u)

    for c in candidates:
        parse_sitemap(c)
        if found:
            print(f"    sitemap: {len(found):,} URLs from {c}")
            return found
        time.sleep(0.3)

    return found


# ─────────────────────────────────────────────
# CATEGORY PAGE CRAWL (fallback)
# ─────────────────────────────────────────────
def crawl_category_pages(base_url: str, category_paths: list,
                          article_pattern: str, max_pages: int = 80) -> set:
    """
    Walk paginated category pages, collecting article URLs matching article_pattern.
    article_pattern: regex that the URL must match to be considered an article.
    """
    found: set = set()
    art_re = re.compile(article_pattern)

    for cat_path in category_paths:
        for page in range(1, max_pages + 1):
            if page == 1:
                url = base_url.rstrip("/") + cat_path
            else:
                # Common WordPress pagination: /page/N/
                url = base_url.rstrip("/") + cat_path + f"page/{page}/"

            html = fetch(url)
            if not html:
                break
            s = soup(html)
            links = {a["href"] for a in s.find_all("a", href=True)}
            new_in_page = 0
            for link in links:
                full = urljoin(base_url, link).split("?")[0].split("#")[0]
                if art_re.search(full) and is_political_url(full) and full not in found:
                    found.add(full)
                    new_in_page += 1
            if new_in_page == 0:
                break   # no new articles → last page
            time.sleep(CRAWL_DELAY)

    return found


# ─────────────────────────────────────────────
# DATE-RANGE ARCHIVE CRAWL (gatoencerrado style)
# ─────────────────────────────────────────────
def crawl_date_archives(base_url: str, start_year: int, end_year: int,
                         article_pattern: str) -> set:
    """
    Walk /YYYY/MM/ archive pages month-by-month and collect article URLs.
    Works for WordPress sites with date-based archives.
    """
    found: set = set()
    art_re = re.compile(article_pattern)

    for yr in range(start_year, end_year + 1):
        for mo in range(1, 13):
            url = f"{base_url.rstrip('/')}/{yr}/{mo:02d}/"
            html = fetch(url)
            if not html:
                time.sleep(0.3)
                continue
            s = soup(html)
            links = {a["href"] for a in s.find_all("a", href=True)}
            for link in links:
                full = urljoin(base_url, link).split("?")[0].split("#")[0]
                if art_re.search(full) and is_political_url(full):
                    found.add(full)
            time.sleep(CRAWL_DELAY)
        print(f"    {yr}: {len(found):,} URLs so far")

    return found


# ─────────────────────────────────────────────
# ARTICLE TEXT EXTRACTION
# ─────────────────────────────────────────────
def extract_article(html: str) -> tuple:
    """Return (title, text) from HTML."""
    s = soup(html)

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

    # Body text
    text = ""
    for sel in ["article .entry-content", "article .post-content",
                ".article-body", ".entry-content", ".post-content",
                ".content-article", ".nota-cuerpo", "article"]:
        tag = s.select_one(sel)
        if tag:
            # Remove script/style/nav
            for t in tag(["script", "style", "nav", "aside",
                           "figure", "figcaption", ".tags", ".related"]):
                t.decompose()
            text = re.sub(r"\s{2,}", " ", tag.get_text(separator=" ", strip=True))
            if len(text.split()) >= 30:
                break

    return title.strip(), text.strip()


def scrape_one(url: str, domain: str = "") -> dict:
    """Scrape a single article URL. Returns dict or None."""
    if not domain:
        domain = urlparse(url).netloc
    html = fetch(url)
    if not html or len(html) < 500:
        return None
    title, text = extract_article(html)
    if len(text.split()) < 30:
        return None
    year, month = extract_date_from_url(url)
    return {
        "url":          url,
        "year":         year,
        "month":        month,
        "title":        title[:400],
        "domain":       domain,
        "text":         text,
        "word_count":   len(text.split()),
        "scraped_date": datetime.date.today().isoformat(),
    }


# ─────────────────────────────────────────────
# OUTLET DEFINITIONS
# ─────────────────────────────────────────────

def collect_factum_urls() -> set:
    """revistafactum.com — category-based WordPress."""
    print("[factum] Checking sitemap ...")
    urls = urls_from_sitemap("https://revistafactum.com", "revistafactum.com")
    if urls:
        return urls
    print("[factum] Falling back to category crawl ...")
    cats = [
        "/el-salvador/", "/opinion/", "/politica/", "/economia/",
        "/derechos-humanos/", "/seguridad/", "/medio-ambiente/",
    ]
    return crawl_category_pages(
        "https://revistafactum.com", cats,
        article_pattern=r"revistafactum\.com/.+/.+",
        max_pages=60,
    )


def collect_gatoencerrado_urls() -> set:
    """gatoencerrado.news — date-based WordPress, good date coverage."""
    print("[gatoencerrado] Checking sitemap ...")
    urls = urls_from_sitemap("https://gatoencerrado.news", "gatoencerrado.news")
    if urls:
        return urls
    print("[gatoencerrado] Falling back to date-archive crawl (2018-2025) ...")
    return crawl_date_archives(
        "https://gatoencerrado.news", 2018, 2025,
        article_pattern=r"gatoencerrado\.news/\d{4}/\d{2}/\d{2}/.+",
    )


def collect_focostv_urls() -> set:
    """focostv.com — slug-based WordPress."""
    print("[focostv] Checking sitemap ...")
    urls = urls_from_sitemap("https://focostv.com", "focostv.com")
    if urls:
        return urls
    print("[focostv] Falling back to category crawl ...")
    cats = [
        "/actualidad/", "/investigacion/", "/opinion/", "/politica/",
        "/economia/", "/sociedad/", "/derechos-humanos/",
    ]
    return crawl_category_pages(
        "https://focostv.com", cats,
        article_pattern=r"focostv\.com/.{10,}",
        max_pages=60,
    )


def collect_edh_urls() -> set:
    """
    elsalvador.com (El Diario de Hoy) — supplement beyond the HuggingFace dataset.
    Crawls national/politics/opinion sections for articles not already scraped.
    """
    print("[elsalvador.com/EDH] Checking sitemap ...")
    urls = urls_from_sitemap("https://www.elsalvador.com", "elsalvador.com")
    if not urls:
        print("[elsalvador.com/EDH] Falling back to category crawl ...")
        cats = [
            "/noticias/nacional/", "/noticias/politica/",
            "/opinion/", "/noticias/judicial/", "/noticias/economia/",
            "/noticias/seguridad/",
        ]
        urls = crawl_category_pages(
            "https://www.elsalvador.com", cats,
            article_pattern=r"elsalvador\.com/noticias/.+/\d+",
            max_pages=100,
        )
    # Filter to political sections only (the sitemap includes sports etc.)
    return {u for u in urls if is_political_url(u)}


OUTLETS = {
    "factum":       ("revistafactum.com",  collect_factum_urls),
    "gatoencerrado":("gatoencerrado.news", collect_gatoencerrado_urls),
    "focostv":      ("focostv.com",        collect_focostv_urls),
    "edh":          ("elsalvador.com",     collect_edh_urls),
}


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Scrape new Salvadoran news outlets.")
    parser.add_argument("--outlet",    choices=list(OUTLETS.keys()),
                        help="Scrape only this outlet (default: all)")
    parser.add_argument("--urls-only", action="store_true",
                        help="Collect URLs but don't scrape article text")
    parser.add_argument("--workers",   type=int, default=SCRAPE_WORKERS)
    args = parser.parse_args()

    outlets_to_run = {args.outlet: OUTLETS[args.outlet]} if args.outlet else OUTLETS

    # Load already-scraped URLs to skip
    done_urls: set = set()
    if os.path.exists(OUTPUT_CSV):
        with open(OUTPUT_CSV, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("url"):
                    done_urls.add(r["url"])
        print(f"[resume] {len(done_urls):,} articles already scraped")

    # Ensure output files exist
    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    if not os.path.exists(OUTPUT_CSV):
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=OUTPUT_FIELDS).writeheader()
    if not os.path.exists(URLS_CSV):
        with open(URLS_CSV, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=URLS_FIELDS).writeheader()

    all_new_articles = 0

    for outlet_key, (domain, url_collector) in outlets_to_run.items():
        print(f"\n{'='*60}")
        print(f"OUTLET: {outlet_key}  ({domain})")
        print(f"{'='*60}")

        # ── Collect URLs ──
        urls = url_collector()
        new_urls = [u for u in urls if u not in done_urls]
        print(f"  {len(urls):,} URLs found, {len(new_urls):,} not yet scraped")

        # Save URL list
        with open(URLS_CSV, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=URLS_FIELDS)
            for u in new_urls:
                yr, mo = extract_date_from_url(u)
                w.writerow({"url": u, "domain": domain, "year": yr, "month": mo})

        if args.urls_only or not new_urls:
            continue

        # ── Scrape articles ──
        print(f"  Scraping {len(new_urls):,} articles with {args.workers} workers ...")
        batch        = []
        saved        = 0
        skipped      = 0
        start        = time.time()

        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(scrape_one, u, domain): u for u in new_urls}
            for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
                result = future.result()
                if result:
                    batch.append(result)
                    done_urls.add(result["url"])
                    saved += 1
                else:
                    skipped += 1

                if len(batch) >= 50:
                    with open(OUTPUT_CSV, "a", newline="", encoding="utf-8") as f:
                        csv.DictWriter(f, fieldnames=OUTPUT_FIELDS).writerows(batch)
                    batch = []

                if i % 100 == 0:
                    elapsed = time.time() - start
                    rate    = i / elapsed if elapsed > 0 else 1
                    eta     = (len(new_urls) - i) / rate
                    print(f"    {i}/{len(new_urls)}  saved={saved}  "
                          f"skipped={skipped}  {rate:.1f}/s  ETA {eta/60:.0f}min")

        # Final flush
        if batch:
            with open(OUTPUT_CSV, "a", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=OUTPUT_FIELDS).writerows(batch)

        print(f"  → saved {saved:,} articles, skipped {skipped:,}")
        all_new_articles += saved

    print(f"\n{'='*60}")
    print(f"Total new articles scraped: {all_new_articles:,}")
    print(f"Output → {OUTPUT_CSV}")
    print(f"URL list → {URLS_CSV}")


if __name__ == "__main__":
    main()
