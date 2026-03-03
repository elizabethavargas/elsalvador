#!/usr/bin/env python3
"""
main.py — El Salvador Political Text Dataset Builder (2015–2025)

Features:
- Political relevance filter (only national politics, governance, opinion)
- Engagement metrics extraction (comment_count, like_count, share_count, view_count)
- Strict date enforcement (no date → dropped; designed for event-mapped analysis)
- Key event proximity tagging (nearest_event, days_from_event)
- 6 collection strategies from live websites

Usage:
    python main.py                              # All strategies
    python main.py --strategies 0 1 2           # Sitemaps + GDELT + archives
    python main.py --strategies 1               # GDELT only (fastest test)
    python main.py --skip-enrichment            # Skip NLP
    python main.py --dry-run                    # Check dependencies
"""

import argparse
import json
import os
import sys
from datetime import datetime

import pandas as pd

import config
print(config.__file__)
import scrapers
import enrichment
import utils

logger = utils.logger

CORE_COLUMNS = [
    "id", "date", "year", "month",
    "source_type", "source_name", "speaker",
    "title", "text", "url",
    "language", "word_count", "document_type", "outlet",
    # Engagement
    "comment_count", "like_count", "share_count", "view_count",
    # Event proximity
    "nearest_event", "days_from_event",
]

ENRICHMENT_COLUMNS = [
    "named_entities", "mentions_bukele",
    "has_corruption_keyword", "corruption_keywords_matched", "corruption_keyword_count",
]


def export_csv(records, path):
    if not records:
        return
    cols = CORE_COLUMNS + [c for c in ENRICHMENT_COLUMNS if c in records[0]]
    df = pd.DataFrame(records)
    for col in cols:
        if col not in df.columns:
            df[col] = ""
    df = df[cols]
    df.to_csv(path, index=False, encoding="utf-8-sig")
    logger.info("CSV: %s (%d rows)", path, len(df))


def export_jsonl(records, path):
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            clean = {k: v for k, v in rec.items() if not k.startswith("_")}
            f.write(json.dumps(clean, ensure_ascii=False, default=str) + "\n")
    logger.info("JSONL: %s (%d)", path, len(records))


def print_summary(records):
    if not records:
        print("\n⚠  No records collected.")
        return

    df = pd.DataFrame(records)
    print("\n" + "=" * 70)
    print("DATASET SUMMARY")
    print("=" * 70)
    print(f"  Total records:         {len(df):,}")
    dated = df["date"].astype(bool).sum()
    print(f"  Records with dates:    {dated:,} (100% — undated articles are dropped)")
    if dated:
        valid = df[df["date"] != ""]["date"]
        print(f"  Date range:            {valid.min()} → {valid.max()}")
    print(f"  Unique sources:        {df['source_name'].nunique()}")
    print(f"  Avg word count:        {df['word_count'].mean():,.0f}")
    print(f"  Total words:           {df['word_count'].sum():,}")

    # Engagement stats
    for col in ["comment_count", "like_count", "share_count", "view_count"]:
        if col in df.columns:
            has = df[col].notna().sum()
            if has > 0:
                print(f"  Articles with {col}: {has:,} (avg: {df[col].dropna().mean():,.0f})")

    print("\n  Records by source:")
    for src, cnt in df["source_name"].value_counts().head(15).items():
        print(f"    {src}: {cnt:,}")

    year_counts = df[df["year"] != ""]["year"].value_counts().sort_index()
    if len(year_counts):
        print("\n  Records by year:")
        for year, cnt in year_counts.items():
            bar = "█" * min(cnt // 10, 50)
            print(f"    {year}: {cnt:>5,}  {bar}")

    if "mentions_bukele" in df.columns and df["mentions_bukele"].dtype == bool:
        print(f"\n  Mentioning Bukele:     {df['mentions_bukele'].sum():,}")
    if "has_corruption_keyword" in df.columns and df["has_corruption_keyword"].dtype == bool:
        print(f"  Corruption keywords:   {df['has_corruption_keyword'].sum():,}")

    # Show articles near key events
    if "nearest_event" in df.columns and "days_from_event" in df.columns:
        close = df[df["days_from_event"].notna() & (df["days_from_event"].abs() <= 7)]
        if len(close):
            print(f"\n  Articles within 7 days of a key event: {len(close):,}")
            top_events = close["nearest_event"].value_counts().head(5)
            for evt, cnt in top_events.items():
                print(f"    {evt}: {cnt}")

    print("\n" + "-" * 70)
    print("FIRST 5 ROWS:")
    print("-" * 70)
    preview = ["id", "date", "source_name", "speaker", "title",
               "word_count", "comment_count", "nearest_event"]
    preview = [c for c in preview if c in df.columns]
    pd.set_option("display.max_colwidth", 40)
    pd.set_option("display.width", 140)
    print(df[preview].head(5).to_string(index=False))
    print()


def dry_run():
    print("Dry run — checking dependencies ...\n")
    deps = {"requests": "requests", "bs4": "beautifulsoup4", "pandas": "pandas",
            "tqdm": "tqdm", "feedparser": "feedparser", "lxml": "lxml",
            "dateutil": "python-dateutil"}
    opt = {"newspaper": "newspaper3k", "spacy": "spacy"}

    ok = True
    for mod, pkg in deps.items():
        try:
            __import__(mod)
            print(f"  ✓ {pkg}")
        except ImportError:
            print(f"  ✗ {pkg} — MISSING")
            ok = False
    for mod, pkg in opt.items():
        try:
            __import__(mod)
            print(f"  ✓ {pkg} (optional)")
        except ImportError:
            print(f"  ⚠ {pkg} (optional)")

    print(f"\n  Date range:              {config.START_DATE} → {config.END_DATE}")
    print(f"  Require date:            {config.REQUIRE_DATE}")
    print(f"  Relevance threshold:     {config.RELEVANCE_THRESHOLD} keywords")
    print(f"  Strong keywords:         {len(config.RELEVANCE_KEYWORDS_STRONG)}")
    print(f"  Normal keywords:         {len(config.RELEVANCE_KEYWORDS_NORMAL)}")
    print(f"  Key events tracked:      {len(config.KEY_EVENTS)}")
    print(f"  Engagement selectors:    {sum(len(v) for v in config.ENGAGEMENT_CSS_SELECTORS.values())}")

    print(f"\n  Strategies:")
    for i, (name, _) in enumerate(scrapers.STRATEGIES):
        print(f"    {i}. {name}")

    if ok:
        print("\n✓ Ready.")
    else:
        print("\n✗ Install: pip install -r requirements.txt")
    sys.exit(0)


def parse_args():
    p = argparse.ArgumentParser(
        description="El Salvador Political Text Dataset Builder (2015–2025)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Strategies:
  0 = XML Sitemaps    1 = GDELT API     2 = Date archives
  3 = Keyword search  4 = RSS feeds     5 = newspaper3k

Examples:
  python main.py                        # All
  python main.py --strategies 0 1 2     # Recommended combo
  python main.py --strategies 1         # Quick test
""")
    p.add_argument("--strategies", nargs="+", type=int, default=None)
    p.add_argument("--skip-enrichment", action="store_true")
    p.add_argument("--skip-ner", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--output-dir", type=str, default=None)
    return p.parse_args()


def main():
    args = parse_args()
    if args.output_dir:
        config.OUTPUT_DIR = args.output_dir
        config.RAW_HTML_DIR = os.path.join(args.output_dir, "raw_html")
        config.LOG_DIR = os.path.join(args.output_dir, "logs")
        config.CSV_OUTPUT = os.path.join(args.output_dir, "el_salvador_political_dataset.csv")
        config.JSONL_OUTPUT = os.path.join(args.output_dir, "el_salvador_political_dataset.jsonl")

    if args.dry_run:
        dry_run()

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    os.makedirs(config.RAW_HTML_DIR, exist_ok=True)
    os.makedirs(config.LOG_DIR, exist_ok=True)

    t0 = datetime.now()
    logger.info("=" * 70)
    logger.info("EL SALVADOR POLITICAL TEXT DATASET BUILDER")
    logger.info("Started: %s | Date filter: %s", t0.isoformat(), config.REQUIRE_DATE)
    logger.info("Relevance threshold: %d | Key events: %d",
                config.RELEVANCE_THRESHOLD, len(config.KEY_EVENTS))
    logger.info("=" * 70)

    # COLLECT
    records = scrapers.collect_all(strategies=args.strategies)
    if not records:
        print("\n⚠  No records collected. Check output/logs/scraper.log")
        return

    # ENRICH
    if not args.skip_enrichment:
        records = enrichment.enrich_records(
            records, do_ner=not args.skip_ner, do_bukele=True, do_corruption=True)

    # EXPORT
    export_csv(records, config.CSV_OUTPUT)
    export_jsonl(records, config.JSONL_OUTPUT)

    elapsed = datetime.now() - t0
    print_summary(records)
    print(f"Files:")
    print(f"  CSV:   {config.CSV_OUTPUT}")
    print(f"  JSONL: {config.JSONL_OUTPUT}")
    print(f"  Logs:  {os.path.join(config.LOG_DIR, 'scraper.log')}")
    print(f"\nElapsed: {elapsed}")


if __name__ == "__main__":
    main()
