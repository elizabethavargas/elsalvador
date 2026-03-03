"""
cleaning.py — Text cleaning and HTML content extraction.
"""

import json
import re
import unicodedata
from typing import Optional

from bs4 import BeautifulSoup, Comment

import config


def extract_text_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in ["script", "style", "nav", "header", "footer",
                "aside", "noscript", "iframe", "form", "svg"]:
        for el in soup.find_all(tag):
            el.decompose()
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()
    nav_re = re.compile(
        r"(sidebar|widget|menu|nav|breadcrumb|social|share|comment-|"
        r"related|footer|cookie|banner|popup|modal|advertis|ad-|"
        r"newsletter|subscribe|paywall)", re.IGNORECASE)
    for el in soup.find_all(class_=nav_re):
        el.decompose()
    for el in soup.find_all(id=nav_re):
        el.decompose()
    return soup.get_text(separator="\n")


def normalize_whitespace(text: str) -> str:
    text = text.replace("\t", " ").replace("\u00a0", " ").replace("\xa0", " ")
    text = re.sub(r"[ ]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def strip_boilerplate(text: str) -> str:
    for phrase in config.BOILERPLATE_PHRASES:
        text = text.replace(phrase, "")
    return text


def ensure_utf8(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)


def remove_remaining_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


def clean_text(raw: str, is_html: bool = True) -> str:
    text = extract_text_from_html(raw) if is_html else raw
    text = remove_remaining_html(text)
    text = strip_boilerplate(text)
    text = ensure_utf8(text)
    return normalize_whitespace(text)


def extract_title_from_html(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, "lxml")
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return og["content"].strip()
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(strip=True)
    title_tag = soup.find("title")
    if title_tag and title_tag.get_text(strip=True):
        return title_tag.get_text(strip=True)
    return None


def extract_date_from_html(html: str) -> Optional[str]:
    """Multi-source date extraction: meta → JSON-LD → <time> → og:*."""
    soup = BeautifulSoup(html, "lxml")

    # Meta tags (broad search)
    for attr in ["article:published_time", "datePublished", "date",
                 "pubdate", "publish_date", "DC.date.issued",
                 "article:modified_time", "dateModified"]:
        meta = soup.find("meta", property=attr) or soup.find("meta", attrs={"name": attr})
        if meta and meta.get("content"):
            return meta["content"].strip()

    # JSON-LD
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if isinstance(item, dict):
                    for key in ["datePublished", "dateCreated", "dateModified"]:
                        if key in item:
                            return str(item[key])
        except (json.JSONDecodeError, TypeError):
            pass

    # <time datetime="...">
    time_tag = soup.find("time", datetime=True)
    if time_tag:
        return time_tag["datetime"].strip()

    # Last resort: look for visible date-like text near the top of the article
    # Many Salvadoran sites display dates as visible text without semantic markup
    top_text = soup.get_text()[:1000]
    # "12 de mayo de 2021"
    m = re.search(r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})", top_text)
    if m:
        return m.group(0)
    # "2021-05-12" or "12/05/2021"
    m = re.search(r"(\d{4}-\d{2}-\d{2})", top_text)
    if m:
        return m.group(1)
    m = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", top_text)
    if m:
        return m.group(1)

    return None


def extract_article_content(html: str, content_selector: str = "") -> str:
    soup = BeautifulSoup(html, "lxml")
    selectors = [s.strip() for s in content_selector.split(",") if s.strip()]
    selectors += [
        "article .entry-content", "article .post-content",
        ".article-body", ".story-body", ".nota-contenido",
        ".article-content", ".post-body", ".field-item",
        "article", ".entry-content", ".post-content",
        "main .content", "#content",
    ]
    for sel in selectors:
        try:
            el = soup.select_one(sel)
            if el:
                text = clean_text(str(el), is_html=True)
                if len(text) > 100:
                    return text
        except Exception:
            continue
    return clean_text(html, is_html=True)
