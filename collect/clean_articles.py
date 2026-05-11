"""
clean_articles.py — Merge all article sources into one master corpus.

SOURCES (in priority order — first-seen URL wins on dedup):
  1. repaired_articles.csv     — explicitly repaired broken URLs
  2. hf_news.csv               — HuggingFace Salvadoran news datasets
  3. gdelt_sv_articles.csv     — domestic outlets via GDELT BQ
  4. articles_text.csv         — original scrape
  5. new_outlets_articles.csv  — focostv, revistafactum, etc.
  6. international_articles.csv — Reuters, DW, Guardian, etc.

WHAT IT DOES:
  1. Loads and normalises columns across all sources
  2. Deduplicates by URL (priority order above)
  3. Near-deduplicates by normalised title (keeps first)
  4. Drops broken/error rows
  5. Strips leading/trailing boilerplate from text
  6. Drops articles shorter than MIN_WORDS after cleaning
  7. Writes output/articles_master.csv

USAGE:
  python3 collect/clean_articles.py
  python3 collect/clean_articles.py --min-words 60 --no-intl
"""

import argparse
import csv
import os
import re
import sys
from urllib.parse import urlparse

csv.field_size_limit(sys.maxsize)

REPO_ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR    = os.path.join(REPO_ROOT, "output")
OUTPUT_CSV = os.path.join(OUT_DIR, "articles_master.csv")

MIN_WORDS_DEFAULT = 50

# Output columns (superset — extras filled with "")
OUTPUT_FIELDS = ["url", "year", "month", "title", "domain",
                 "text", "word_count", "source_file"]

# ─────────────────────────────────────────────────────
# DROP / ERROR RULES
# ─────────────────────────────────────────────────────
DROP_DOMAINS = {"elmundo.sv"}   # old domain — all 404; real content is at diario.elmundo.sv

ERROR_RE = re.compile(
    r"404|not found|no encontramos|p[aá]gina.{0,20}(no existe|que buscas)"
    r"|page not found|javascript (is )?required|cookies? (are )?required"
    r"|access denied|forbidden|suscr[ií]bete para continuar",
    re.IGNORECASE,
)

# ─────────────────────────────────────────────────────
# TEXT CLEANING
# ─────────────────────────────────────────────────────
_BYLINE_BLOCK = re.compile(
    r"^.*?\npor\s*\n\s*[^\n]+\n"
    r"[^\n]*(hace|published|publicado)[^\n]*\n"
    r"(\d+\n)?",
    re.IGNORECASE | re.DOTALL,
)
_SECTION_HEADER = re.compile(r"^\s*[A-ZÁÉÍÓÚÑ][^\n]{0,40}\n\n", re.UNICODE)

_FOOTER_PATTERNS = [re.compile(p, re.IGNORECASE) for p in [
    r"\n(compartir|share)\s*$",
    r"\n(suscr[ií]bete|subscribe)[^\n]*$",
    re.escape("©"),
    r"\ntodos los derechos reservados",
    r"\n(cookies?|privacidad|privacy)[^\n]*$",
    r"\n(ver m[aá]s|read more|continue reading)[^\n]*$",
    r"\nir al inicio[^\n]*$",
]]


def clean_text(raw: str) -> str:
    text = raw
    # Fix common mojibake
    try:
        text = text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    # Strip leading byline block
    m = _BYLINE_BLOCK.match(text)
    if m:
        text = text[m.end():]
    else:
        m2 = _SECTION_HEADER.match(text)
        if m2:
            text = text[m2.end():]
    # Strip trailing boilerplate
    for pat in _FOOTER_PATTERNS:
        text = pat.sub("", text)
    # Collapse whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def word_count(text: str) -> int:
    return len(text.split())


# ─────────────────────────────────────────────────────
# NORMALISE TITLE for near-dedup
# ─────────────────────────────────────────────────────
def norm_domain(domain: str, url: str = "") -> str:
    """Strip www. and extract from URL if domain is blank."""
    d = domain.strip()
    if not d and url:
        try:
            d = urlparse(url).netloc
        except Exception:
            pass
    # Remove leading www.
    if d.startswith("www."):
        d = d[4:]
    return d.lower()


def norm_title(title: str) -> str:
    """Lowercase, strip punctuation/spaces for near-dedup."""
    t = title.lower()
    t = re.sub(r"[^a-záéíóúñü0-9]", "", t)
    return t[:120]   # cap length so tiny truncations don't matter


# ─────────────────────────────────────────────────────
# LOAD HELPERS
# ─────────────────────────────────────────────────────
def _year_month(date_str: str):
    """Extract (year, month) strings from YYYY-MM-DD or YYYYMMDD or YYYY/MM/..."""
    if not date_str:
        return "", ""
    date_str = date_str.strip()
    # YYYY-MM-DD
    m = re.match(r"(\d{4})-(\d{2})", date_str)
    if m:
        return m.group(1), m.group(2)
    # YYYYMMDD
    m = re.match(r"(\d{4})(\d{2})\d{2}", date_str)
    if m:
        return m.group(1), m.group(2)
    # YYYY/MM
    m = re.match(r"(\d{4})/(\d{2})", date_str)
    if m:
        return m.group(1), m.group(2)
    # Just YYYY
    m = re.match(r"(\d{4})", date_str)
    if m:
        return m.group(1), ""
    return "", ""


def load_standard(path: str, source_label: str):
    """Load CSVs with standard schema: url,year,month,title,domain,text,word_count,..."""
    rows = []
    if not os.path.exists(path):
        print(f"  [skip] not found: {path}")
        return rows
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        for r in csv.DictReader(f):
            url = r.get("url", "").strip()
            rows.append({
                "url":        url,
                "year":       r.get("year", "").strip(),
                "month":      r.get("month", "").strip(),
                "title":      r.get("title", "").strip(),
                "domain":     norm_domain(r.get("domain", ""), url),
                "text":       r.get("text", "").strip(),
                "word_count": r.get("word_count", "0"),
                "source_file": source_label,
            })
    return rows


def load_hf_news(path: str):
    """Load hf_news.csv which uses different column names."""
    rows = []
    if not os.path.exists(path):
        print(f"  [skip] not found: {path}")
        return rows
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        for r in csv.DictReader(f):
            url   = r.get("url", "").strip()
            text  = r.get("content", "").strip()
            title = r.get("title", "").strip()
            date  = r.get("date", "").strip()
            year, month = _year_month(date)
            domain = norm_domain(r.get("source", ""), url)
            rows.append({
                "url":         url,
                "year":        year,
                "month":       month,
                "title":       title,
                "domain":      domain,
                "text":        text,
                "word_count":  str(len(text.split())),
                "source_file": "hf_news",
            })
    return rows


# ─────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────
def main(min_words: int = MIN_WORDS_DEFAULT, include_intl: bool = True):

    # ── Load all sources in priority order ──
    print("Loading sources...")
    sources = [
        ("repaired",      load_standard(os.path.join(OUT_DIR, "repaired_articles.csv"),      "repaired")),
        ("hf_news",       load_hf_news(os.path.join(OUT_DIR, "hf_news.csv"))),
        ("gdelt_sv",      load_standard(os.path.join(OUT_DIR, "gdelt_sv_articles.csv"),      "gdelt_sv")),
        ("articles_text", load_standard(os.path.join(OUT_DIR, "articles_text.csv"),          "articles_text")),
        ("new_outlets",   load_standard(os.path.join(OUT_DIR, "new_outlets_articles.csv"),   "new_outlets")),
    ]
    if include_intl:
        sources.append(
            ("intl", load_standard(os.path.join(OUT_DIR, "international_articles.csv"), "intl"))
        )

    total_raw = 0
    for label, rows in sources:
        print(f"  {len(rows):>8,}  {label}")
        total_raw += len(rows)
    print(f"  {total_raw:>8,}  TOTAL raw")

    # ── Dedup by URL (first seen wins) ──
    print("\nDeduplicating by URL...")
    url_seen: set = set()
    deduped = []
    for _, rows in sources:
        for r in rows:
            url = r["url"]
            if not url or url in url_seen:
                continue
            url_seen.add(url)
            deduped.append(r)
    print(f"  After URL dedup: {len(deduped):,}")

    # ── Drop broken domains / error pages / shorts ──
    print("\nCleaning...")
    stats = {"dropped_domain": 0, "dropped_error": 0,
             "dropped_short": 0, "kept": 0}
    cleaned = []
    title_seen: set = set()

    for r in deduped:
        domain = r.get("domain", "").strip()

        if domain in DROP_DOMAINS:
            stats["dropped_domain"] += 1
            continue

        title = r.get("title", "")
        text  = r.get("text",  "")
        probe = (title + " " + text[:300]).lower()
        if ERROR_RE.search(probe):
            stats["dropped_error"] += 1
            continue

        raw_wc = int(r.get("word_count") or 0)
        if raw_wc < min_words:
            stats["dropped_short"] += 1
            continue

        # Near-dedup by title
        nt = norm_title(title)
        if nt and len(nt) > 15:   # skip very short/empty titles from dedup
            if nt in title_seen:
                stats["dropped_short"] += 1   # reuse bucket
                continue
            title_seen.add(nt)

        # Clean text
        text_clean = clean_text(text)
        wc = word_count(text_clean)
        if wc < min_words:
            stats["dropped_short"] += 1
            continue

        r["text"]       = text_clean
        r["word_count"] = wc
        cleaned.append(r)
        stats["kept"] += 1

    print(f"  Dropped (bad domain):  {stats['dropped_domain']:>7,}")
    print(f"  Dropped (error page):  {stats['dropped_error']:>7,}")
    print(f"  Dropped (short/dedup): {stats['dropped_short']:>7,}")

    # ── Write ──
    print(f"\nWriting {len(cleaned):,} articles → {OUTPUT_CSV}")
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(cleaned)

    print(f"\n{'='*50}")
    print(f"Master corpus: {stats['kept']:,} articles")

    # Source breakdown
    from collections import Counter
    src_counts = Counter(r["source_file"] for r in cleaned)
    for src, cnt in src_counts.most_common():
        print(f"  {cnt:>8,}  {src}")

    # Domain breakdown (top 20)
    print("\nTop 20 domains:")
    dom_counts = Counter(r["domain"] for r in cleaned)
    for dom, cnt in dom_counts.most_common(20):
        print(f"  {cnt:>8,}  {dom}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Merge and clean all article sources.")
    parser.add_argument("--min-words", type=int, default=MIN_WORDS_DEFAULT)
    parser.add_argument("--no-intl", action="store_true",
                        help="Exclude international_articles.csv")
    args = parser.parse_args()
    main(min_words=args.min_words, include_intl=not args.no_intl)
