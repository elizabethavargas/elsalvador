"""
collect_hf_news.py — Download and filter Salvadoran news datasets from HuggingFace
(user justinian336), merge into one CSV, deduplicate.

SOURCES:
  justinian336/salvadoran-news-elmundo  — diario.elmundo.sv, 47k rows, has date+category
  justinian336/salvadoran-news-edh      — eldiariodehoy.com, 55k rows, has category
  justinian336/salvadoran-news-elsalvadorgram — elsalvadorgram.com, 2k rows, has category
  justinian336/salvadoran-news          — mixed (diario.elmundo.sv + elsalvador.com +
                                          historico.elsalvador.com), 103k rows, no date
  justinian336/news-and-blogs           — mixed, 3k rows, no category/link

NOTE: salvadoran-news is an aggregation that overlaps heavily with the individual
datasets above. Loading the individual datasets first preserves their richer
date/category metadata when dedup runs.

OUTPUT: output/hf_news.csv
  columns: source, title, content, date, url, category

USAGE:
  python3 collect/collect_hf_news.py
"""

import csv
import os
import re
from collections import Counter
from urllib.parse import urlparse

REPO_ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_CSV = os.path.join(REPO_ROOT, "output", "hf_news.csv")

MIN_CONTENT_WORDS = 30

# ─────────────────────────────────────────────
# CATEGORY FILTERS
# ─────────────────────────────────────────────

# diario.elmundo.sv category labels
ELMUNDO_KEEP = {"Editorial", "Nacionales", "Confidencial", "Politica", "Economia"}
ELMUNDO_SKIP = {"Guia Mundialista", "Tecnomundo"}

# eldiariodehoy.com category labels
EDH_KEEP = {"noticias", "opinion", "opinion/caricaturas"}
EDH_SKIP = {"deportes", "deportes/zona-mundialista", "entretenimiento",
            "vida", "videos", "fotogalerias", "null"}

# elsalvadorgram.com category labels
ELSALVADORGRAM_KEEP = {"Nacional", "Economía", "Negocios", "Política"}
ELSALVADORGRAM_SKIP = {"Internacional", "Arte y Cultura", "Espectáculos", "Trends",
                       "Tips", "Deportes", "Cine y TV", "Turismo"}

# URL path segments to skip for the undifferentiated salvadoran-news dataset
SKIP_URL_SEGMENTS = {
    "deportes", "sports", "entretenimiento", "entertainment",
    "internacional", "international", "espectaculos", "farandula",
    "cine", "musica", "television", "moda", "estilo", "lifestyle",
    "horoscopo", "recetas", "viajes", "turismo", "salud-y-vida",
    "tecnologia", "guia-mundialista",
}
KEEP_URL_SEGMENTS = {
    "nacional", "nacionales", "politica", "economia", "negocios",
    "opinion", "judicial", "seguridad", "comunidades", "sociedad",
    "medio-ambiente",
}


def url_is_relevant(url: str):
    """
    True  → URL path signals politics/economy/nacional
    False → URL path signals sports/entertainment/etc.
    None  → ambiguous; caller includes by default
    """
    if not url:
        return None
    try:
        path = urlparse(url).path.lower()
    except Exception:
        return None
    segments = set(re.split(r"[/\-_]", path))
    if segments & SKIP_URL_SEGMENTS:
        return False
    if segments & KEEP_URL_SEGMENTS:
        return True
    return None


def domain_from_url(url: str) -> str:
    """Extract bare domain (no www.) from a URL."""
    try:
        netloc = urlparse(url).netloc.lower()
        return re.sub(r"^www\.", "", netloc)
    except Exception:
        return ""


def word_count(text: str) -> int:
    return len(text.split()) if text else 0


def normalize_title(title: str) -> str:
    return re.sub(r"[^\w\s]", "", title.lower()).strip()


# ─────────────────────────────────────────────
# LOADERS  (order matters — first in wins dedup)
# ─────────────────────────────────────────────

def load_elmundo():
    """diario.elmundo.sv — has date + category. Load first to preserve metadata."""
    print("[load] salvadoran-news-elmundo (diario.elmundo.sv) ...")
    from datasets import load_dataset
    ds = load_dataset("justinian336/salvadoran-news-elmundo", split="train")
    cat_feature = ds.features["category"]
    rows, skipped = [], 0
    for r in ds:
        cat_int = r.get("category")
        cat_str = cat_feature.int2str(cat_int) if cat_int is not None else ""
        if cat_str not in ELMUNDO_KEEP:
            skipped += 1
            continue
        content = r.get("content") or ""
        if word_count(content) < MIN_CONTENT_WORDS:
            skipped += 1
            continue
        rows.append({
            "source":   "diario.elmundo.sv",
            "title":    (r.get("title") or "").strip(),
            "content":  content.strip(),
            "date":     (r.get("date") or "").strip(),
            "url":      (r.get("link") or "").strip(),
            "category": cat_str,
        })
    print(f"  {len(rows):,} kept, {skipped:,} skipped")
    return rows


def load_edh():
    """elsalvador.com (El Diario de Hoy) — HF dataset is from www.elsalvador.com.
    'edh' = El Diario de Hoy; their website domain is elsalvador.com."""
    print("[load] salvadoran-news-edh (elsalvador.com / El Diario de Hoy) ...")
    from datasets import load_dataset
    ds = load_dataset("justinian336/salvadoran-news-edh", split="train")
    cat_feature = ds.features["category"]
    rows, skipped = [], 0
    for r in ds:
        cat_int = r.get("category")
        cat_str = cat_feature.int2str(cat_int) if cat_int is not None else ""
        if cat_str not in EDH_KEEP:
            skipped += 1
            continue
        content = r.get("content") or ""
        if word_count(content) < MIN_CONTENT_WORDS:
            skipped += 1
            continue
        # Derive source from actual URL domain; fall back to elsalvador.com
        url = (r.get("link") or "").strip()
        domain = domain_from_url(url) or "elsalvador.com"
        rows.append({
            "source":   domain,
            "title":    (r.get("title") or "").strip(),
            "content":  content.strip(),
            "date":     "",
            "url":      (r.get("link") or "").strip(),
            "category": cat_str,
        })
    print(f"  {len(rows):,} kept, {skipped:,} skipped")
    return rows


def load_elsalvadorgram():
    """elsalvadorgram.com — has category."""
    print("[load] salvadoran-news-elsalvadorgram ...")
    from datasets import load_dataset
    ds = load_dataset("justinian336/salvadoran-news-elsalvadorgram", split="train")
    cat_feature = ds.features["category"]
    rows, skipped = [], 0
    for r in ds:
        cat_int = r.get("category")
        cat_str = cat_feature.int2str(cat_int) if cat_int is not None else ""
        if cat_str not in ELSALVADORGRAM_KEEP:
            skipped += 1
            continue
        content = r.get("content") or ""
        if word_count(content) < MIN_CONTENT_WORDS:
            skipped += 1
            continue
        rows.append({
            "source":   "elsalvadorgram.com",
            "title":    (r.get("title") or "").strip(),
            "content":  content.strip(),
            "date":     "",
            "url":      (r.get("link") or "").strip(),
            "category": cat_str,
        })
    print(f"  {len(rows):,} kept, {skipped:,} skipped")
    return rows


def load_salvadoran_news():
    """Aggregated dataset. Use actual URL domain as source. Load AFTER individual
    datasets so richer metadata wins on dedup."""
    print("[load] salvadoran-news (mixed: elmundo + elsalvador.com + historico) ...")
    from datasets import load_dataset
    ds = load_dataset("justinian336/salvadoran-news", split="train")
    rows, skipped = [], 0
    for r in ds:
        url = (r.get("link") or "").strip()
        relevant = url_is_relevant(url)
        if relevant is False:
            skipped += 1
            continue
        content = r.get("content") or ""
        if word_count(content) < MIN_CONTENT_WORDS:
            skipped += 1
            continue
        source = domain_from_url(url) or "unknown"
        rows.append({
            "source":   source,
            "title":    (r.get("title") or "").strip(),
            "content":  content.strip(),
            "date":     "",
            "url":      url,
            "category": "",
        })
    print(f"  {len(rows):,} kept, {skipped:,} skipped")
    return rows


def load_news_and_blogs():
    """Mixed, no category or URL. Include all that meet length threshold."""
    print("[load] news-and-blogs ...")
    from datasets import load_dataset
    ds = load_dataset("justinian336/news-and-blogs", split="train")
    rows, skipped = [], 0
    for r in ds:
        content = r.get("content") or ""
        if word_count(content) < MIN_CONTENT_WORDS:
            skipped += 1
            continue
        rows.append({
            "source":   "news-and-blogs",
            "title":    (r.get("title") or "").strip(),
            "content":  content.strip(),
            "date":     "",
            "url":      "",
            "category": "",
        })
    print(f"  {len(rows):,} kept, {skipped:,} skipped")
    return rows


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    print("=" * 60)
    print("Collecting HuggingFace Salvadoran news datasets")
    print("=" * 60)
    print()

    # Order matters: individual datasets (with metadata) come first
    all_rows = []
    all_rows.extend(load_elmundo())
    all_rows.extend(load_edh())
    all_rows.extend(load_elsalvadorgram())
    all_rows.extend(load_salvadoran_news())   # aggregated — goes last
    all_rows.extend(load_news_and_blogs())

    print(f"\nTotal before dedup: {len(all_rows):,}")

    # Deduplicate — first occurrence (richest metadata) wins
    seen_urls:   set = set()
    seen_titles: set = set()
    deduped = []
    dup_url = dup_title = 0

    for row in all_rows:
        url = row["url"].strip()
        if url:
            if url in seen_urls:
                dup_url += 1
                continue
            seen_urls.add(url)

        nt = normalize_title(row["title"])
        if nt and nt in seen_titles:
            dup_title += 1
            continue
        if nt:
            seen_titles.add(nt)

        deduped.append(row)

    print(f"Removed {dup_url:,} URL dups + {dup_title:,} title dups")
    print(f"Final:  {len(deduped):,} articles")

    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    fieldnames = ["source", "title", "content", "date", "url", "category"]
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(deduped)
    print(f"\nSaved → {OUTPUT_CSV}")

    # Summary
    source_counts = Counter(r["source"] for r in deduped)
    print("\nPer source (final):")
    for src, n in sorted(source_counts.items(), key=lambda x: -x[1]):
        print(f"  {src:<40} {n:>7,}")

    with_date = sum(1 for r in deduped if r["date"])
    with_cat  = sum(1 for r in deduped if r["category"])
    print(f"\n  {with_date:,} articles have a date field")
    print(f"  {with_cat:,}  articles have a category field")


if __name__ == "__main__":
    main()
