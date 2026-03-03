# El Salvador Political Text Dataset Builder (2015–2025)

Collects thousands of **politically relevant** Spanish-language texts from live Salvadoran websites. Designed for temporal NLP analysis mapped against key political events.

## What Gets Collected (and What Doesn't)

**INCLUDED:** National politics, governance, legislative actions, elections, party news, security policy, economic policy, corruption, protests, constitutional changes, human rights, opinion/editorial on any of these. Government press releases are always included.

**EXCLUDED:** Sports, entertainment, lifestyle, local crime without political context, horoscopes, recipes, classifieds. Articles without extractable dates are dropped.

Each article is scored against ~100 political keywords. Articles must hit a minimum relevance threshold (default: 2 keyword matches in title + first 1500 chars) to be kept. Government sources skip this filter.

## New in This Version

| Feature | Description |
|---------|-------------|
| **Political filter** | ~40 strong keywords (2 pts) + ~60 normal keywords (1 pt). Threshold: 2+ |
| **Engagement metrics** | Extracts `comment_count`, `like_count`, `share_count`, `view_count` from JSON-LD, meta tags, CSS selectors, data attributes |
| **Strict dates** | Multi-layer extraction (meta → JSON-LD → `<time>` → visible text → URL path). No date = dropped |
| **Event tagging** | Each article tagged with `nearest_event` and `days_from_event` (negative = before, positive = after) from a 20-event political timeline |

## Quick Start

```bash
pip install -r requirements.txt
python -m spacy download es_core_news_sm   # optional

python main.py --dry-run         # verify setup
python main.py --strategies 1    # quick test (GDELT)
python main.py                   # full run
```

## Output Schema

| Column | Description |
|--------|-------------|
| `id` | Unique ID |
| `date` | ISO date (ALWAYS present — strict enforcement) |
| `year` / `month` | Extracted from date |
| `source_type` | `government` or `news` |
| `source_name` | Full outlet name |
| `speaker` | Auto-detected (Bukele, Sánchez Cerén, Funes, etc.) |
| `title` | Article title |
| `text` | Cleaned full text (Spanish accents preserved) |
| `url` | Live source URL |
| `word_count` | Word count |
| `comment_count` | Comment count (if available on page) |
| `like_count` | Like/reaction count (if available) |
| `share_count` | Share count (if available) |
| `view_count` | View count (if available) |
| `nearest_event` | Closest key political event |
| `days_from_event` | Days from that event (- = before, + = after) |
| `mentions_bukele` | Boolean flag |
| `has_corruption_keyword` | Boolean flag |
| `corruption_keywords_matched` | Matched terms |

## Key Events Timeline (20 events)

The dataset maps every article to its nearest event from this timeline:

- 2015-03: Legislative elections
- 2019-02: Bukele wins presidency
- 2019-06: Bukele inaugurated
- 2020-02: Military enters Asamblea
- 2020-03: COVID emergency
- 2021-02: Nuevas Ideas supermajority
- 2021-05: Supreme Court justices removed
- 2021-06: Bitcoin Law approved
- 2021-09: Bitcoin legal tender / reelection ruling
- 2022-03: State of exception (gang crackdown)
- 2023-11: CECOT mega-prison opens
- 2024-02: Bukele reelected
- 2024-06: Second term inauguration

## Architecture

```
├── main.py           CLI entry point
├── config.py         Sources, keywords, events, engagement selectors
├── scrapers.py       6 strategies + relevance filter + date enforcement
├── cleaning.py       HTML extraction, text normalization
├── enrichment.py     NER, Bukele flag, corruption keywords
├── utils.py          HTTP, relevance scorer, engagement parser, event tagger
```
