"""
enrichment.py — NLP enrichment: NER, Bukele flag, corruption keywords.
"""

import re
from utils import logger
import config

_nlp_model = None


def _get_spacy_model():
    global _nlp_model
    if _nlp_model is not None:
        return _nlp_model
    import spacy
    for name in ["es_core_news_lg", "es_core_news_md", "es_core_news_sm"]:
        try:
            _nlp_model = spacy.load(name)
            logger.info("Loaded spaCy: %s", name)
            return _nlp_model
        except OSError:
            continue
    try:
        import subprocess
        subprocess.check_call(["python", "-m", "spacy", "download", "es_core_news_sm"],
                              stdout=subprocess.DEVNULL)
        _nlp_model = spacy.load("es_core_news_sm")
        return _nlp_model
    except Exception as exc:
        logger.warning("No spaCy model: %s", exc)
        return None


def extract_named_entities(text, max_chars=50_000):
    nlp = _get_spacy_model()
    if nlp is None:
        return ""
    doc = nlp(text[:max_chars])
    seen = set()
    ents = []
    for ent in doc.ents:
        key = (ent.text.strip(), ent.label_)
        if key not in seen and len(ent.text.strip()) > 1:
            seen.add(key)
            ents.append(f"{ent.text.strip()} ({ent.label_})")
    return "|".join(ents)


_BUKELE_RE = re.compile(
    r"\b(bukele|nayib\s+bukele|presidente\s+bukele|nayib\s+armando\s+bukele)\b",
    re.IGNORECASE)


def flag_bukele(text):
    return bool(_BUKELE_RE.search(text))


def flag_corruption(text):
    text_lower = text.lower()
    matched = []
    for kw in config.CORRUPTION_KEYWORDS:
        kl = kw.lower()
        if " " in kl:
            if kl in text_lower:
                matched.append(kw)
        elif re.search(r"\b" + re.escape(kl) + r"\b", text_lower):
            matched.append(kw)
    return {
        "has_corruption_keyword": len(matched) > 0,
        "matched_keywords": matched,
        "corruption_keyword_count": len(matched),
    }


def enrich_records(records, do_ner=True, do_bukele=True, do_corruption=True):
    from tqdm import tqdm
    logger.info("Enriching %d records ...", len(records))
    if do_ner and _get_spacy_model() is None:
        logger.warning("NER skipped — no model")
        do_ner = False

    for rec in tqdm(records, desc="Enriching", unit="rec"):
        text = rec.get("text", "")
        rec["named_entities"] = extract_named_entities(text) if do_ner else ""
        rec["mentions_bukele"] = flag_bukele(text) if do_bukele else ""
        if do_corruption:
            c = flag_corruption(text)
            rec["has_corruption_keyword"] = c["has_corruption_keyword"]
            rec["corruption_keywords_matched"] = "|".join(c["matched_keywords"])
            rec["corruption_keyword_count"] = c["corruption_keyword_count"]
        else:
            rec["has_corruption_keyword"] = ""
            rec["corruption_keywords_matched"] = ""
            rec["corruption_keyword_count"] = ""
    logger.info("Enrichment done.")
    return records
