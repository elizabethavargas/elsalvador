"""
scrape_government.py — Scrape press releases and documents from Salvadoran
government websites via their XML sitemaps.

Sources:
  - presidencia.gob.sv  (press releases, speeches)
  - asamblea.gob.sv     (legislative records)
  - rrees.gob.sv        (foreign affairs)
  - fiscalia.gob.sv     (attorney general)

OUTPUT: output/government_articles.csv
Safe to cancel and resume — already-scraped URLs are skipped on re-run.

USAGE:
  python scrape_government.py
  python scrape_government.py --limit 200   # test run
"""

import argparse
import csv
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import date

import requests

# Allow imports of shared helpers (config, utils, cleaning) from project root
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cleaning
import utils

# ─────────────────────────────────────────────
# GOVERNMENT SOURCES
# ─────────────────────────────────────────────
SOURCES = [
    {
        "name":    "Presidencia de El Salvador",
        "sitemap": "https://www.presidencia.gob.sv/sitemap.xml",
        "delay":   2.5,
    },
    {
        "name":    "Asamblea Legislativa",
        "sitemap": "https://www.asamblea.gob.sv/sitemap.xml",
        "delay":   2.5,
    },
    {
        "name":    "Ministerio de Relaciones Exteriores",
        "sitemap": "https://www.rrees.gob.sv/sitemap.xml",
        "delay":   2.5,
    },
    {
        "name":    "Fiscalía General",
        "sitemap": "https://www.fiscalia.gob.sv/sitemap.xml",
        "delay":   2.5,
    },
]

START_YEAR = 2015
END_YEAR   = 2025
OUTPUT_CSV = os.path.join("output", "government_articles.csv")
OUTPUT_FIELDS = ["url", "source_name", "title", "text", "date",
                 "year", "month", "word_count"]

# ─────────────────────────────────────────────
# SITEMAP PARSING
# ─────────────────────────────────────────────
def _parse_sitemap(url, delay, depth=0):
    """Recursively fetch URLs from an XML sitemap or sitemap index."""
    if depth > 3:
        return []
    resp = utils.rate_limited_get(url, delay=delay)
    if resp is None:
        return []
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        return []

    ns_match = re.match(r"\{[^}]+\}", root.tag)
    ns = ns_match.group(0) if ns_match else ""

    # Sitemap index — recurse into each child sitemap
    if root.findall(f"{ns}sitemap"):
        entries = []
        for sm in root.findall(f"{ns}sitemap"):
            loc = sm.find(f"{ns}loc")
            if loc is not None and loc.text:
                entries.extend(_parse_sitemap(loc.text.strip(), delay, depth + 1))
        return entries

    # Regular sitemap — collect <url> entries
    entries = []
    for u in root.findall(f"{ns}url"):
        loc     = u.find(f"{ns}loc")
        lastmod = u.find(f"{ns}lastmod")
        if loc is not None and loc.text:
            entries.append({
                "url":     loc.text.strip(),
                "lastmod": lastmod.text.strip() if lastmod is not None and lastmod.text else "",
            })
    return entries


# ─────────────────────────────────────────────
# DATE HELPERS
# ─────────────────────────────────────────────
def _in_range(d):
    return d is not None and date(START_YEAR, 1, 1) <= d <= date(END_YEAR, 12, 31)


# ─────────────────────────────────────────────
# CSV HELPERS
# ─────────────────────────────────────────────
def load_done_urls(path):
    if not os.path.exists(path):
        return set()
    done = set()
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("url"):
                done.add(row["url"])
    print(f"[resume] {len(done):,} URLs already scraped in {path}")
    return done


def init_output(path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=OUTPUT_FIELDS).writeheader()


def append_rows(path, rows):
    if not rows:
        return
    with open(path, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=OUTPUT_FIELDS).writerows(rows)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Scrape Salvadoran government sites.")
    parser.add_argument("--output", default=OUTPUT_CSV)
    parser.add_argument("--limit",  type=int, default=0,
                        help="Max articles per source (0 = all, useful for testing)")
    args = parser.parse_args()

    init_output(args.output)
    done_urls = load_done_urls(args.output)
    total_saved = len(done_urls)

    for src in SOURCES:
        print(f"\n{'='*60}")
        print(f"Source: {src['name']}")
        print(f"Sitemap: {src['sitemap']}")

        # ── Fetch sitemap ──
        entries = _parse_sitemap(src["sitemap"], src["delay"])
        print(f"  {len(entries):,} URLs in sitemap")

        # ── Filter: skip seen, skip non-articles, check date range ──
        candidates = []
        for entry in entries:
            url = entry["url"]
            if url in done_urls:
                continue
            if not utils.is_article_url(url):
                continue
            if not utils.url_passes_prefilter(url, is_government=True):
                continue

            # Use lastmod for date pre-check
            pub_date = None
            if entry["lastmod"]:
                pub_date = utils.parse_date_flexible(entry["lastmod"])
                if pub_date and not _in_range(pub_date):
                    continue

            candidates.append((url, pub_date))

        if args.limit:
            candidates = candidates[:args.limit]

        print(f"  {len(candidates):,} new URLs to fetch")

        batch = []
        saved_this_source = 0

        for i, (url, known_date) in enumerate(candidates, 1):
            resp = utils.rate_limited_get(url, delay=src["delay"])
            if resp is None or len(resp.text) < 500:
                continue

            html  = resp.text
            title = cleaning.extract_title_from_html(html) or ""
            text  = cleaning.extract_article_content(html)

            if len(text.strip()) < 150:
                continue

            # Resolve date
            pub_date = known_date
            if pub_date is None:
                raw = cleaning.extract_date_from_html(html)
                if raw:
                    pub_date = utils.parse_date_flexible(raw)
            if pub_date is None:
                pub_date = utils.extract_date_from_url(url)
            if pub_date and not _in_range(pub_date):
                continue

            batch.append({
                "url":         url,
                "source_name": src["name"],
                "title":       title[:400],
                "text":        text,
                "date":        pub_date.isoformat() if pub_date else "",
                "year":        str(pub_date.year) if pub_date else "",
                "month":       f"{pub_date.month:02d}" if pub_date else "",
                "word_count":  len(text.split()),
            })
            done_urls.add(url)
            total_saved  += 1
            saved_this_source += 1

            # Flush every 25 articles
            if len(batch) >= 25:
                append_rows(args.output, batch)
                batch = []

            if i % 50 == 0:
                print(f"  [{i}/{len(candidates)}] saved={saved_this_source}")

        append_rows(args.output, batch)
        print(f"  Done: {saved_this_source} articles saved from {src['name']}")

    print(f"\nTotal saved: {total_saved:,} → {args.output}")


if __name__ == "__main__":
    main()
