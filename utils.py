"""
utils.py — Shared utilities.

Key additions in this version:
- Political relevance scoring (keyword-based filter)
- Multi-layer date extraction (meta → JSON-LD → URL → Spanish text)
- Engagement metrics extraction (likes, comments, shares, views)
"""

import hashlib
import json
import logging
import os
import re
import time
from datetime import date
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config


# ──────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────
def setup_logging() -> logging.Logger:
    os.makedirs(config.LOG_DIR, exist_ok=True)
    logger = logging.getLogger("el_salvador_dataset")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

    fh = logging.FileHandler(
        os.path.join(config.LOG_DIR, "scraper.log"), encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s"))

    logger.addHandler(ch)
    logger.addHandler(fh)
    return logger


logger = setup_logging()


# ──────────────────────────────────────────────────────────────
# HTTP session
# ──────────────────────────────────────────────────────────────
def build_session() -> requests.Session:
    """
    Build an HTTP session.  Tries cloudscraper first (handles Cloudflare JS
    challenges and TLS fingerprinting).  Falls back to plain requests if the
    package is not installed.
    """
    retry = Retry(
        total=config.MAX_RETRIES,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)

    try:
        import cloudscraper  # type: ignore
        session = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )
        logger.info("HTTP session: using cloudscraper (Cloudflare-bypass mode)")
    except ImportError:
        session = requests.Session()
        logger.info("HTTP session: cloudscraper not installed — using plain requests "
                    "(install with: pip install cloudscraper)")

    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(config.HEADERS)
    return session


SESSION = build_session()

_last_request_time: dict = {}
_domain_403_count: dict = {}   # track consecutive 403s per domain


def rate_limited_get(url, delay=config.DEFAULT_DELAY, domain_key=None,
                     timeout=config.REQUEST_TIMEOUT) -> Optional[requests.Response]:
    """
    Rate-limited GET with 403-retry logic:
    - On first 403, wait 2 s and retry with a rotated User-Agent.
    - On a second consecutive 403 from the same domain, log a warning and
      skip the URL (the domain is likely blocking the scraper outright).
    """
    if domain_key is None:
        domain_key = re.sub(r"https?://([^/]+).*", r"\1", url)

    now = time.time()
    wait = delay - (now - _last_request_time.get(domain_key, 0))
    if wait > 0:
        time.sleep(wait)

    def _get(session_headers_override=None):
        headers = {}
        if session_headers_override:
            headers = session_headers_override
        try:
            resp = SESSION.get(url, timeout=timeout, headers=headers)
            _last_request_time[domain_key] = time.time()
            return resp
        except requests.RequestException as exc:
            logger.error("Request failed %s: %s", url, exc)
            return None

    resp = _get()
    if resp is None:
        return None

    if resp.status_code == 200:
        _domain_403_count[domain_key] = 0
        resp.encoding = resp.apparent_encoding or "utf-8"
        return resp

    if resp.status_code == 403:
        consecutive = _domain_403_count.get(domain_key, 0) + 1
        _domain_403_count[domain_key] = consecutive

        if consecutive <= len(config.ALTERNATE_USER_AGENTS):
            # Retry once with the next user-agent in the rotation
            alt_ua = config.ALTERNATE_USER_AGENTS[consecutive - 1]
            logger.debug("403 on %s — retrying with alternate UA #%d", domain_key, consecutive)
            time.sleep(2)
            resp2 = _get({"User-Agent": alt_ua})
            if resp2 is not None and resp2.status_code == 200:
                _domain_403_count[domain_key] = 0
                resp2.encoding = resp2.apparent_encoding or "utf-8"
                return resp2
            logger.warning("HTTP 403 (retry also failed) for %s", url)
        else:
            logger.warning(
                "HTTP 403 (domain %s blocked after %d attempts) — skipping: %s",
                domain_key, consecutive, url,
            )
        return None

    logger.warning("HTTP %d for %s", resp.status_code, url)
    return None


# ──────────────────────────────────────────────────────────────
# Raw HTML caching
# ──────────────────────────────────────────────────────────────
def save_raw_html(html, source_key, identifier):
    os.makedirs(config.RAW_HTML_DIR, exist_ok=True)
    safe_id = re.sub(r"[^\w\-]", "_", identifier)[:120]
    path = os.path.join(config.RAW_HTML_DIR, f"{source_key}_{safe_id}.html")
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
    except Exception:
        pass
    return path


# ──────────────────────────────────────────────────────────────
# Date validation and parsing — MULTI-LAYER
# ──────────────────────────────────────────────────────────────
def validate_date(d: Optional[date]) -> bool:
    if d is None:
        return False
    return config.START_DATE <= d <= config.END_DATE


SPANISH_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "septbre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}


def parse_date_flexible(text: str) -> Optional[date]:
    """Parse dates from many formats including Spanish month names and URL paths."""
    if not text or not text.strip():
        return None
    text = text.strip()

    from dateutil import parser as dateutil_parser

    # dateutil (handles ISO, RFC, most formats)
    try:
        dt = dateutil_parser.parse(text, dayfirst=True, fuzzy=True)
        return dt.date()
    except (ValueError, OverflowError):
        pass

    # "12 de mayo de 2021"
    m = re.search(r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})", text, re.IGNORECASE)
    if m:
        day_s, month_s, year_s = m.groups()
        mn = SPANISH_MONTHS.get(month_s.lower())
        if mn:
            try:
                return date(int(year_s), mn, int(day_s))
            except ValueError:
                pass

    # "mayo 2021" or "mayo de 2021" → day=1
    m = re.search(r"(\w+)\s+(?:de\s+)?(\d{4})", text, re.IGNORECASE)
    if m:
        month_s, year_s = m.groups()
        mn = SPANISH_MONTHS.get(month_s.lower())
        if mn:
            try:
                return date(int(year_s), mn, 1)
            except ValueError:
                pass

    return None


def extract_date_from_url(url: str) -> Optional[date]:
    """
    Try to extract a date from the URL path itself.
    Many news sites embed dates: /2021/06/09/article-slug/
    Also handles trailing /YYYY/ pattern (e.g. elsalvador.com/.../slug/64046/2026/).
    """
    # Pattern: /YYYY/MM/DD/
    m = re.search(r"/(\d{4})/(\d{1,2})/(\d{1,2})/", url)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    # Pattern: /YYYY/MM/ (use day=15 as mid-month estimate)
    m = re.search(r"/(\d{4})/(\d{1,2})/", url)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), 15)
        except ValueError:
            pass

    # Pattern in slug: 2021-06-09 or 20210609
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", url)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    m = re.search(r"/(\d{8})/", url)
    if m:
        ds = m.group(1)
        try:
            return date(int(ds[:4]), int(ds[4:6]), int(ds[6:8]))
        except ValueError:
            pass

    # Pattern: trailing /YYYY/ or /YYYY at path end
    # e.g. elsalvador.com/noticias/.../slug/64046/2026/
    clean = url.split("?")[0].split("#")[0].rstrip("/")
    m = re.search(r"/(\d{4})$", clean)
    if m:
        try:
            yr = int(m.group(1))
            if 2000 <= yr <= 2030:
                return date(yr, 6, 15)  # mid-year estimate
        except ValueError:
            pass

    return None


# ──────────────────────────────────────────────────────────────
# POLITICAL RELEVANCE SCORING
# ──────────────────────────────────────────────────────────────
# Pre-compile patterns for speed
_strong_patterns = [
    (re.compile(r"\b" + re.escape(kw.lower()) + r"\b"), 2)
    for kw in config.RELEVANCE_KEYWORDS_STRONG
]
_normal_patterns = [
    (re.compile(r"\b" + re.escape(kw.lower()) + r"\b"), 1)
    for kw in config.RELEVANCE_KEYWORDS_NORMAL
]
_irrelevance_patterns = [
    re.compile(r"\b" + re.escape(kw.lower()) + r"\b")
    for kw in config.IRRELEVANCE_KEYWORDS
]


def compute_relevance_score(title: str, text: str) -> int:
    """
    Score political relevance of an article.

    Checks title + first 1500 chars of text against keyword lists.
    Strong keywords = 2 points, normal = 1 point.
    Returns the total score. Articles need >= RELEVANCE_THRESHOLD to keep.
    """
    sample = (title + " " + text[:1500]).lower()
    score = 0

    for pattern, weight in _strong_patterns:
        if pattern.search(sample):
            score += weight

    for pattern, weight in _normal_patterns:
        if pattern.search(sample):
            score += weight

    return score


def is_politically_irrelevant(title: str) -> bool:
    """
    Quick check: if the title is ONLY about sports/entertainment/etc.,
    flag it so we can skip before fetching the full article.
    """
    title_lower = title.lower()
    for pattern in _irrelevance_patterns:
        if pattern.search(title_lower):
            # Check if it ALSO has political keywords (e.g. "Bukele at football game")
            for kw_pattern, _ in _strong_patterns:
                if kw_pattern.search(title_lower):
                    return False  # has political context, keep it
            return True
    return False


# ──────────────────────────────────────────────────────────────
# URL-LEVEL PRE-FILTER
# Runs before fetching any page; uses only the URL itself.
# ──────────────────────────────────────────────────────────────

# Political terms that appear in URL slugs (unaccented, hyphen-delimited words)
_URL_POLITICAL_STRONG = {
    "bukele", "nayib",
    "nuevas ideas", "fmln", "arena",
    "asamblea", "legislativa",
    "excepcion", "regimen",
    "decreto", "reforma", "constitucional", "reeleccion",
    "bitcoin", "pandillas", "maras",
    "elecciones", "presidenciales", "legislativas",
    "corrupcion", "fiscal",
    "cecot", "carceles", "carcel",
    "detenidos", "presos",
    "golpe", "posesion",
    "congreso", "diputado", "diputados",
    "partido", "candidato",
    "impunidad", "soborno",
}

# Path segments that indicate political/national coverage sections
_URL_SECTION_POLITICAL = {
    "nacionales", "nacional", "politica", "gobierno",
    "seguridad", "opinion", "editorial", "economia",
    "actualidad", "judicial", "legal",
}

# Slug/section words that indicate non-political topics
_URL_IRRELEVANCE_SLUGS = {
    "deportes", "futbol", "deporte",
    "entretenimiento", "farandula", "espectaculos",
    "clasificados", "horoscopo", "recetas", "cocina",
    "beisbol", "baloncesto",
}


def _extract_year_from_url_only(url: str) -> Optional[int]:
    """Return a 4-digit year (2000–2030) found in the URL, or None."""
    clean = url.split("?")[0].split("#")[0]

    # /YYYY/MM/DD/ or /YYYY/MM/
    m = re.search(r"/(\d{4})/(\d{1,2})/", clean)
    if m:
        yr, mo = int(m.group(1)), int(m.group(2))
        if 2000 <= yr <= 2030 and 1 <= mo <= 12:
            return yr

    # /YYYYMM/ compact format (elfaro.net: /202203/)
    m = re.search(r"/(\d{4})(\d{2})/", clean)
    if m:
        yr, mo = int(m.group(1)), int(m.group(2))
        if 2000 <= yr <= 2030 and 1 <= mo <= 12:
            return yr

    # YYYY-MM-DD in slug
    m = re.search(r"(\d{4})-(\d{2})-\d{2}", clean)
    if m:
        yr, mo = int(m.group(1)), int(m.group(2))
        if 2000 <= yr <= 2030 and 1 <= mo <= 12:
            return yr

    # /YYYYMMDD/
    m = re.search(r"/(\d{8})/", clean)
    if m:
        yr = int(m.group(1)[:4])
        if 2000 <= yr <= 2030:
            return yr

    # Trailing /YYYY at path end (elsalvador.com: /slug/64046/2026/)
    m = re.search(r"/(\d{4})$", clean.rstrip("/"))
    if m and 2000 <= int(m.group(1)) <= 2030:
        return int(m.group(1))

    return None


def url_passes_prefilter(url: str, is_government: bool = False) -> bool:
    """
    URL-only pre-filter — runs before fetching any page.

    Rejects URLs when:
    1. A year is detectable in the URL and falls outside 2015–2025.
    2. The URL slug/path clearly signals a non-political topic
       (sports, entertainment, etc.) with no offsetting political term.

    Government sources always pass (everything they publish is kept).
    Conservative by design: ambiguous URLs pass through to full filtering.
    """
    if is_government:
        return True

    # ── 1. DATE CHECK ──
    yr = _extract_year_from_url_only(url)
    if yr is not None:
        if yr < config.START_DATE.year or yr > config.END_DATE.year:
            logger.debug("URL pre-filter (year=%d out of range): %s", yr, url[-100:])
            return False

    # ── 2. SLUG POLITICAL/IRRELEVANCE CHECK ──
    clean = url.split("?")[0].split("#")[0]
    path = re.sub(r"^https?://[^/]+", "", clean)
    # Convert path separators and hyphens to spaces for keyword matching
    slug_text = re.sub(r"[-_/]", " ", path).lower()

    has_irrelevance = any(kw in slug_text for kw in _URL_IRRELEVANCE_SLUGS)
    if has_irrelevance:
        has_political = (
            any(kw in slug_text for kw in _URL_POLITICAL_STRONG)
            or any(kw in slug_text for kw in _URL_SECTION_POLITICAL)
        )
        if not has_political:
            logger.debug("URL pre-filter (non-political slug): %s", url[-100:])
            return False

    return True


# ──────────────────────────────────────────────────────────────
# ENGAGEMENT METRICS EXTRACTION
# ──────────────────────────────────────────────────────────────
def extract_engagement_metrics(html: str) -> dict:
    """
    Extract engagement metrics (comments, likes, shares, views) from HTML.

    Tries multiple approaches:
    1. Schema.org / JSON-LD structured data
    2. Open Graph meta tags
    3. CSS selectors matching common counter patterns
    4. Disqus comment count markers
    5. Data attributes (data-shares, data-comments, etc.)

    Returns dict with keys: comment_count, like_count, share_count, view_count.
    Values are int or None if not found.
    """
    from bs4 import BeautifulSoup

    metrics = {
        "comment_count": None,
        "like_count": None,
        "share_count": None,
        "view_count": None,
    }

    soup = BeautifulSoup(html, "lxml")

    # ── 1. JSON-LD structured data ──
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                # commentCount
                if "commentCount" in item:
                    metrics["comment_count"] = _parse_count(item["commentCount"])
                # interactionStatistic (schema.org)
                for stat in item.get("interactionStatistic", []):
                    if isinstance(stat, dict):
                        itype = stat.get("interactionType", "")
                        value = stat.get("userInteractionCount", 0)
                        if "Comment" in str(itype):
                            metrics["comment_count"] = _parse_count(value)
                        elif "Like" in str(itype):
                            metrics["like_count"] = _parse_count(value)
                        elif "Share" in str(itype):
                            metrics["share_count"] = _parse_count(value)
        except (json.JSONDecodeError, TypeError):
            continue

    # ── 2. Meta tags ──
    for prop in config.ENGAGEMENT_META_PROPERTIES:
        meta = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
        if meta and meta.get("content"):
            val = _parse_count(meta["content"])
            if val is not None:
                if "comment" in prop.lower():
                    metrics["comment_count"] = metrics["comment_count"] or val
                elif "like" in prop.lower():
                    metrics["like_count"] = metrics["like_count"] or val

    # ── 3. CSS selectors ──
    for metric_key, selectors in config.ENGAGEMENT_CSS_SELECTORS.items():
        if metrics.get(f"{metric_key}_count") is not None:
            continue  # already found via JSON-LD or meta
        for sel in selectors:
            try:
                el = soup.select_one(sel)
                if el:
                    text = el.get_text(strip=True)
                    val = _parse_count(text)
                    if val is not None:
                        metrics[f"{metric_key}_count"] = val
                        break
            except Exception:
                continue

    # ── 4. Data attributes (common in share buttons) ──
    for el in soup.find_all(attrs={"data-shares": True}):
        val = _parse_count(el["data-shares"])
        if val is not None:
            metrics["share_count"] = metrics["share_count"] or val
    for el in soup.find_all(attrs={"data-comments": True}):
        val = _parse_count(el["data-comments"])
        if val is not None:
            metrics["comment_count"] = metrics["comment_count"] or val

    # ── 5. Disqus comment count ──
    disqus = soup.find("a", class_="disqus-comment-count")
    if disqus:
        val = _parse_count(disqus.get_text(strip=True))
        if val is not None:
            metrics["comment_count"] = metrics["comment_count"] or val

    return metrics


def _parse_count(value) -> Optional[int]:
    """Parse a count value from various formats (int, str with commas, '1.2K', etc.)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)

    text = str(value).strip().replace(",", "").replace(".", "")

    # Handle "1.2K", "3.4M" abbreviations
    m = re.match(r"^([\d.]+)\s*([kKmM])?$", str(value).strip().replace(",", ""))
    if m:
        num = float(m.group(1))
        suffix = (m.group(2) or "").upper()
        if suffix == "K":
            return int(num * 1000)
        elif suffix == "M":
            return int(num * 1_000_000)
        return int(num)

    # Plain number
    m = re.search(r"(\d+)", text)
    if m:
        return int(m.group(1))

    return None


# ──────────────────────────────────────────────────────────────
# KEY EVENT PROXIMITY TAGGING
# ──────────────────────────────────────────────────────────────
def tag_nearest_event(article_date: date) -> dict:
    """
    Find the nearest key political event to the article's date.
    Returns dict with event name and days_from_event (negative = before, positive = after).
    """
    if article_date is None:
        return {"nearest_event": "", "days_from_event": None}

    nearest = None
    min_delta = float("inf")

    for evt in config.KEY_EVENTS:
        evt_date = date.fromisoformat(evt["date"])
        delta = (article_date - evt_date).days
        if abs(delta) < abs(min_delta):
            min_delta = delta
            nearest = evt

    if nearest is None:
        return {"nearest_event": "", "days_from_event": None}

    return {
        "nearest_event": nearest["event"],
        "days_from_event": min_delta,
    }


# ──────────────────────────────────────────────────────────────
# URL filtering
# ──────────────────────────────────────────────────────────────
_skip_patterns = [re.compile(p, re.IGNORECASE) for p in config.SKIP_URL_PATTERNS]


def is_article_url(url: str) -> bool:
    if not url or len(url) < 20:
        return False
    for p in _skip_patterns:
        if p.search(url):
            return False
    return True


def normalize_url(url: str) -> str:
    url = url.split("#")[0]
    url = re.sub(r"[?&](utm_\w+=[^&]*)", "", url)
    return url.rstrip("/")


# ──────────────────────────────────────────────────────────────
# Deduplication
# ──────────────────────────────────────────────────────────────
def text_fingerprint(text: str) -> str:
    norm = re.sub(r"\s+", " ", text.lower().strip())
    return hashlib.sha256(norm[:2000].encode("utf-8")).hexdigest()


def deduplicate_records(records: list) -> list:
    seen_urls = set()
    seen_fps = set()
    seen_keys = set()
    unique = []

    for rec in records:
        url_n = normalize_url(rec.get("url", ""))
        fp = text_fingerprint(rec.get("text", ""))
        key = (rec.get("source_name", ""), rec.get("title", "")[:100], rec.get("date", ""))

        if url_n and url_n in seen_urls:
            continue
        if fp in seen_fps:
            continue
        if key[1] and key in seen_keys:
            continue

        if url_n:
            seen_urls.add(url_n)
        seen_fps.add(fp)
        if key[1]:
            seen_keys.add(key)
        unique.append(rec)

    removed = len(records) - len(unique)
    if removed > 0:
        logger.info("Dedup: removed %d (%d → %d)", removed, len(records), len(unique))
    return unique


# ──────────────────────────────────────────────────────────────
# ID generation
# ──────────────────────────────────────────────────────────────
_id_counter = 0


def generate_id(source_key: str) -> str:
    global _id_counter
    _id_counter += 1
    return f"{source_key}_{_id_counter:06d}"
