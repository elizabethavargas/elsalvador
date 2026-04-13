"""
clean_articles.py — Clean output/articles_text.csv, removing 404/error pages
and stripping scraper boilerplate from surviving article text.

WHAT IT DOES:
  1. Drops entire domains known to be all-404 (elmundo.sv)
  2. Drops articles whose title or first 200 chars match 404/error patterns
  3. Strips common boilerplate from the start/end of article text:
       - Section/category header lines
       - "por\n\nRedacción …\nhace N días\n0\n" byline blocks
       - Trailing nav/social/cookie footers
  4. Drops articles with fewer than MIN_WORDS after cleaning
  5. Recalculates word_count

OUTPUT: output/articles_text_clean.csv  (same columns as input)

USAGE:
  python3 collect/clean_articles.py
  python3 collect/clean_articles.py --min-words 60
"""

import argparse
import csv
import os
import re
import sys

REPO_ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_CSV  = os.path.join(REPO_ROOT, "output", "articles_text.csv")
OUTPUT_CSV = os.path.join(REPO_ROOT, "output", "articles_text_clean.csv")

MIN_WORDS_DEFAULT = 30  # applied to RAW word_count so header words still count

# Domains where every article is a 404 / fully broken — drop entirely
DROP_DOMAINS = {"elmundo.sv"}

# Patterns in the title or first 200 chars of text that signal a 404/error page
ERROR_PATTERNS = [
    r"404",
    r"not found",
    r"no encontramos",
    r"p[aá]gina.{0,20}(no existe|que buscas)",
    r"page not found",
    r"javascript (is )?required",
    r"cookies? (are )?required",
    r"access denied",
    r"forbidden",
]
ERROR_RE = re.compile("|".join(ERROR_PATTERNS), re.IGNORECASE)

# ─────────────────────────────────────────────────────
# TEXT CLEANING
# ─────────────────────────────────────────────────────

# Leading boilerplate: section label + duplicate title + byline block.
# Handles both forms:
#   "Nacionales\n\nTitle\npor\n\nRedacción …\nhace 3 meses\n0\n<content>"
#   "Opinión – Sitio\nOpinión\n\nOpinión\n\nTitle\npor\n\nAuthor\nhace 2 meses\n\n<content>"
_BYLINE_BLOCK = re.compile(
    r"^.*?\npor\s*\n\s*[^\n]+\n"           # everything up to "por\n\nauthor\n"
    r"[^\n]*(hace|published|publicado)[^\n]*\n"  # "hace N meses/días" line
    r"(\d+\n)?",                            # optional comment-count line
    re.IGNORECASE | re.DOTALL,
)
# Simpler leading section header: one short word/phrase followed by a blank line
_SECTION_HEADER = re.compile(r"^\s*[A-ZÁÉÍÓÚÑ][^\n]{0,40}\n\n", re.UNICODE)

# Trailing boilerplate footers (social share prompts, cookie notices, etc.)
_FOOTER_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\n(compartir|share)\s*$",
        r"\n(suscr[ií]bete|subscribe)[^\n]*$",
        re.escape("©"),
        r"\ntodos los derechos reservados",
        r"\n(cookies?|privacidad|privacy)[^\n]*$",
        r"\n(ver m[aá]s|read more|continue reading)[^\n]*$",
        r"\nir al inicio[^\n]*$",
    ]
]


def clean_text(raw: str) -> str:
    text = raw

    # Fix common mojibake from latin-1/utf-8 confusion
    try:
        text = text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass

    # Strip leading byline block (section + title + por/Redacción/hace N días/0)
    m = _BYLINE_BLOCK.match(text)
    if m:
        text = text[m.end():]
    else:
        # Fallback: strip a single-line section header if present
        m2 = _SECTION_HEADER.match(text)
        if m2:
            text = text[m2.end():]

    # Strip trailing boilerplate
    for pat in _FOOTER_PATTERNS:
        text = pat.sub("", text)

    # Collapse excessive whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    return text


def word_count(text: str) -> int:
    return len(text.split())


# ─────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────
def main(min_words: int = MIN_WORDS_DEFAULT):
    stats = {
        "read": 0,
        "dropped_domain": 0,
        "dropped_error":  0,
        "dropped_short":  0,
        "kept":           0,
    }

    with open(INPUT_CSV, encoding="utf-8-sig", errors="replace") as fin, \
         open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as fout:

        reader = csv.DictReader(fin)
        writer = csv.DictWriter(fout, fieldnames=reader.fieldnames)
        writer.writeheader()

        for row in reader:
            stats["read"] += 1
            domain = row.get("domain", "").strip()

            # 1. Drop known all-404 domains
            if domain in DROP_DOMAINS:
                stats["dropped_domain"] += 1
                continue

            # 2. Drop error pages detected by pattern
            title = row.get("title", "")
            text  = row.get("text", "")
            probe = (title + " " + text[:200]).lower()
            if ERROR_RE.search(probe):
                stats["dropped_error"] += 1
                continue

            # 3. Drop articles that were too short even before cleaning
            raw_wc = int(row.get("word_count") or 0)
            if raw_wc < min_words:
                stats["dropped_short"] += 1
                continue

            # 4. Clean text and update word count
            cleaned = clean_text(text)
            row["text"]       = cleaned
            row["word_count"] = word_count(cleaned)
            writer.writerow(row)
            stats["kept"] += 1

    print(f"Input:              {stats['read']:>7,} articles")
    print(f"Dropped (domain):   {stats['dropped_domain']:>7,}  "
          f"({', '.join(DROP_DOMAINS)})")
    print(f"Dropped (error pg): {stats['dropped_error']:>7,}")
    print(f"Dropped (<{min_words} words): {stats['dropped_short']:>7,}")
    print(f"─────────────────────────────")
    print(f"Kept:               {stats['kept']:>7,}  → {OUTPUT_CSV}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-words", type=int, default=MIN_WORDS_DEFAULT,
                        help=f"Drop articles shorter than N words after cleaning "
                             f"(default: {MIN_WORDS_DEFAULT})")
    args = parser.parse_args()
    main(args.min_words)
