"""
scrapers.py — High-volume political text collection from live websites.

KEY CHANGES IN THIS VERSION:
- Political relevance filter: articles must score >= threshold to be kept
- Engagement metrics: extracts comment_count, like_count, share_count, view_count
- Strict date enforcement: articles without extractable dates are DROPPED
- Event proximity tagging: each article tagged with nearest key political event
- Government sources skip the relevance filter (everything is political by definition)
"""

import re
import time
import xml.etree.ElementTree as ET
from datetime import date
from typing import Optional
from urllib.parse import urljoin, quote_plus

from bs4 import BeautifulSoup
from tqdm import tqdm

import config
import cleaning
import utils

logger = utils.logger


# ══════════════════════════════════════════════════════════════
# RECORD BUILDER (with filtering, engagement, date enforcement)
# ══════════════════════════════════════════════════════════════
def _build_record(
    source_key: str,
    source_type: str,
    source_name: str,
    title: str,
    text: str,
    url: str,
    pub_date: Optional[date],
    document_type: str = "news_article",
    speaker: str = "",
    outlet: str = "",
    engagement: Optional[dict] = None,
    skip_relevance_filter: bool = False,
) -> Optional[dict]:
    """
    Build a validated, filtered, enriched record.

    Returns None if:
    - Text is too short (<100 chars)
    - Date is missing and REQUIRE_DATE is True
    - Date is outside 2015-2025
    - Article fails political relevance filter
    """
    if not text or len(text.strip()) < 100:
        return None

    # ── DATE ENFORCEMENT ──
    date_str = year = month = ""
    if pub_date and utils.validate_date(pub_date):
        date_str = pub_date.isoformat()
        year = str(pub_date.year)
        month = str(pub_date.month).zfill(2)
    elif pub_date and not utils.validate_date(pub_date):
        return None  # outside 2015-2025
    elif config.REQUIRE_DATE:
        # Last resort: try extracting date from URL
        url_date = utils.extract_date_from_url(url)
        if url_date and utils.validate_date(url_date):
            pub_date = url_date
            date_str = pub_date.isoformat()
            year = str(pub_date.year)
            month = str(pub_date.month).zfill(2)
        else:
            logger.debug("DROPPED (no date): %s", url)
            return None  # strict mode: no date → drop

    # ── POLITICAL RELEVANCE FILTER ──
    if not skip_relevance_filter and source_type != "government":
        score = utils.compute_relevance_score(title, text)
        if score < config.RELEVANCE_THRESHOLD:
            logger.debug("DROPPED (relevance=%d): %s", score, title[:80])
            return None

    # ── AUTO-DETECT SPEAKER ──
    if not speaker:
        text_lower = (title + " " + text[:500]).lower()
        for pattern, name in config.KEY_SPEAKERS.items():
            if pattern in text_lower:
                speaker = name
                break

    # ── EVENT PROXIMITY ──
    event_info = utils.tag_nearest_event(pub_date) if pub_date else {
        "nearest_event": "", "days_from_event": None
    }

    # ── ENGAGEMENT METRICS ──
    eng = engagement or {}

    return {
        "id": utils.generate_id(source_key),
        "date": date_str,
        "year": year,
        "month": month,
        "source_type": source_type,
        "source_name": source_name,
        "speaker": speaker,
        "title": (title or "")[:500],
        "text": text,
        "url": url,
        "language": "es",
        "word_count": len(text.split()),
        "outlet": outlet,
        "document_type": document_type,
        # Engagement metrics (None if not found)
        "comment_count": eng.get("comment_count"),
        "like_count": eng.get("like_count"),
        "share_count": eng.get("share_count"),
        "view_count": eng.get("view_count"),
        # Event proximity
        "nearest_event": event_info["nearest_event"],
        "days_from_event": event_info["days_from_event"],
    }


def _fetch_and_parse_article(
    url: str,
    source_key: str,
    source_name: str,
    source_type: str,
    document_type: str,
    outlet: str,
    delay: float,
    known_date: Optional[date] = None,
    content_selector: str = "",
    skip_relevance_filter: bool = False,
) -> Optional[dict]:
    """Fetch article, extract text + date + engagement, apply filters, return record."""
    resp = utils.rate_limited_get(url, delay=delay)
    if resp is None:
        return None

    html = resp.text
    if len(html) < 500:
        return None

    utils.save_raw_html(html, source_key, url.split("/")[-1][:80])

    # ── QUICK TITLE CHECK ──
    # Before full extraction, check if title is obviously irrelevant
    title = cleaning.extract_title_from_html(html) or ""
    if title and not skip_relevance_filter and utils.is_politically_irrelevant(title):
        logger.debug("SKIPPED (irrelevant title): %s", title[:80])
        return None

    # ── EXTRACT CONTENT ──
    text = cleaning.extract_article_content(html, content_selector)

    # ── EXTRACT DATE (multi-layer) ──
    pub_date = known_date
    if pub_date is None:
        # Layer 1: HTML metadata
        raw_date = cleaning.extract_date_from_html(html)
        if raw_date:
            pub_date = utils.parse_date_flexible(raw_date)
    if pub_date is None:
        # Layer 2: URL-embedded date
        pub_date = utils.extract_date_from_url(url)

    # ── EXTRACT ENGAGEMENT METRICS ──
    engagement = utils.extract_engagement_metrics(html)

    return _build_record(
        source_key=source_key,
        source_type=source_type,
        source_name=source_name,
        title=title,
        text=text,
        url=url,
        pub_date=pub_date,
        document_type=document_type,
        outlet=outlet,
        engagement=engagement,
        skip_relevance_filter=skip_relevance_filter,
    )


# ══════════════════════════════════════════════════════════════
# GLOBAL URL TRACKER
# ══════════════════════════════════════════════════════════════
_global_seen_urls: set = set()


def _url_seen(url: str) -> bool:
    norm = utils.normalize_url(url)
    if norm in _global_seen_urls:
        return True
    _global_seen_urls.add(norm)
    return False


# ══════════════════════════════════════════════════════════════
# STRATEGY 0: XML SITEMAPS
# ══════════════════════════════════════════════════════════════
def _parse_sitemap(url: str, delay: float, depth: int = 0) -> list:
    if depth > 3:
        return []
    resp = utils.rate_limited_get(url, delay=delay, domain_key="sitemap_" + url[:50])
    if resp is None:
        return []
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        return []

    ns_match = re.match(r"\{[^}]+\}", root.tag)
    ns = ns_match.group(0) if ns_match else ""
    entries = []

    sitemaps = root.findall(f"{ns}sitemap")
    if sitemaps:
        logger.info("  Sitemap index: %d sub-sitemaps at %s", len(sitemaps), url)
        for sm in sitemaps:
            loc = sm.find(f"{ns}loc")
            if loc is not None and loc.text:
                entries.extend(_parse_sitemap(loc.text.strip(), delay, depth + 1))
        return entries

    for u in root.findall(f"{ns}url"):
        loc = u.find(f"{ns}loc")
        lastmod = u.find(f"{ns}lastmod")
        if loc is not None and loc.text:
            entries.append({
                "url": loc.text.strip(),
                "lastmod": lastmod.text.strip() if lastmod is not None and lastmod.text else "",
            })
    return entries


def scrape_sitemaps() -> list:
    all_records = []
    for src in config.SITEMAP_SOURCES:
        logger.info("Sitemap: %s", src["sitemap_url"])
        try:
            entries = _parse_sitemap(src["sitemap_url"], src["delay"])
        except Exception as exc:
            logger.error("Sitemap failed %s: %s", src["source_name"], exc)
            continue

        logger.info("Sitemap %s: %d total URLs", src["source_name"], len(entries))
        is_govt = src["source_type"] == "government"

        filtered = []
        for entry in entries:
            url = entry["url"]
            if not utils.is_article_url(url) or _url_seen(url):
                continue
            if not utils.url_passes_prefilter(url, is_government=is_govt):
                continue
            pub_date = None
            if entry["lastmod"]:
                pub_date = utils.parse_date_flexible(entry["lastmod"])
                if pub_date and not utils.validate_date(pub_date):
                    continue
            filtered.append((url, pub_date))

        logger.info("Sitemap %s: %d after filtering", src["source_name"], len(filtered))
        count = 0
        for url, known_date in tqdm(filtered, desc=f"Sitemap: {src['source_name']}", unit="pg"):
            try:
                rec = _fetch_and_parse_article(
                    url=url, source_key=src["source_key"],
                    source_name=src["source_name"], source_type=src["source_type"],
                    document_type=src["document_type"], outlet=src.get("outlet", ""),
                    delay=src["delay"], known_date=known_date,
                    skip_relevance_filter=is_govt,
                )
                if rec:
                    all_records.append(rec)
                    count += 1
            except Exception as exc:
                logger.debug("Sitemap article error %s: %s", url, exc)
        logger.info("Sitemap %s: %d records", src["source_name"], count)
    return all_records


# ══════════════════════════════════════════════════════════════
# STRATEGY 1: GDELT DOC API
# ══════════════════════════════════════════════════════════════
def _gdelt_query(term: str, start: str, end: str) -> list:
    params = (
        f"?query={quote_plus(term)}"
        f"&mode=ArtList&maxrecords=250&format=json"
        f"&startdatetime={start}&enddatetime={end}"
        f"&sourcelang=spanish"
    )
    resp = utils.rate_limited_get(
        config.GDELT_DOC_API + params,
        delay=config.GDELT_DELAY, domain_key="api.gdeltproject.org",
    )
    if resp is None:
        return []
    try:
        return resp.json().get("articles", [])
    except Exception:
        return []


def scrape_gdelt() -> list:
    discovered = []
    seen = set()

    quarters = []
    for year in config.YEARS:
        for qs in [1, 4, 7, 10]:
            qe = qs + 2
            start = f"{year}{qs:02d}01000000"
            end = f"{year}{qe:02d}28235959" if qe < 12 else f"{year}1231235959"
            quarters.append((start, end))

    total = len(config.GDELT_SEARCH_TERMS) * len(quarters)
    logger.info("GDELT: %d queries", total)
    pbar = tqdm(total=total, desc="GDELT discovery", unit="q")

    for term in config.GDELT_SEARCH_TERMS:
        for start_dt, end_dt in quarters:
            pbar.update(1)
            try:
                for art in _gdelt_query(term, start_dt, end_dt):
                    url = art.get("url", "")
                    if not url or not utils.is_article_url(url):
                        continue
                    norm = utils.normalize_url(url)
                    if norm in seen:
                        continue
                    if not utils.url_passes_prefilter(url):
                        continue
                    seen.add(norm)
                    sd = art.get("seendate", "")
                    discovered.append({
                        "url": url,
                        "title": art.get("title", ""),
                        "pub_date": utils.parse_date_flexible(sd[:8]) if sd else None,
                        "domain": art.get("domain", ""),
                    })
            except Exception:
                continue
    pbar.close()
    logger.info("GDELT: %d unique URLs discovered", len(discovered))

    # Fetch full text
    all_records = []
    for item in tqdm(discovered, desc="GDELT full-text", unit="art"):
        if _url_seen(item["url"]):
            continue
        try:
            resp = utils.rate_limited_get(item["url"], delay=config.DEFAULT_DELAY)
            if resp is None or len(resp.text) < 500:
                continue

            html = resp.text
            title = cleaning.extract_title_from_html(html) or item["title"]

            # Quick irrelevance check on title
            if utils.is_politically_irrelevant(title):
                continue

            text = cleaning.extract_article_content(html)
            if len(text) < 100:
                continue

            pub_date = item["pub_date"]
            if pub_date is None:
                raw = cleaning.extract_date_from_html(html)
                if raw:
                    pub_date = utils.parse_date_flexible(raw)
            if pub_date is None:
                pub_date = utils.extract_date_from_url(item["url"])

            engagement = utils.extract_engagement_metrics(html)

            rec = _build_record(
                source_key="gdelt", source_type="news",
                source_name=item["domain"], title=title, text=text,
                url=item["url"], pub_date=pub_date,
                document_type="news_article", outlet=item["domain"],
                engagement=engagement,
            )
            if rec:
                all_records.append(rec)
        except Exception as exc:
            logger.debug("GDELT fulltext error: %s", exc)
    logger.info("GDELT: %d records with full text", len(all_records))
    return all_records


# ══════════════════════════════════════════════════════════════
# STRATEGY 2: DATE-BASED ARCHIVE BROWSING
# ══════════════════════════════════════════════════════════════
def _extract_links(html: str, base_url: str, selector: str) -> list:
    soup = BeautifulSoup(html, "lxml")
    urls = []
    seen = set()
    for link in soup.select(selector):
        href = link.get("href", "")
        if href:
            full = urljoin(base_url, href)
            norm = utils.normalize_url(full)
            if norm not in seen and utils.is_article_url(full):
                seen.add(norm)
                urls.append(full)
    return urls


def scrape_date_archives() -> list:
    all_records = []
    for src in config.DATE_ARCHIVE_SOURCES:
        logger.info("Archive: %s", src["source_name"])
        is_govt = src.get("is_government", False)
        count = 0
        urls_found = 0

        year_months = [
            (y, m) for y in config.YEARS for m in config.MONTHS
            if date(y, m, 1) <= config.END_DATE
        ]

        for year, month in tqdm(year_months, desc=f"Archive: {src['source_name']}", unit="mo"):
            known_date = date(year, month, 15)
            month_urls = []

            archive_url = src["archive_template"].format(year=year, month=month)
            resp = utils.rate_limited_get(archive_url, delay=src["delay"])
            if resp is None:
                continue

            month_urls.extend(_extract_links(resp.text, archive_url, src["link_selector"]))

            # Sub-pages within the month
            if month_urls and "archive_page_template" in src:
                for sp in range(2, src["max_sub_pages"] + 1):
                    sub_url = src["archive_page_template"].format(
                        year=year, month=month, page=sp)
                    sub_resp = utils.rate_limited_get(sub_url, delay=src["delay"])
                    if sub_resp is None:
                        break
                    sub_urls = _extract_links(sub_resp.text, sub_url, src["link_selector"])
                    if not sub_urls:
                        break
                    month_urls.extend(sub_urls)

            urls_found += len(month_urls)

            for url in month_urls:
                if _url_seen(url):
                    continue
                if not utils.url_passes_prefilter(url, is_government=is_govt):
                    continue
                try:
                    rec = _fetch_and_parse_article(
                        url=url, source_key=src["source_key"],
                        source_name=src["source_name"], source_type=src["source_type"],
                        document_type=src["document_type"], outlet=src.get("outlet", ""),
                        delay=src["delay"], known_date=known_date,
                        content_selector=src.get("content_selector", ""),
                        skip_relevance_filter=is_govt,
                    )
                    if rec:
                        all_records.append(rec)
                        count += 1
                except Exception as exc:
                    logger.debug("Archive error %s: %s", url, exc)

        logger.info("Archive %s: %d URLs found, %d records kept", src["source_name"], urls_found, count)
    return all_records


# ══════════════════════════════════════════════════════════════
# STRATEGY 3: DEEP KEYWORD SEARCH
# ══════════════════════════════════════════════════════════════
def scrape_keyword_search() -> list:
    all_records = []
    for src in config.PAGINATED_SOURCES:
        count = 0
        for keyword in config.SEARCH_KEYWORDS:
            kw_count = 0
            empty = 0
            for page in range(1, src["max_pages_per_keyword"] + 1):
                page_url = src["search_template"].format(
                    page=page, keyword=quote_plus(keyword))
                resp = utils.rate_limited_get(page_url, delay=src["delay"])
                if resp is None:
                    empty += 1
                    if empty >= 3:
                        break
                    continue
                page_urls = _extract_links(resp.text, page_url, src["link_selector"])
                if not page_urls:
                    empty += 1
                    if empty >= 3:
                        break
                    continue
                empty = 0
                for url in page_urls:
                    if _url_seen(url):
                        continue
                    if not utils.url_passes_prefilter(url):
                        continue
                    try:
                        rec = _fetch_and_parse_article(
                            url=url, source_key=src["source_key"],
                            source_name=src["source_name"], source_type=src["source_type"],
                            document_type=src["document_type"], outlet=src.get("outlet", ""),
                            delay=src["delay"],
                            content_selector=src.get("content_selector", ""),
                        )
                        if rec:
                            all_records.append(rec)
                            kw_count += 1
                            count += 1
                    except Exception:
                        continue
            if kw_count:
                logger.info("  Search %s/'%s': %d", src["source_name"], keyword, kw_count)
        logger.info("Search %s: %d total", src["source_name"], count)
    return all_records


# ══════════════════════════════════════════════════════════════
# STRATEGY 4: RSS FEEDS
# ══════════════════════════════════════════════════════════════
def scrape_rss_feeds() -> list:
    try:
        import feedparser
    except ImportError:
        logger.warning("feedparser not installed; skipping RSS")
        return []

    all_records = []
    for src in config.RSS_SOURCES:
        logger.info("RSS: %s", src["source_name"])
        is_govt = src.get("is_government", False)
        resp = utils.rate_limited_get(src["feed_url"], delay=src["delay"])
        if resp is None:
            continue
        feed = feedparser.parse(resp.text)
        for entry in tqdm(feed.entries, desc=f"RSS: {src['source_name']}", unit="art"):
            try:
                url = entry.get("link", "")
                if not url or _url_seen(url):
                    continue
                pub_date = None
                for df in ["published", "updated", "created"]:
                    raw = entry.get(df, "")
                    if raw:
                        pub_date = utils.parse_date_flexible(raw)
                        if pub_date:
                            break
                if pub_date and not utils.validate_date(pub_date):
                    continue
                rec = _fetch_and_parse_article(
                    url=url, source_key=src["source_key"],
                    source_name=src["source_name"], source_type=src["source_type"],
                    document_type=src["document_type"], outlet=src.get("outlet", ""),
                    delay=src["delay"], known_date=pub_date,
                    skip_relevance_filter=is_govt,
                )
                if rec:
                    if not rec["title"]:
                        rec["title"] = entry.get("title", "")[:500]
                    all_records.append(rec)
            except Exception:
                continue
    logger.info("RSS: %d total", len(all_records))
    return all_records


# ══════════════════════════════════════════════════════════════
# STRATEGY 5: NEWSPAPER3K
# ══════════════════════════════════════════════════════════════
def scrape_newspaper3k() -> list:
    try:
        from newspaper import Source as NewspaperSource
    except ImportError:
        logger.warning("newspaper3k not installed; skipping")
        return []

    all_records = []
    for src in config.NEWSPAPER3K_SOURCES:
        logger.info("n3k: %s", src["source_name"])
        try:
            paper = NewspaperSource(src["base_url"], memoize_articles=False, language="es")
            paper.build()
            articles = paper.articles[:src["max_articles"]]
        except Exception as exc:
            logger.error("n3k build failed %s: %s", src["source_name"], exc)
            continue

        count = 0
        for article in tqdm(articles, desc=f"n3k: {src['source_name']}", unit="art"):
            if _url_seen(article.url):
                continue
            if not utils.url_passes_prefilter(article.url):
                continue
            try:
                article.download()
                article.parse()
                text = article.text
                if not text or len(text.strip()) < 100:
                    continue
                text = cleaning.ensure_utf8(cleaning.strip_boilerplate(
                    cleaning.normalize_whitespace(text)))
                pub_date = article.publish_date.date() if article.publish_date else None
                rec = _build_record(
                    source_key=src["source_key"], source_type=src["source_type"],
                    source_name=src["source_name"], title=article.title or "",
                    text=text, url=article.url, pub_date=pub_date,
                    document_type=src["document_type"], outlet=src.get("outlet", ""),
                )
                if rec:
                    all_records.append(rec)
                    count += 1
                time.sleep(config.DEFAULT_DELAY)
            except Exception:
                continue
        logger.info("n3k %s: %d", src["source_name"], count)
    return all_records


# ══════════════════════════════════════════════════════════════
# MASTER COLLECTION
# ══════════════════════════════════════════════════════════════
STRATEGIES = [
    ("XML Sitemaps (full site article inventories)", scrape_sitemaps),
    ("GDELT API (global news index → live fetch)", scrape_gdelt),
    ("Date-based archives (/YYYY/MM/ every month 2015–2025)", scrape_date_archives),
    ("Deep keyword search (14 keywords × 50 pages × 3 sites)", scrape_keyword_search),
    ("RSS feeds (recent articles)", scrape_rss_feeds),
    ("newspaper3k (auto-discovery fallback)", scrape_newspaper3k),
]


def collect_all(strategies=None) -> list:
    global _global_seen_urls
    _global_seen_urls = set()

    to_run = STRATEGIES if strategies is None else [
        STRATEGIES[i] for i in strategies if 0 <= i < len(STRATEGIES)
    ]

    all_records = []
    for name, fn in to_run:
        logger.info("=" * 70)
        logger.info("STRATEGY: %s", name)
        logger.info("=" * 70)
        try:
            recs = fn()
            logger.info("✓ %s → %d records", name, len(recs))
            all_records.extend(recs)
        except Exception as exc:
            logger.error("✗ FAILED: %s — %s", name, exc, exc_info=True)

    logger.info("Raw total: %d", len(all_records))
    all_records = utils.deduplicate_records(all_records)
    logger.info("After dedup: %d", len(all_records))
    return all_records
