# El Salvador Political Text Dataset (2015–2025)

Spanish-language political texts from Salvadoran government and news sources, designed for NLP analysis mapped against key political events.

## Dataset Sources

The final dataset is built from three sources:

| # | Source | Script | Status |
|---|--------|--------|--------|
| 1 | **Government sites** (Presidencia, Asamblea) | `scrape_government.py` | ✅ 6,574 articles scraped |
| 2 | **News sites via GDELT** | `GDELT.py` → `scrape_articles.py` | 🔄 13,399 URLs collected, text pending |
| 3 | **Government tweets** | *(future)* | ⏳ Not started |

---

## Workflow

### Source 1 — Government sites

The government scraper pulls press releases and transcripts from `presidencia.gob.sv` and `asamblea.gob.sv` via their XML sitemaps and monthly archives.

```bash
python scrape_government.py
# Output: output/el_salvador_political_dataset.csv
```

### Source 2 — GDELT news articles (two steps)

**Step 2a — Collect URLs from GDELT API:**

```bash
python GDELT.py
# Output: gdelt_urls.csv
# Safe to cancel and resume — progress saved in gdelt_progress.json
```

`GDELT.py` queries the GDELT Doc API using 20 focused political search terms
(`sourcecountry:ES "Bukele"`, `"estado de excepcion"`, etc.) across weekly
time windows (2018–2025). Max 250 results per query.

**Step 2b — Fetch full article text:**

```bash
python scrape_articles.py                          # uses gdelt_urls.csv by default
python scrape_articles.py --input my_urls.csv      # or any CSV with a 'url' column
python scrape_articles.py --workers 10             # more threads = faster
python scrape_articles.py --limit 500              # test with 500 URLs first
# Output: articles_text.csv
# Safe to cancel and resume — already-scraped URLs are skipped
```

`scrape_articles.py` also accepts URLs from other sources (e.g. a BigQuery export).
Just provide any CSV that has a `url` column; extra columns are carried through.

### Source 3 — Government tweets *(future)*

Will cover official Twitter/X accounts of Presidencia, Asamblea, Bukele, etc.

---

## Output Schema

### Government + GDELT articles (`el_salvador_political_dataset.csv`, `articles_text.csv`)

| Column | Description |
|--------|-------------|
| `url` | Source URL |
| `date` / `year` / `month` | Publication date |
| `source_type` | `government` or `news` |
| `source_name` | Outlet name |
| `title` | Article title |
| `text` | Cleaned full text (Spanish accents preserved) |
| `word_count` | Word count |
| `speaker` | Auto-detected (Bukele, Sánchez Cerén, etc.) |
| `nearest_event` | Closest key political event |
| `days_from_event` | Days from that event (negative = before) |
| `mentions_bukele` | Boolean |
| `has_corruption_keyword` | Boolean |

### GDELT URL list (`gdelt_urls.csv`)

| Column | Description |
|--------|-------------|
| `url` | Article URL |
| `year` / `month` | From GDELT seendate |
| `title` | Title from GDELT index |
| `domain` | Source domain |
| `query_term` | Which GDELT query found it |

---

## Key Political Events Timeline

Articles are tagged with the nearest event and days-from-event:

| Date | Event |
|------|-------|
| 2015-03 | Legislative elections |
| 2019-02 | Bukele wins presidency |
| 2019-06 | Bukele inaugurated |
| 2020-02 | Military enters Asamblea |
| 2020-03 | COVID emergency |
| 2021-02 | Nuevas Ideas supermajority |
| 2021-05 | Supreme Court justices removed |
| 2021-06 | Bitcoin Law approved |
| 2021-09 | Bitcoin becomes legal tender; reelection ruling |
| 2022-03 | State of exception (gang crackdown) |
| 2023-11 | CECOT mega-prison opens |
| 2024-02 | Bukele reelected |
| 2024-06 | Second term inauguration |

---

## Installation

```bash
pip install -r requirements.txt
```

---

## File Structure

```
├── scrape_government.py   # Step 1: scrape government sites (Presidencia, Asamblea, etc.)
├── GDELT.py               # Step 2a: collect article URLs from GDELT API
├── scrape_articles.py     # Step 2b: fetch full text from any URL CSV
│
├── cleaning.py            # Shared HTML extraction and text normalization
├── config.py              # Political keywords, event timeline, source lists
├── utils.py               # HTTP, date parsing, URL pre-filtering
├── requirements.txt
│
├── gdelt_urls.csv         # URLs collected by GDELT.py
├── gdelt_progress.json    # Resume checkpoint for GDELT.py
├── articles_text.csv      # Full text output from scrape_articles.py
│
└── output/
    ├── government_articles.csv             # Output of scrape_government.py
    └── analysis/                           # Corpus stats, term trends
```
