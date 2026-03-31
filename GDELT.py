"""
GDELT.py — El Salvador political article URL collection via GDELT Doc API

HOW TO GET ALL THE DATA (the core problem with the old version):
  The GDELT API returns at most 250 records per call.  If a time window has
  more than 250 matching articles you can't page through them — you just get
  the first 250.  The solution is to use SMALLER time windows (weekly instead
  of monthly) AND multiple focused political query terms so each sub-query
  stays under the cap.

  Old approach  : 1 query × 12 months × 50 records  =    600 max/year
  New approach  : 20 terms × 52 weeks  × 250 records = 260 000 max/year

RESTART SAFETY:
  - URLs are appended to gdelt_urls.csv after EVERY (term × week) batch.
  - gdelt_progress.json records the last completed (term_index, year, week).
  - Re-running the script skips everything already saved.

OUTPUT: gdelt_urls.csv
  Columns: url | year | month | title | domain | seendate | query_term
"""

import csv
import datetime
import json
import os
import re
import time

import requests

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
START_YEAR     = 2018          # change to restart partway (see gdelt_progress.json)
END_YEAR       = 2025
MAX_RECORDS    = 250           # GDELT API hard cap — do not raise above 250
API_DELAY_SEC  = 1.2           # seconds between API calls (be polite)
REQUEST_TIMEOUT = 60

OUTPUT_CSV     = "gdelt_urls.csv"
PROGRESS_FILE  = "gdelt_progress.json"
GDELT_URL      = "https://api.gdeltproject.org/api/v2/doc/doc"

CSV_FIELDS = ["url", "year", "month", "title", "domain", "seendate", "query_term"]

# ─────────────────────────────────────────────
# POLITICAL SEARCH TERMS
#
# Each term is queried separately for every weekly window.
# "sourcecountry:ES" restricts results to El Salvador-based news outlets
# (GDELT uses FIPS 10-4 codes; ES = El Salvador).
# Using multiple terms ensures we don't miss articles that contain
# only one political keyword.
# ─────────────────────────────────────────────
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
# URL-LEVEL SECTION FILTER
#
# Skips URLs whose path contains clearly non-political section names.
# Mirrors the SKIP_URL_PATTERNS logic in config.py so both pipelines
# stay consistent.
# ─────────────────────────────────────────────
_SKIP_SECTION_RE = re.compile(
    r"/("
    r"deportes|sports|futbol|deporte|"
    r"entretenimiento|farandula|espectaculos|"
    r"internacional|mundo|global|"           # international news ≠ El Salvador domestic
    r"tecnologia|salud|turismo|moda|"
    r"clasificados|horoscopo|recetas|vida|cocina|"
    r"h-deportes|h-internacional|h-entretenimiento|"
    r"h-tecnologia|h-salud|h-vida|h-espectaculos"
    r")/",
    re.IGNORECASE,
)

def is_political_url(url: str) -> bool:
    """Return False if the URL path clearly signals a non-political section."""
    return not _SKIP_SECTION_RE.search(url)


# ─────────────────────────────────────────────
# YEAR EXTRACTION FROM URL
#
# Supports: /YYYY/MM/DD/, /YYYY/MM/, YYYY-MM-DD slug, trailing /YYYY/
# Returns the year as a string, or "" if not found.
# ─────────────────────────────────────────────
def extract_year_from_url(url: str) -> str:
    """
    Extract a 4-digit year (2000-2030) from a URL using common news-site patterns.
    Returns the year as a string, or "" if not found.

    Patterns handled:
      /YYYY/MM/DD/      elfaro, laprensagrafica, etc.
      /YYYY/MM/         archive-style paths
      /YYYYMM/          elfaro compact format (e.g. /202203/)
      YYYY-MM-DD        date in slug
      /YYYY at path end elsalvador.com trailing year (e.g. /slug/64046/2026/)
    """
    clean = url.split("?")[0].split("#")[0]

    # /YYYY/MM/DD/ or /YYYY/MM/
    m = re.search(r"/(\d{4})/(\d{1,2})/", clean)
    if m:
        yr, mo = int(m.group(1)), int(m.group(2))
        if 2000 <= yr <= 2030 and 1 <= mo <= 12:
            return m.group(1)

    # /YYYYMM/ — 6-digit compact year+month (elfaro.net style: /202203/)
    m = re.search(r"/(\d{4})(\d{2})/", clean)
    if m:
        yr, mo = int(m.group(1)), int(m.group(2))
        if 2000 <= yr <= 2030 and 1 <= mo <= 12:
            return m.group(1)

    # YYYY-MM-DD in slug
    m = re.search(r"(\d{4})-(\d{2})-\d{2}", clean)
    if m:
        yr, mo = int(m.group(1)), int(m.group(2))
        if 2000 <= yr <= 2030 and 1 <= mo <= 12:
            return m.group(1)

    # Trailing /YYYY at path end (elsalvador.com: /slug/64046/2026/)
    m = re.search(r"/(\d{4})$", clean.rstrip("/"))
    if m and 2000 <= int(m.group(1)) <= 2030:
        return m.group(1)

    return ""


# ─────────────────────────────────────────────
# CSV HELPERS
# ─────────────────────────────────────────────
def init_csv():
    """Create CSV with header row if it doesn't already exist."""
    if not os.path.exists(OUTPUT_CSV):
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=CSV_FIELDS).writeheader()
        print(f"[init] Created {OUTPUT_CSV}")


def load_existing_urls() -> set:
    """Read all URLs already saved so we can skip them on resume."""
    if not os.path.exists(OUTPUT_CSV):
        return set()
    seen = set()
    with open(OUTPUT_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("url"):
                seen.add(row["url"])
    print(f"[resume] Loaded {len(seen):,} existing URLs from {OUTPUT_CSV}")
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


def save_progress(term_idx: int, year: int, week: int):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"last_term_idx": term_idx, "last_year": year, "last_week": week},
            f, indent=2,
        )


# ─────────────────────────────────────────────
# GDELT API
# ─────────────────────────────────────────────
def query_gdelt(query: str, start_dt: str, end_dt: str) -> list:
    """
    Call the GDELT Doc API for one (query, time-window) combination.
    Returns a list of article dicts from the API response.
    """
    params = {
        "query":         query,
        "mode":          "ArtList",
        "format":        "json",
        "maxrecords":    MAX_RECORDS,
        "startdatetime": start_dt,
        "enddatetime":   end_dt,
    }
    try:
        r = requests.get(GDELT_URL, params=params, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        return data.get("articles") or []
    except Exception as exc:
        print(f"  [API error] {exc}")
        return []


# ─────────────────────────────────────────────
# WEEK ITERATOR
# ─────────────────────────────────────────────
def iter_weeks(start_year: int, end_year: int):
    """
    Yield (year, iso_week, week_start_date, week_end_date) for every
    calendar week between start_year-01-01 and end_year-12-31.

    Why weekly?  The GDELT API caps each response at MAX_RECORDS=250.
    A busy news month can easily have 500+ articles; splitting into weeks
    ensures we collect from the full range rather than just the first 250.
    """
    current = datetime.date(start_year, 1, 1)
    end     = datetime.date(end_year, 12, 31)
    while current <= end:
        week_end = min(current + datetime.timedelta(days=6), end)
        iso_week = current.isocalendar()[1]
        yield current.year, iso_week, current, week_end
        current = week_end + datetime.timedelta(days=1)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    init_csv()
    seen_urls = load_existing_urls()
    progress  = load_progress()

    # Resume position — default to "before everything"
    last_term = progress.get("last_term_idx", -1)
    last_year = progress.get("last_year",     START_YEAR - 1)
    last_week = progress.get("last_week",     0)

    total_new      = 0
    total_filtered = 0

    all_weeks = list(iter_weeks(START_YEAR, END_YEAR))
    total_calls = len(QUERY_TERMS) * len(all_weeks)
    call_num    = 0

    print(f"\nGDELT collection: {len(QUERY_TERMS)} terms × {len(all_weeks)} weeks "
          f"= {total_calls:,} API calls")
    print(f"Output → {OUTPUT_CSV}   Progress → {PROGRESS_FILE}\n")

    for term_idx, query_term in enumerate(QUERY_TERMS):

        # Resume: skip query terms we've already fully processed
        if term_idx < last_term:
            call_num += len(all_weeks)
            continue

        print(f"\n{'='*70}")
        print(f"Term {term_idx+1}/{len(QUERY_TERMS)}: {query_term}")
        print(f"{'='*70}")

        for year, week_num, week_start, week_end in all_weeks:

            call_num += 1

            # Resume: skip weeks within the last term that are already done
            if term_idx == last_term and (year, week_num) <= (last_year, last_week):
                continue

            start_dt = week_start.strftime("%Y%m%d") + "000000"
            end_dt   = week_end.strftime("%Y%m%d")   + "235959"

            progress_pct = call_num / total_calls * 100
            print(
                f"  [{progress_pct:5.1f}%] {year} W{week_num:02d} "
                f"({week_start} → {week_end}) ...",
                end="  ", flush=True,
            )

            articles = query_gdelt(query_term, start_dt, end_dt)
            new_rows = []

            for art in articles:
                url = art.get("url", "").strip()
                if not url:
                    continue

                # ── Dedup ──
                if url in seen_urls:
                    continue

                # ── URL-level political section filter ──
                if not is_political_url(url):
                    total_filtered += 1
                    continue

                # ── Date out of range (if detectable from URL) ──
                url_year = extract_year_from_url(url)
                if url_year and not (str(START_YEAR) <= url_year <= str(END_YEAR)):
                    total_filtered += 1
                    continue

                seen_urls.add(url)

                # ── Parse year/month from GDELT seendate (YYYYMMDDTHHmmssZ) ──
                sd        = art.get("seendate", "")
                art_year  = sd[:4]  if len(sd) >= 4  else str(year)
                art_month = sd[4:6] if len(sd) >= 6  else f"{week_start.month:02d}"

                new_rows.append({
                    "url":        url,
                    "year":       art_year,
                    "month":      art_month,
                    "title":      (art.get("title") or "")[:300],
                    "domain":     art.get("domain", ""),
                    "seendate":   sd,
                    "query_term": query_term,
                })
                total_new += 1

            # ── Save after every batch ──
            append_rows(new_rows)
            save_progress(term_idx, year, week_num)

            print(
                f"+{len(new_rows):3d} new  "
                f"(total saved: {len(seen_urls):,}  filtered: {total_filtered:,})"
            )

            time.sleep(API_DELAY_SEC)

    print(f"\n{'='*70}")
    print(f"DONE.  {total_new:,} new URLs saved to {OUTPUT_CSV}")
    print(f"       {total_filtered:,} URLs filtered out (section/date/duplicate)")
    print(f"       Total unique URLs: {len(seen_urls):,}")
    print(f"\nTo restart from scratch: delete {OUTPUT_CSV} and {PROGRESS_FILE}")
    print(f"To resume after interruption: just run the script again — it will")
    print(f"  pick up from where it left off using {PROGRESS_FILE}.")


if __name__ == "__main__":
    main()
