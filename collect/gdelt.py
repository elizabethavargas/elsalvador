"""
gdelt.py — El Salvador political article URL collection

TWO MODES:

1. API mode (default):
   Queries the GDELT Doc API week-by-week for political search terms.
   Usage:  python3 collect/gdelt.py

2. BigQuery CSV mode:
   Reads a GDELT BigQuery export (e.g. dfd_bq_full.csv), filters to El
   Salvador-relevant rows, deduplicates, and writes new URLs to gdelt_urls.csv.
   Usage:  python3 collect/gdelt.py --bq-input /path/to/dfd_bq_full.csv

FILTERING (BQ mode):
  Keep a row if:
    (a) ActionGeo_CountryCode == 'ES'  — event occurred in El Salvador, OR
    (b) article domain is a known Salvadoran news site
  Then additionally apply the URL section filter (skip sports/entertainment/etc.)
  and deduplicate against any URLs already in gdelt_urls.csv.

  Why exclude US-action-geo rows from non-SV domains?  GDELT maps many articles
  about Salvadoran immigrants committing crimes in US cities to ActionGeo=US.
  Those are not about El Salvador politics and would flood the corpus with noise.

OUTPUT: output/gdelt_urls.csv
  Columns: url | year | month | title | domain | seendate | query_term
"""

import argparse
import csv
import datetime
import json
import os
import re
import time
from urllib.parse import urlparse

import requests

REPO_ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_CSV    = os.path.join(REPO_ROOT, "output", "gdelt_urls.csv")
PROGRESS_FILE = os.path.join(REPO_ROOT, "output", "gdelt_progress.json")

# ─────────────────────────────────────────────
# API MODE CONFIGURATION
# ─────────────────────────────────────────────
START_YEAR      = 2018
END_YEAR        = 2025
MAX_RECORDS     = 250          # GDELT API hard cap
API_DELAY_SEC   = 1.2
REQUEST_TIMEOUT = 60
GDELT_URL       = "https://api.gdeltproject.org/api/v2/doc/doc"

CSV_FIELDS = ["url", "year", "month", "title", "domain", "seendate", "query_term"]

QUERY_TERMS = [
    'sourcecountry:ES "Bukele"',
    'sourcecountry:ES "Asamblea Legislativa" "El Salvador"',
    'sourcecountry:ES "gobierno" "El Salvador" politica',
    'sourcecountry:ES "elecciones" "El Salvador"',
    'sourcecountry:ES "estado de excepcion" "El Salvador"',
    'sourcecountry:ES "Nuevas Ideas" partido',
    'sourcecountry:ES "FMLN" OR "ARENA" "El Salvador"',
    'sourcecountry:ES "pandillas" OR "maras" gobierno "El Salvador"',
    'sourcecountry:ES "bitcoin" ley "El Salvador"',
    'sourcecountry:ES "corrupcion" OR "corrupción" gobierno "El Salvador"',
    'sourcecountry:ES "decreto legislativo" "El Salvador"',
    'sourcecountry:ES "derechos humanos" "El Salvador"',
    'sourcecountry:ES "Corte Suprema" "El Salvador"',
    'sourcecountry:ES "Fiscalia" OR "fiscal general" "El Salvador"',
    'sourcecountry:ES "CECOT" OR "regimen excepcion"',
    'sourcecountry:ES "presidente" "El Salvador" politica',
    'sourcecountry:ES "Sanchez Ceren" OR "Mauricio Funes"',
    'sourcecountry:ES "militares" asamblea "El Salvador"',
    'sourcecountry:ES "seguridad" nacional "El Salvador" gobierno',
    'sourcecountry:ES "reforma constitucional" OR "reeleccion" "El Salvador"',
]

# ─────────────────────────────────────────────
# BQ MODE: KNOWN SALVADORAN DOMAINS
#
# If a row's domain matches one of these, keep it regardless of ActionGeo.
# Covers outlets we know report on El Salvador politics.
# ─────────────────────────────────────────────
SALVADORAN_DOMAINS = {
    # El Diario de Hoy / elsalvador.com
    "www.elsalvador.com", "elsalvador.com",
    "historico.elsalvador.com",
    # La Prensa Gráfica
    "www.laprensagrafica.com", "laprensagrafica.com",
    # El Mundo
    "elmundo.sv", "diario.elmundo.sv", "www.elmundo.sv",
    # La Página
    "www.lapagina.com.sv", "lapagina.com.sv",
    # Diario Co Latino
    "www.diariocolatino.com", "diariocolatino.com",
    # El Faro
    "elfaro.net", "www.elfaro.net",
    # Diario 1
    "diario1.com", "www.diario1.com",
    # Investigative / alternative outlets
    "revistafactum.com", "www.revistafactum.com",
    "gatoencerrado.news", "www.gatoencerrado.news",
    "focostv.com", "www.focostv.com",
    "contrapunto.com.sv", "www.contrapunto.com.sv",
    "nuevotribuno.com.sv", "www.nuevotribuno.com.sv",
    # Official government
    "www.asamblea.gob.sv", "asamblea.gob.sv",
    "rree.gob.sv", "www.rree.gob.sv",
    "presidencia.gob.sv", "www.presidencia.gob.sv",
    "www.fiscalia.gob.sv", "fiscalia.gob.sv",
    "www.pddh.gob.sv", "pddh.gob.sv",
    "www.tse.gob.sv", "tse.gob.sv",
    # Regional wires that focus on El Salvador
    "www.centralamericadata.com", "centralamericadata.com",
}

# Aggregator/syndication domains to skip even if ActionGeo=ES.
# These are hub pages (Yahoo, MSN) or US hyper-local outlets that only
# mention El Salvador in the context of local crime / immigration stories.
SKIP_DOMAINS = {
    "www.yahoo.com", "news.yahoo.com", "yahoo.com",
    "www.msn.com", "msn.com",
    # US local news — primarily cover Salvadoran immigrant crime, not politics
    "www.chron.com", "www.sfgate.com", "www.latimes.com",
    "www.sandiegouniontribune.com", "www.lmtonline.com",
    "mynorthwest.com", "tucson.com",
    "www.expressnews.com", "www.mercurynews.com",
    "www.dallasnews.com", "www.star-telegram.com",
    # Tabloids
    "www.dailymail.co.uk",
}


# ─────────────────────────────────────────────
# SHARED: URL SECTION FILTER
# ─────────────────────────────────────────────
_SKIP_SECTION_RE = re.compile(
    r"/("
    r"deportes|sports|futbol|deporte|"
    r"entretenimiento|farandula|espectaculos|"
    r"internacional|mundo|global|"
    r"tecnologia|salud|turismo|moda|"
    r"clasificados|horoscopo|recetas|vida|cocina|"
    r"h-deportes|h-internacional|h-entretenimiento|"
    r"h-tecnologia|h-salud|h-vida|h-espectaculos|"
    r"guia-mundialista"
    r")/",
    re.IGNORECASE,
)

def is_political_url(url: str) -> bool:
    return not _SKIP_SECTION_RE.search(url)


def bare_domain(url: str) -> str:
    """Return netloc without trailing slash."""
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


# ─────────────────────────────────────────────
# SHARED: YEAR EXTRACTION FROM URL
# ─────────────────────────────────────────────
def extract_year_from_url(url: str) -> str:
    clean = url.split("?")[0].split("#")[0]
    m = re.search(r"/(\d{4})/(\d{1,2})/", clean)
    if m:
        yr, mo = int(m.group(1)), int(m.group(2))
        if 2000 <= yr <= 2030 and 1 <= mo <= 12:
            return m.group(1)
    m = re.search(r"/(\d{4})(\d{2})/", clean)
    if m:
        yr, mo = int(m.group(1)), int(m.group(2))
        if 2000 <= yr <= 2030 and 1 <= mo <= 12:
            return m.group(1)
    m = re.search(r"(\d{4})-(\d{2})-\d{2}", clean)
    if m:
        yr, mo = int(m.group(1)), int(m.group(2))
        if 2000 <= yr <= 2030 and 1 <= mo <= 12:
            return m.group(1)
    m = re.search(r"/(\d{4})$", clean.rstrip("/"))
    if m and 2000 <= int(m.group(1)) <= 2030:
        return m.group(1)
    return ""


# ─────────────────────────────────────────────
# SHARED: CSV HELPERS
# ─────────────────────────────────────────────
def init_csv():
    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    if not os.path.exists(OUTPUT_CSV):
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=CSV_FIELDS).writeheader()
        print(f"[init] Created {OUTPUT_CSV}")


def load_existing_urls() -> set:
    if not os.path.exists(OUTPUT_CSV):
        return set()
    seen = set()
    with open(OUTPUT_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("url"):
                seen.add(row["url"])
    print(f"[resume] {len(seen):,} URLs already in {OUTPUT_CSV}")
    return seen


def append_rows(rows: list):
    if not rows:
        return
    with open(OUTPUT_CSV, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=CSV_FIELDS).writerows(rows)


# ─────────────────────────────────────────────
# API MODE HELPERS
# ─────────────────────────────────────────────
def load_progress() -> dict:
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_progress(term_idx: int, year: int, week: int):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_term_idx": term_idx, "last_year": year,
                   "last_week": week}, f, indent=2)


def query_gdelt(query: str, start_dt: str, end_dt: str) -> list:
    params = {
        "query": query, "mode": "ArtList", "format": "json",
        "maxrecords": MAX_RECORDS,
        "startdatetime": start_dt, "enddatetime": end_dt,
    }
    try:
        r = requests.get(GDELT_URL, params=params, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return r.json().get("articles") or []
    except Exception as exc:
        print(f"  [API error] {exc}")
        return []


def iter_weeks(start_year: int, end_year: int):
    current = datetime.date(start_year, 1, 1)
    end     = datetime.date(end_year, 12, 31)
    while current <= end:
        week_end = min(current + datetime.timedelta(days=6), end)
        iso_week = current.isocalendar()[1]
        yield current.year, iso_week, current, week_end
        current = week_end + datetime.timedelta(days=1)


# ─────────────────────────────────────────────
# BQ MODE
# ─────────────────────────────────────────────
def run_bq_mode(bq_path: str):
    """
    Read a GDELT BigQuery export, filter to El Salvador-relevant articles,
    deduplicate, and append new URLs to gdelt_urls.csv.

    Relevance rules:
      1. ActionGeo_CountryCode == 'ES'  (event in El Salvador)
         AND domain is not in SKIP_DOMAINS
      OR
      2. Domain is in SALVADORAN_DOMAINS  (always keep Salvadoran outlets)

    Then additionally filter by URL section (no sports/entertainment/etc.)

    The --international flag also keeps major wire services (Reuters, AP, DW,
    WashPost, NYT, Guardian) that covered El Salvador events.  These form a
    separate analytical tier; off by default to keep the corpus focused.
    """
    print(f"\n{'='*70}")
    print(f"BQ MODE: processing {bq_path}")
    print(f"{'='*70}\n")

    if not os.path.exists(bq_path):
        print(f"ERROR: file not found: {bq_path}")
        return

    init_csv()
    seen_urls = load_existing_urls()

    total_rows   = 0
    kept         = 0
    skip_domain  = 0
    skip_geo     = 0
    skip_section = 0
    skip_dup     = 0
    new_rows     = []

    print(f"Reading {bq_path} ...")
    with open(bq_path, encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total_rows += 1
            if total_rows % 200_000 == 0:
                print(f"  ...{total_rows:,} rows scanned, {kept:,} kept so far")

            url = (row.get("article_url") or row.get("url") or "").strip()
            if not url:
                continue

            # ── Already seen ──
            if url in seen_urls:
                skip_dup += 1
                continue

            domain = bare_domain(url)

            # ── Domain block list (aggregators, US local news) ──
            if domain in SKIP_DOMAINS:
                skip_domain += 1
                continue

            # ── Relevance: must be in El Salvador OR from a Salvadoran outlet ──
            action_geo_cc = (row.get("ActionGeo_CountryCode") or "").strip()
            is_sv_action  = (action_geo_cc == "ES")
            is_sv_domain  = (domain in SALVADORAN_DOMAINS)

            if not is_sv_action and not is_sv_domain:
                skip_geo += 1
                continue

            # ── URL section filter ──
            if not is_political_url(url):
                skip_section += 1
                continue

            # ── Accept ──
            seen_urls.add(url)

            # Parse date from SQLDATE (YYYYMMDD) or MentionTimeDate
            sql_date = (row.get("SQLDATE") or row.get("MentionTimeDate") or "")
            year  = sql_date[:4]  if len(sql_date) >= 4  else ""
            month = sql_date[4:6] if len(sql_date) >= 6  else ""
            # Fall back to URL-extracted year
            if not year:
                year = extract_year_from_url(url)

            new_rows.append({
                "url":        url,
                "year":       year,
                "month":      month,
                "title":      (row.get("title") or "")[:300],
                "domain":     domain,
                "seendate":   sql_date,
                "query_term": "bq_import",
            })
            kept += 1

    append_rows(new_rows)

    print(f"\n{'='*70}")
    print(f"BQ processing complete.")
    print(f"  Total rows scanned : {total_rows:,}")
    print(f"  Duplicates skipped : {skip_dup:,}")
    print(f"  Domain blocked     : {skip_domain:,}")
    print(f"  Wrong geo (non-SV) : {skip_geo:,}")
    print(f"  Section filtered   : {skip_section:,}")
    print(f"  NEW URLs added     : {kept:,}")
    print(f"  Output → {OUTPUT_CSV}")
    print(f"\nNext step:")
    print(f"  python3 collect/scrape_articles.py --input {OUTPUT_CSV}")


# ─────────────────────────────────────────────
# API MODE
# ─────────────────────────────────────────────
def run_api_mode():
    init_csv()
    seen_urls = load_existing_urls()
    progress  = load_progress()

    last_term = progress.get("last_term_idx", -1)
    last_year = progress.get("last_year",     START_YEAR - 1)
    last_week = progress.get("last_week",     0)

    total_new      = 0
    total_filtered = 0

    all_weeks   = list(iter_weeks(START_YEAR, END_YEAR))
    total_calls = len(QUERY_TERMS) * len(all_weeks)
    call_num    = 0

    print(f"\nGDELT API collection: {len(QUERY_TERMS)} terms × {len(all_weeks)} weeks "
          f"= {total_calls:,} API calls")
    print(f"Output → {OUTPUT_CSV}   Progress → {PROGRESS_FILE}\n")

    for term_idx, query_term in enumerate(QUERY_TERMS):

        if term_idx < last_term:
            call_num += len(all_weeks)
            continue

        print(f"\n{'='*70}")
        print(f"Term {term_idx+1}/{len(QUERY_TERMS)}: {query_term}")
        print(f"{'='*70}")

        for year, week_num, week_start, week_end in all_weeks:
            call_num += 1

            if term_idx == last_term and (year, week_num) <= (last_year, last_week):
                continue

            start_dt = week_start.strftime("%Y%m%d") + "000000"
            end_dt   = week_end.strftime("%Y%m%d")   + "235959"

            pct = call_num / total_calls * 100
            print(f"  [{pct:5.1f}%] {year} W{week_num:02d} "
                  f"({week_start} → {week_end}) ...", end="  ", flush=True)

            articles = query_gdelt(query_term, start_dt, end_dt)
            new_rows = []

            for art in articles:
                url = art.get("url", "").strip()
                if not url or url in seen_urls:
                    continue
                if not is_political_url(url):
                    total_filtered += 1
                    continue
                url_year = extract_year_from_url(url)
                if url_year and not (str(START_YEAR) <= url_year <= str(END_YEAR)):
                    total_filtered += 1
                    continue

                seen_urls.add(url)
                sd = art.get("seendate", "")
                new_rows.append({
                    "url":        url,
                    "year":       sd[:4]  if len(sd) >= 4  else str(year),
                    "month":      sd[4:6] if len(sd) >= 6  else f"{week_start.month:02d}",
                    "title":      (art.get("title") or "")[:300],
                    "domain":     art.get("domain", ""),
                    "seendate":   sd,
                    "query_term": query_term,
                })
                total_new += 1

            append_rows(new_rows)
            save_progress(term_idx, year, week_num)

            print(f"+{len(new_rows):3d} new  "
                  f"(total: {len(seen_urls):,}  filtered: {total_filtered:,})")
            time.sleep(API_DELAY_SEC)

    print(f"\n{'='*70}")
    print(f"DONE.  {total_new:,} new URLs  →  {OUTPUT_CSV}")


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Collect GDELT article URLs for El Salvador.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Query GDELT Doc API week-by-week (default):
  python3 collect/gdelt.py

  # Process a BigQuery export instead:
  python3 collect/gdelt.py --bq-input dfd_bq_full.csv
""",
    )
    parser.add_argument(
        "--bq-input",
        metavar="PATH",
        help="Path to a GDELT BigQuery CSV export (dfd_bq_full.csv). "
             "Skips API queries and processes the file directly.",
    )
    args = parser.parse_args()

    if args.bq_input:
        run_bq_mode(args.bq_input)
    else:
        run_api_mode()
