"""
scrape_international.py — Scrape international news coverage of El Salvador
from the GDELT BigQuery export, with content filtering to keep only articles
actually about El Salvador politics / quality of life.

CONTENT FILTER:
  After scraping, the article text must contain:
    - "El Salvador" ≥ 3 times, OR
    - "Bukele" ≥ 2 times, OR
    - "El Salvador" ≥ 2 times AND any of (Bukele, excepción, CECOT, bitcoin,
      pandillas, maras, FMLN, ARENA, corrupción, derechos humanos, migración)
  This rejects "Salvadoran arrested in Maryland" stories (0-1 El Salvador
  mentions) while keeping actual political coverage.

SOURCES (from GDELT BQ, ActionGeo=ES, non-Salvadoran domains):
  Wire services:  reuters.com, efe.com, prensa-latina.cu, apnews.com, afp.com
  Quality dailies: theguardian.com, washingtonpost.com, dw.com, bbc.com,
                   nytimes.com, latimes.com, eluniversal.com.mx, nacion.com
  Spanish-language US: univision.com, vozdeamerica.com, telemundo.com
  Regional Central/South American: laprensa.hn, proceso.hn, prensalibre.com,
                   elpais.cr, elperiodico.com.gt, elnuevodiario.com.ni,
                   diariolibre.com, estrategiaynegocios.net, latribuna.hn
  International orgs: reliefweb.int, hrw.org, amnesty.org
  Networks: telesurtv.net, nbcnews.com, cbsnews.com, abcnews.go.com

SKIP (non-Spanish language papers, pure aggregators, hyper-local):
  mangalam.com, mathrubhumi.com, suprabhaatham.com (Malayalam)
  pregon.com.ar, jujuyaldia.com.ar, zazoom.it (aggregators)
  foxnews.com, breitbart.com (partisan US; immigration framing only)

OUTPUT: output/international_articles.csv
  columns: url, year, month, title, domain, text, word_count, scraped_date

USAGE:
  python3 collect/scrape_international.py
  python3 collect/scrape_international.py --limit 500   # test run
"""

import argparse
import concurrent.futures
import csv
import sys
csv.field_size_limit(sys.maxsize)
import datetime
import os
import re
import time
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

REPO_ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BQ_CSV     = os.path.join(REPO_ROOT, ".claude", "worktrees", "jolly-banzai", "dfd_bq_full.csv")
INTL_URLS  = os.path.join(REPO_ROOT, "output", "intl_urls.csv")
OUTPUT_CSV = os.path.join(REPO_ROOT, "output", "international_articles.csv")

OUTPUT_FIELDS = ["url", "year", "month", "title", "domain",
                 "text", "word_count", "scraped_date"]

REQUEST_TIMEOUT = 20
WORKERS         = 10

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es,en;q=0.8",
}

# ─────────────────────────────────────────────
# DOMAIN LISTS
# ─────────────────────────────────────────────

# Salvadoran domestic outlets — handled by other scripts, not here
SALVADORAN_DOMAINS = {
    "www.elsalvador.com", "elsalvador.com", "historico.elsalvador.com",
    "www.laprensagrafica.com", "laprensagrafica.com",
    "elmundo.sv", "diario.elmundo.sv", "www.elmundo.sv",
    "www.lapagina.com.sv", "lapagina.com.sv",
    "www.diariocolatino.com", "diariocolatino.com",
    "elfaro.net", "www.elfaro.net", "diario1.com", "www.diario1.com",
    "revistafactum.com", "gatoencerrado.news", "focostv.com",
    "contrapunto.com.sv", "nuevotribuno.com.sv",
    "www.asamblea.gob.sv", "asamblea.gob.sv",
    "rree.gob.sv", "presidencia.gob.sv",
    "www.fiscalia.gob.sv", "fiscalia.gob.sv",
    "www.pddh.gob.sv", "pddh.gob.sv", "www.tse.gob.sv", "tse.gob.sv",
}

# Explicitly skip — low quality, wrong language, aggregators, or too partisan
SKIP_DOMAINS = {
    # Aggregators / syndication hubs
    "www.yahoo.com", "news.yahoo.com", "yahoo.com",
    "www.msn.com", "msn.com", "www.aol.com",
    # US hyper-local (Salvadoran crime in US)
    "www.chron.com", "www.sfgate.com", "www.sandiegouniontribune.com",
    "www.lmtonline.com", "mynorthwest.com", "tucson.com",
    "www.expressnews.com", "www.mercurynews.com",
    "www.dallasnews.com", "www.star-telegram.com",
    "www.startribune.com", "www.mymotherlode.com",
    # US partisan (immigration framing, not El Salvador politics)
    "www.foxnews.com", "www.breitbart.com",
    # Malayalam / regional Indian (wrong language)
    "www.mangalam.com", "suprabhaatham.com",
    "www.mathrubhumi.com", "www.chandrikadaily.com",
    # Low-quality aggregators
    "www.pregon.com.ar", "www.jujuyaldia.com.ar",
    "www.zazoom.it", "www.notimerica.com",
    "www.plenglish.com",  # duplicate of prensa-latina in English
    "www.dailymail.co.uk",
}

# Section paths to skip even on good domains
_SKIP_SEC_RE = re.compile(
    r"/("
    r"deportes|sports|futbol|entretenimiento|farandula|espectaculos|"
    r"tecnologia|moda|horoscopo|recetas|cocina|turismo|travel|lifestyle|"
    r"entertainment|arts?|culture|food|fashion|style"
    r")(/|$)",
    re.IGNORECASE,
)

def is_political_url(url: str) -> bool:
    return not _SKIP_SEC_RE.search(url)


# ─────────────────────────────────────────────
# CONTENT FILTER  — must be ABOUT El Salvador
# ─────────────────────────────────────────────
_KEY_TERMS = re.compile(
    r"(bukele|excepci[oó]n|cecot|bitcoin|pandillas?|maras?|fmln|arena|"
    r"corrupci[oó]n|derechos humanos|migraci[oó]n|migrantes?|deportaci[oó]n|"
    r"asamblea legislativa|nuevas ideas|estado de excepci[oó]n)",
    re.IGNORECASE,
)

def is_about_el_salvador(text: str) -> bool:
    """
    True if the article is substantively about El Salvador, not just
    mentioning it in passing (e.g. 'Salvadoran arrested in Maryland').
    """
    t = text.lower()
    sv = t.count("el salvador")
    bukele = t.count("bukele")
    key_hits = len(_KEY_TERMS.findall(text))
    return (
        sv >= 3 or
        bukele >= 2 or
        (sv >= 2 and key_hits >= 1) or
        (sv >= 1 and key_hits >= 3)
    )


# ─────────────────────────────────────────────
# URL HELPERS
# ─────────────────────────────────────────────
def bare_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""

def extract_date(url: str):
    clean = url.split("?")[0].rstrip("/")
    m = re.search(r"/(\d{4})/(\d{2})/", clean)
    if m: return m.group(1), m.group(2)
    m = re.search(r"(\d{4})-(\d{2})-\d{2}", clean)
    if m: return m.group(1), m.group(2)
    return "", ""


# ─────────────────────────────────────────────
# ARTICLE EXTRACTION
# ─────────────────────────────────────────────
_SESSION = requests.Session()
_SESSION.headers.update(HEADERS)

def fetch(url: str):
    try:
        r = _SESSION.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if r.status_code == 200 and len(r.text) > 500:
            r.encoding = r.apparent_encoding or "utf-8"
            return r.text, r.url
    except Exception:
        pass
    return None, url

def extract(html: str) -> tuple:
    s = BeautifulSoup(html, "html.parser")
    # Title
    title = ""
    for sel in ["h1.entry-title","h1.post-title","h1.article-title",
                "h1.ArticleTitle","h1","og:title"]:
        if sel == "og:title":
            og = s.find("meta", property="og:title")
            if og and og.get("content"):
                title = og["content"].strip()
        else:
            tag = s.select_one(sel)
            if tag:
                title = tag.get_text(strip=True)
        if title: break
    # Body
    text = ""
    for sel in ["article .entry-content","article .post-content",".article-body",
                ".entry-content",".post-content",".content-article",
                ".ArticleBody","article",".story-body","[itemprop='articleBody']",
                ".field-items",".texto-noticia"]:
        tag = s.select_one(sel)
        if tag:
            for junk in tag(["script","style","nav","aside","figure",
                              "figcaption",".tags",".related",".share",".ad"]):
                junk.decompose()
            candidate = re.sub(r"\s{2,}", " ", tag.get_text(separator=" ", strip=True))
            if len(candidate.split()) >= 40:
                text = candidate
                break
    return title.strip(), text.strip()


# ─────────────────────────────────────────────
# STEP 1: Extract international URLs from BQ CSV
# ─────────────────────────────────────────────
def extract_intl_urls():
    """
    Read dfd_bq_full.csv and extract unique international domain URLs
    where ActionGeo=ES (event happened in El Salvador).
    Writes to intl_urls.csv.
    """
    # Priority domains — quality journalism actually covering El Salvador.
    # Only these are scraped; everything else in the BQ data is noise
    # (US local crime, Indian-language papers, Argentine aggregators, etc.)
    PRIORITY_DOMAINS = {
        # Wire services
        "www.reuters.com", "reuters.com",
        "www.efe.com", "efe.com",
        "www.prensa-latina.cu", "prensa-latina.cu",
        "apnews.com", "www.apnews.com",
        "www.afp.com", "afp.com",
        # Quality international dailies
        "www.theguardian.com", "theguardian.com",
        "www.dw.com", "dw.com",
        "www.bbc.com", "bbc.com", "www.bbc.co.uk",
        "www.washingtonpost.com",
        "www.nytimes.com",
        "www.latimes.com",
        "www.nbcnews.com",
        "www.cbsnews.com",
        "www.newsweek.com",
        # Spanish-language international
        "www.univision.com", "univision.com",
        "www.vozdeamerica.com", "vozdeamerica.com",
        "www.telemundo.com",
        "www.eluniversal.com.mx",
        "www.notimex.mx",
        # Regional Central/Latin American quality outlets
        "www.nacion.com", "nacion.com",            # Costa Rica
        "www.elpais.cr", "elpais.cr",              # Costa Rica
        "www.laprensa.hn", "laprensa.hn",          # Honduras
        "proceso.hn", "www.proceso.hn",            # Honduras (investigative)
        "www.latribuna.hn", "latribuna.hn",        # Honduras
        "www.prensalibre.com", "prensalibre.com",  # Guatemala
        "elperiodico.com.gt",                      # Guatemala
        "www.elnuevodiario.com.ni",                # Nicaragua
        "www.diariolibre.com",                     # Dominican Republic
        "www.estrategiaynegocios.net",             # Central America business
        "www.eleconomista.net",                    # Central America economics
        # International orgs / humanitarian
        "reliefweb.int", "www.reliefweb.int",
        "www.hrw.org", "hrw.org",
        "www.amnesty.org",
        # Networks
        "www.telesurtv.net", "telesurtv.net",
        "www.semana.com",                          # Colombia
        "www.eltiempo.com",                        # Colombia
    }

    if not os.path.exists(BQ_CSV):
        alt = os.path.join(REPO_ROOT, "dfd_bq_full.csv")
        if os.path.exists(alt):
            bq_path = alt
        else:
            print(f"ERROR: BQ CSV not found at {BQ_CSV}")
            print("Pass the correct path with --bq-input PATH")
            return 0
    else:
        bq_path = BQ_CSV

    print(f"[extract] Reading {bq_path} (priority domains only) ...")
    seen: set = set()
    rows = []
    skipped = 0

    with open(bq_path, encoding="utf-8-sig", errors="replace") as f:
        for r in csv.DictReader(f):
            url = (r.get("article_url") or "").strip()
            if not url or url in seen:
                continue
            d = bare_domain(url)
            # Only keep priority international domains
            if d not in PRIORITY_DOMAINS:
                skipped += 1
                continue
            if d in SKIP_DOMAINS:
                skipped += 1
                continue
            geo = (r.get("ActionGeo_CountryCode") or "").strip()
            if geo != "ES":
                skipped += 1
                continue
            if not is_political_url(url):
                skipped += 1
                continue
            seen.add(url)
            sql = r.get("SQLDATE") or r.get("MentionTimeDate") or ""
            rows.append({
                "url":    url,
                "domain": d,
                "year":   sql[:4],
                "month":  sql[4:6],
            })

    os.makedirs(os.path.dirname(INTL_URLS), exist_ok=True)
    with open(INTL_URLS, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["url","domain","year","month"])
        w.writeheader()
        w.writerows(rows)

    print(f"  Extracted {len(rows):,} international URLs → {INTL_URLS}")
    print(f"  (skipped {skipped:,} non-SV-geo / skip-domain / section-filtered)")

    from collections import Counter
    top = Counter(r["domain"] for r in rows).most_common(20)
    print("\n  Top domains:")
    for d, n in top:
        print(f"    {d:<45} {n:>5,}")
    return len(rows)


# ─────────────────────────────────────────────
# STEP 2: Scrape + content-filter
# ─────────────────────────────────────────────
def scrape_one(row: dict):
    url = row["url"]
    html, final_url = fetch(url)
    if not html:
        return None
    title, text = extract(html)
    if len(text.split()) < 80:
        return None
    if not is_about_el_salvador(text):
        return None
    year, month = extract_date(final_url)
    if not year:
        year, month = row.get("year",""), row.get("month","")
    return {
        "url":          final_url,
        "year":         year,
        "month":        month,
        "title":        title[:400],
        "domain":       bare_domain(final_url) or row.get("domain",""),
        "text":         text,
        "word_count":   len(text.split()),
        "scraped_date": datetime.date.today().isoformat(),
    }


def run_scrape(limit: int = 0, workers: int = WORKERS):
    if not os.path.exists(INTL_URLS):
        print(f"No URL file found at {INTL_URLS}. Run with --extract-urls first.")
        return

    with open(INTL_URLS, encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))
    print(f"[scrape] {len(all_rows):,} international URLs to process")

    # Resume
    done: set = set()
    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    if os.path.exists(OUTPUT_CSV):
        with open(OUTPUT_CSV, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("url"): done.add(r["url"])
        print(f"[resume] {len(done):,} already scraped")

    if not os.path.exists(OUTPUT_CSV):
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=OUTPUT_FIELDS).writeheader()

    todo = [r for r in all_rows if r["url"] not in done]
    if limit:
        todo = todo[:limit]
    print(f"[queue] {len(todo):,} URLs to scrape")

    saved = content_filtered = fetch_failed = 0
    batch = []
    start = time.time()

    def flush():
        if batch:
            with open(OUTPUT_CSV, "a", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=OUTPUT_FIELDS).writerows(batch)
            batch.clear()

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(scrape_one, r): r for r in todo}
        for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
            result = future.result()
            if result:
                batch.append(result)
                saved += 1
            else:
                # Could be fetch fail or content filter; approximate
                fetch_failed += 1

            if len(batch) >= 100:
                flush()

            if i % 500 == 0:
                elapsed = time.time() - start
                rate    = i / elapsed if elapsed > 0 else 1
                eta     = (len(todo) - i) / rate
                pct_kept = saved / i * 100
                print(f"  {i}/{len(todo)}  saved={saved:,} ({pct_kept:.0f}% pass filter)"
                      f"  {rate:.1f}/s  ETA {eta/60:.0f}min")

    flush()
    elapsed = time.time() - start

    print(f"\n{'='*60}")
    print(f"Done in {elapsed/60:.1f} min")
    print(f"  Scraped + passed El Salvador filter: {saved:,}")
    print(f"  Failed fetch or filtered out:        {fetch_failed:,}")
    print(f"  Output → {OUTPUT_CSV}")

    # Domain breakdown of what passed
    from collections import Counter
    with open(OUTPUT_CSV, encoding="utf-8") as f:
        domain_counts = Counter(r["domain"] for r in csv.DictReader(f))
    print("\nArticles per source:")
    for d, n in domain_counts.most_common(20):
        print(f"  {d:<45} {n:>5,}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Scrape international news about El Salvador from GDELT BQ data."
    )
    parser.add_argument("--extract-urls", action="store_true",
                        help="Extract international URLs from BQ CSV (run this first)")
    parser.add_argument("--bq-input", metavar="PATH",
                        help="Path to dfd_bq_full.csv (override default)")
    parser.add_argument("--limit",   type=int, default=0,
                        help="Only scrape first N URLs (0 = all)")
    parser.add_argument("--workers", type=int, default=WORKERS)
    args = parser.parse_args()

    if args.bq_input:
        global BQ_CSV
        BQ_CSV = args.bq_input

    # Default: do both steps
    if args.extract_urls or not os.path.exists(INTL_URLS):
        n = extract_intl_urls()
        if n == 0:
            return
        print()

    run_scrape(limit=args.limit, workers=args.workers)


if __name__ == "__main__":
    main()
