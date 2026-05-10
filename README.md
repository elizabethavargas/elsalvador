# Governing Through Narrative: Framing Analysis of Salvadoran Political Discourse (2015–2025)

**Live website:** [https://el-salvador-news.netlify.app/](https://el-salvador-news.netlify.app/)

**Report:** [paper/governing_through_narrative.docx](paper/governing_through_narrative.docx)

**GitHub repository:** [https://github.com/elizabethavargas/elsalvador](https://github.com/elizabethavargas/elsalvador)

---

## Project Overview

This project analyzes ten years of Spanish-language political communication in El Salvador (2015–2025), comparing how the Bukele government frames key events on social media versus how independent media covers those same events. The corpus includes ~162,000 government tweets from five official accounts and ~140,000+ news articles from six Salvadoran outlets. Analyses cover distinctive vocabulary, event-specific framing, rhetoric patterns, and rhetorical shifts over time.

---

## Replication Package

### Prerequisites

- Python 3.10+
- Install dependencies:

```bash
pip install -r requirements.txt
```

Additionally, for word cloud generation:

```bash
pip install wordcloud matplotlib
```

For paper generation:

```bash
pip install python-docx
```

### Data

All input data files are included in the `output/` directory:

| File | Description |
|------|-------------|
| `output/articles_master.csv` | ~140k+ news articles from 6 Salvadoran outlets (2015–2025) |
| `output/el_salvador_political_dataset.csv` | Government press releases and transcripts (Presidencia, Asamblea) |
| `output/articles_text_clean.csv` | Cleaned article text used in analysis |
| `collect/twitter_collector.py` | Script to re-collect tweets (requires X/Twitter API credentials in `.env`) |

Twitter data requires API credentials. Set `BEARER_TOKEN` in a `.env` file:

```
BEARER_TOKEN=your_token_here
```

---

### Step 1 — Collect data (optional, data already included)

| Script | What it does | Output |
|--------|--------------|--------|
| `collect/scrape_government.py` | Scrapes press releases from presidencia.gob.sv and asamblea.gob.sv | `output/el_salvador_political_dataset.csv` |
| `collect/gdelt.py` | Collects article URLs from GDELT API using political search terms | `output/gdelt_urls.csv` |
| `collect/scrape_articles.py` | Fetches full article text from URL lists | `output/articles_text.csv` |
| `collect/scrape_new_outlets.py` | Scrapes additional Salvadoran news outlets | `output/new_outlets_articles.csv` |
| `collect/twitter_collector.py` | Collects tweets from 5 official government accounts via X API | (requires API key) |

### Step 2 — Run analyses

All analysis scripts read from `output/` and write interactive HTML charts to `website/viz/` and PNGs to `paper/`.

```bash
# Distinctive vocabulary by source (log-odds ratio)
python analyze/word_prevalence.py

# Event-specific framing: word clouds + butterfly chart
python analyze/event_framing.py

# Bukele rhetoric patterns: targets, strategies, volume over time
python analyze/bukele_critics.py

# Topic modeling across corpus
python analyze/topic_modeling.py

# N-gram comparison between government and press
python analyze/ngram_comparison.py

# Article-level content analysis
python analyze/article_analysis.py

# Public engagement metrics
python analyze/public_metrics.py
```

### Step 3 — Build the paper

```bash
python paper/build_paper.py
# Output: paper/governing_through_narrative.docx
```

---

## Directory Structure

```
├── README.md                          # This file
├── requirements.txt                   # Python dependencies
├── config.py                          # Political keywords, event timeline
├── cleaning.py                        # Shared HTML extraction and text normalization
├── utils.py                           # HTTP helpers, date parsing
│
├── collect/                           # Data collection scripts
│   ├── twitter_collector.py           # X/Twitter API collector (5 govt accounts)
│   ├── scrape_government.py           # Presidencia + Asamblea press releases
│   ├── gdelt.py                       # GDELT URL collection
│   ├── scrape_articles.py             # Full-text article scraper
│   ├── scrape_new_outlets.py          # Additional Salvadoran outlets
│   ├── scrape_international.py        # International coverage
│   └── clean_articles.py             # Post-scrape cleaning
│
├── analyze/                           # Analysis scripts
│   ├── event_framing.py              # Word clouds + butterfly chart by event
│   ├── word_prevalence.py            # Log-odds distinctive vocabulary
│   ├── bukele_critics.py             # Rhetoric targets, strategies, volume
│   ├── topic_modeling.py             # BERTopic / sklearn topic modeling
│   ├── ngram_comparison.py           # N-gram analysis govt vs. press
│   ├── article_analysis.py           # Article-level content analysis
│   ├── rhetoric_analysis.py          # Rhetorical framing categories
│   └── public_metrics.py            # Engagement and reach metrics
│
├── output/                            # Data files (inputs to analysis)
│   ├── articles_master.csv           # ~140k+ news articles (main corpus)
│   ├── el_salvador_political_dataset.csv  # Govt press releases
│   ├── articles_text_clean.csv       # Cleaned text for analysis
│   └── [intermediate files]
│
├── paper/                             # Report
│   ├── governing_through_narrative.docx  # Final paper
│   ├── build_paper.py                # Script to regenerate .docx
│   └── wc_*.png                      # Word cloud figures embedded in paper
│
└── website/                           # Interactive website
    ├── index.html                     # Main site (deployed to Netlify)
    ├── viz/                           # Interactive Plotly visualizations
    │   ├── event_framing_butterfly.html
    │   ├── event_framing_wordclouds.html
    │   ├── tweets_heatmap.html
    │   ├── bukele_volume.html
    │   ├── bukele_strategies.html
    │   ├── bukele_critics_heatmap.html
    │   ├── tweets_distinctive.html
    │   ├── media_distinctive.html
    │   └── [additional charts]
    └── paper/
        └── governing_through_narrative.docx  # Paper served from site
```

---

## Corpus Description

| Source | Type | Count | Years |
|--------|------|-------|-------|
| @nayibbukele, @PresidenciaSV, @AsambleaSV, @MH_SV, @PolicíaSV | Government tweets | ~162,000 | 2015–2025 |
| elfaro.net, elsalvador.com, laprensagrafica.com, diariocolatino.com, lapagina.com.sv, gatoencerrado.net | News articles | ~140,000+ | 2015–2025 |

All text is in Spanish. Analyses use log-odds ratio (Monroe, Colaresi & Quinn 2008) with Dirichlet prior smoothing, normalized per 1,000 tokens to control for format-driven length differences between tweets and articles.

---

## Key Political Events

| Date | Event |
|------|-------|
| 2019-02 | Bukele wins presidency |
| 2019-06 | Inauguration |
| 2020-02 | Military enters Asamblea |
| 2020-03 | COVID emergency declared |
| 2021-02 | Nuevas Ideas supermajority |
| 2021-05 | Supreme Court justices removed |
| 2021-06 | Bitcoin Law approved |
| 2021-09 | Bitcoin becomes legal tender |
| 2022-03 | State of exception declared (gang crackdown) |
| 2023-11 | CECOT mega-prison opens |
| 2024-02 | Bukele reelected |
| 2024-06 | Second term inaugurated |
