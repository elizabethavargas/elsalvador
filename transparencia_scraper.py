"""
transparencia_scraper.py — Scrape document metadata (and optionally files)
from https://www.transparencia.gob.sv/ for all publications since 2015.

SITE ARCHITECTURE:
  indexJSON.php
    → list of 11 institution category tokens

  institucionesCategoriaJSON.php?id_tipo={N}
    → JSON array of institutions in that category (id_institucion, nombre, acronym, etc.)
    N=1  Ministerios (17)
    N=2  Autónomas (97)
    N=3  Presidencia (1)
    N=4  Otras dependencias del Estado (11)
    N=5  Municipalidades (231)
    N=6  Hospitales (36)
    N=7  Gobernaciones (14)
    N=8  ONG (2)
    N=10 Nuevas Municipalidades (41)
    N=11 Órgano Legislativo (1+)
    (N=12..20 probed automatically)

  perfilInstitucionesDocMasDescargadosJson.php?id_institucion={id}
    → JSON {data: [...]} of the most-downloaded documents per institution.
      Each record: id_documents, downloads, active, year, estandar, name,
                   document_file_name_anexo, file_url, file_url2, file_detalle

  descarga_archivo.php?id={base64(doc_id)}&inst={doc_id}
    → actual file download (PDF, XLSX, DOCX, etc.)

USAGE:
    # Collect metadata only (fast, ~hours)
    python transparencia_scraper.py

    # Collect metadata AND download every file
    python transparencia_scraper.py --download

    # Only one institution type (e.g. Ministerios = id_tipo 1)
    python transparencia_scraper.py --id-tipo 1

    # Only a single institution by numeric ID
    python transparencia_scraper.py --institution 9

    # Resume an interrupted run (checkpoint auto-saved to output/)
    python transparencia_scraper.py --resume

OUTPUT (in ./output/transparencia/):
    metadata.csv         — all document records
    metadata.jsonl       — same, one JSON object per line
    checkpoint.json      — progress state for --resume
    files/{inst}/{year}/ — downloaded files (only with --download)
"""

import argparse
import base64
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ─────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────
BASE_URL = "https://www.transparencia.gob.sv/"
START_YEAR = 2015
MAX_ID_TIPO = 20   # probe institution types 1..20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-SV,es;q=0.9,en;q=0.5",
    "Accept": "application/json, text/html, */*",
    "Referer": BASE_URL,
}

REQUEST_TIMEOUT = 30
MAX_RETRIES = 3

_MIME_TO_EXT = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/msword": "doc",
    "application/zip": "zip",
    "image/jpeg": "jpg",
    "image/png": "png",
}

CSV_FIELDS = [
    "id_documents", "id_institucion", "institution_name", "institution_acronym",
    "id_tipo", "year", "estandar", "name", "active", "downloads",
    "file_url", "file_url2", "file_detalle", "has_annex", "file_extension",
    "local_path", "scraped_at",
]

# ─────────────────────────────────────────────────────────────
# LOGGING — module-level logger initialised lazily
# ─────────────────────────────────────────────────────────────
logger = logging.getLogger("transparencia")


def _setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"transparencia_{datetime.now():%Y%m%d_%H%M%S}.log"
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )


# ─────────────────────────────────────────────────────────────
# HTTP SESSION — built once in main(), shared globally
# ─────────────────────────────────────────────────────────────
_session: Optional[requests.Session] = None
_last_request_time: float = 0.0
_request_delay: float = 1.5    # updated by CLI --delay


def _build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    retry = Retry(
        total=MAX_RETRIES,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _get(url: str, delay: Optional[float] = None, **kwargs) -> Optional[requests.Response]:
    """Rate-limited GET.  Returns None on any failure."""
    global _last_request_time
    used_delay = delay if delay is not None else _request_delay
    elapsed = time.time() - _last_request_time
    if elapsed < used_delay:
        time.sleep(used_delay - elapsed)

    try:
        resp = _session.get(url, timeout=REQUEST_TIMEOUT, **kwargs)  # type: ignore[union-attr]
        _last_request_time = time.time()
        if resp.status_code == 200:
            return resp
        logger.warning("HTTP %d: %s", resp.status_code, url)
        return None
    except requests.RequestException as exc:
        logger.warning("Request error for %s: %s", url, exc)
        return None


# ─────────────────────────────────────────────────────────────
# CHECKPOINT  (resume support)
# ─────────────────────────────────────────────────────────────
class Checkpoint:
    """Persist progress so interrupted runs can be resumed with --resume."""

    def __init__(self, path: Path):
        self.path = path
        self.data: dict = {
            "completed_institutions": [],
            "total_docs": 0,
            "total_downloaded": 0,
            "started_at": datetime.now().isoformat(),
        }
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    self.data = json.load(f)
                logger.info("Resumed checkpoint: %d institutions already done",
                            len(self.data["completed_institutions"]))
            except (json.JSONDecodeError, KeyError):
                logger.warning("Corrupt checkpoint — starting fresh")

    def save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def mark_done(self, inst_id: int, doc_count: int, dl_count: int) -> None:
        if inst_id not in self.data["completed_institutions"]:
            self.data["completed_institutions"].append(inst_id)
        self.data["total_docs"] += doc_count
        self.data["total_downloaded"] += dl_count
        self.save()

    def is_done(self, inst_id: int) -> bool:
        return inst_id in self.data["completed_institutions"]


# ─────────────────────────────────────────────────────────────
# INSTITUTION DISCOVERY
# ─────────────────────────────────────────────────────────────
def fetch_institution_categories() -> list:
    """
    Return the 11 top-level category tokens from indexJSON.php.
    Each element: {int_name, int_imagen, int_insti_token, int_cantidad}.
    """
    url = urljoin(BASE_URL, "indexJSON.php")
    resp = _get(url)
    if resp is None:
        logger.error("Could not fetch institution categories")
        return []
    try:
        data = resp.json()
        logger.info("Fetched %d institution categories", len(data))
        return data
    except ValueError:
        logger.error("Non-JSON response from %s", url)
        return []


def fetch_institutions_for_tipo(id_tipo: int) -> list:
    """
    Return institutions for the given id_tipo category.
    Each element: {id_institucion, nombre_institucion, acronym, ...}.
    """
    url = urljoin(BASE_URL, f"institucionesCategoriaJSON.php?id_tipo={id_tipo}")
    resp = _get(url)
    if resp is None:
        return []
    try:
        payload = resp.json()
        institutions = payload.get("data", [])
        return institutions if isinstance(institutions, list) else []
    except ValueError:
        return []


def discover_all_institutions(only_id_tipo: Optional[int] = None) -> list:
    """
    Probe id_tipo 1..MAX_ID_TIPO and collect every unique institution.
    Returns enriched dicts: {id_institucion, nombre_institucion, acronym, id_tipo, ...}.
    """
    all_institutions: list = []
    seen_ids: set = set()
    probe_range = [only_id_tipo] if only_id_tipo else range(1, MAX_ID_TIPO + 1)

    for id_tipo in probe_range:
        institutions = fetch_institutions_for_tipo(id_tipo)
        if not institutions:
            logger.debug("id_tipo=%d: empty", id_tipo)
            continue
        logger.info("id_tipo=%d: %d institutions", id_tipo, len(institutions))
        for inst in institutions:
            try:
                inst_id = int(inst.get("id_institucion", 0))
            except (TypeError, ValueError):
                continue
            if inst_id == 0 or inst_id in seen_ids:
                continue
            seen_ids.add(inst_id)
            all_institutions.append({
                "id_institucion": inst_id,
                "nombre_institucion": inst.get("nombre_institucion", ""),
                "acronym": inst.get("acronym", ""),
                "id_tipo": id_tipo,
                "officer_name": inst.get("officer_name", ""),
                "officer_email": inst.get("officer_email", ""),
            })

    logger.info("Total unique institutions: %d", len(all_institutions))
    return all_institutions


# ─────────────────────────────────────────────────────────────
# DOCUMENT DISCOVERY
# ─────────────────────────────────────────────────────────────
def fetch_documents_for_institution(inst_id: int) -> list:
    """
    Return raw document dicts for one institution from the known JSON endpoint.
    The endpoint returns the most-downloaded documents (typically up to 50).
    """
    url = urljoin(
        BASE_URL,
        f"perfilInstitucionesDocMasDescargadosJson.php?id_institucion={inst_id}",
    )
    resp = _get(url)
    if resp is None:
        return []
    try:
        payload = resp.json()
        # Endpoint returns {"data": [...]} or a bare list
        if isinstance(payload, list):
            return payload
        return payload.get("data", []) or []
    except ValueError:
        return []


def _safe_int(val, default: int = 0) -> int:
    try:
        if val in (None, "", "null"):
            return default
        # Strip thousands-separator commas (e.g. "111,983" → 111983)
        return int(str(val).replace(",", ""))
    except (TypeError, ValueError):
        return default


def _safe_year(val) -> Optional[int]:
    try:
        y = int(val)
        return y if 1990 <= y <= 2100 else None
    except (TypeError, ValueError):
        return None


def _make_download_url(doc_id: int) -> str:
    """Construct the canonical download URL from a document ID."""
    b64 = base64.b64encode(str(doc_id).encode()).decode()
    return urljoin(BASE_URL, f"descarga_archivo.php?id={b64}&inst={doc_id}")


def _infer_extension(url: str) -> str:
    try:
        path = urlparse(url).path
        _, ext = os.path.splitext(path)
        return ext.lower().lstrip(".")
    except Exception:
        return ""


def build_record(raw: dict, institution: dict) -> Optional[dict]:
    """
    Normalise a raw API doc dict.  Returns None if year < START_YEAR.
    """
    doc_id = _safe_int(raw.get("id_documents"))
    if doc_id == 0:
        return None

    year = _safe_year(raw.get("year"))
    if year is not None and year < START_YEAR:
        return None

    file_url = raw.get("file_url") or _make_download_url(doc_id)
    file_url2 = raw.get("file_url2") or ""

    return {
        "id_documents": doc_id,
        "id_institucion": institution["id_institucion"],
        "institution_name": institution["nombre_institucion"],
        "institution_acronym": institution["acronym"],
        "id_tipo": institution["id_tipo"],
        "year": year,
        "estandar": raw.get("estandar", ""),
        "name": (raw.get("name") or "")[:500],
        "active": raw.get("active", ""),
        "downloads": _safe_int(raw.get("downloads")),
        "file_url": file_url,
        "file_url2": file_url2,
        "file_detalle": raw.get("file_detalle") or "",
        "has_annex": bool(raw.get("document_file_name_anexo")),
        "file_extension": _infer_extension(file_url),
        "local_path": "",
        "scraped_at": datetime.now().isoformat(),
    }


# ─────────────────────────────────────────────────────────────
# FILE DOWNLOAD
# ─────────────────────────────────────────────────────────────
def _safe_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = re.sub(r"\s+", "_", name.strip())
    return name[:200] if name else "document"


def download_file(record: dict, files_dir: Path) -> Optional[Path]:
    """
    Download the primary file for a record.
    Organises output as:  files/{institution_slug}/{year}/{doc_id}_{name}.{ext}
    Returns local Path on success, None on failure.
    """
    url = record["file_url"]
    if not url:
        return None

    inst_slug = _safe_filename(record["institution_acronym"] or str(record["id_institucion"]))
    year_str = str(record["year"]) if record["year"] else "unknown_year"
    dest_dir = files_dir / inst_slug / year_str
    dest_dir.mkdir(parents=True, exist_ok=True)

    doc_name = _safe_filename(record["name"] or str(record["id_documents"]))
    ext = record["file_extension"] or "bin"

    # Pre-determine a candidate filename; we may update ext after the response
    filename_stem = f"{record['id_documents']}_{doc_name}"

    resp = _get(url, delay=_request_delay * 1.3, stream=True)
    if resp is None:
        return None

    # Refine extension from Content-Type
    ctype = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
    if ctype in _MIME_TO_EXT:
        ext = _MIME_TO_EXT[ctype]

    dest_path = dest_dir / f"{filename_stem}.{ext}"

    if dest_path.exists():
        logger.debug("Already downloaded: %s", dest_path)
        return dest_path

    try:
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
        logger.debug("Downloaded: %s", dest_path)
        return dest_path
    except OSError as exc:
        logger.warning("Write error for %s: %s", dest_path, exc)
        return None


# ─────────────────────────────────────────────────────────────
# OUTPUT WRITERS
# ─────────────────────────────────────────────────────────────
def _init_csv(csv_path: Path) -> None:
    """Write the CSV header row if the file is new."""
    if not csv_path.exists():
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write(",".join(CSV_FIELDS) + "\n")


def _append_csv(csv_path: Path, records: list) -> None:
    with open(csv_path, "a", encoding="utf-8", newline="") as f:
        for rec in records:
            row = []
            for field in CSV_FIELDS:
                val = str(rec.get(field, "")).replace('"', '""')
                if any(ch in val for ch in (",", '"', "\n")):
                    val = f'"{val}"'
                row.append(val)
            f.write(",".join(row) + "\n")


def _append_jsonl(jsonl_path: Path, records: list) -> None:
    with open(jsonl_path, "a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ─────────────────────────────────────────────────────────────
# MAIN SCRAPER
# ─────────────────────────────────────────────────────────────
def run(
    only_id_tipo: Optional[int] = None,
    only_institution: Optional[int] = None,
    do_download: bool = False,
    resume: bool = False,
    output_dir: Path = Path("output/transparencia"),
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    files_dir = output_dir / "files"
    if do_download:
        files_dir.mkdir(parents=True, exist_ok=True)

    csv_path = output_dir / "metadata.csv"
    jsonl_path = output_dir / "metadata.jsonl"
    ckpt_path = output_dir / "checkpoint.json"

    _init_csv(csv_path)
    checkpoint = Checkpoint(ckpt_path)

    if not resume:
        checkpoint.data["completed_institutions"] = []
        checkpoint.save()

    # ── Step 1: Discover institutions ──────────────────────────
    if only_institution:
        institutions = [{
            "id_institucion": only_institution,
            "nombre_institucion": f"Institution {only_institution}",
            "acronym": str(only_institution),
            "id_tipo": 0,
            "officer_name": "",
            "officer_email": "",
        }]
    else:
        institutions = discover_all_institutions(only_id_tipo=only_id_tipo)

    if not institutions:
        logger.error("No institutions found — exiting.")
        return

    logger.info(
        "Scraping %d institutions | year >= %d | download=%s",
        len(institutions), START_YEAR, do_download,
    )

    total_docs = 0
    total_downloaded = 0

    # ── Step 2: Documents per institution ──────────────────────
    for i, inst in enumerate(institutions, 1):
        inst_id = inst["id_institucion"]

        if checkpoint.is_done(inst_id):
            logger.info("[%d/%d] Skip (done): %s [id=%d]",
                        i, len(institutions), inst["nombre_institucion"], inst_id)
            continue

        logger.info("[%d/%d] %s [id=%d]",
                    i, len(institutions), inst["nombre_institucion"], inst_id)

        raw_docs = fetch_documents_for_institution(inst_id)

        records: list = []
        for raw in raw_docs:
            rec = build_record(raw, inst)
            if rec is not None:
                records.append(rec)

        logger.info("  %d raw → %d kept (year >= %d)",
                    len(raw_docs), len(records), START_YEAR)

        dl_count = 0
        if do_download:
            for rec in records:
                local = download_file(rec, files_dir)
                if local:
                    rec["local_path"] = str(local)
                    dl_count += 1

        if records:
            _append_csv(csv_path, records)
            _append_jsonl(jsonl_path, records)

        total_docs += len(records)
        total_downloaded += dl_count
        checkpoint.mark_done(inst_id, len(records), dl_count)

        logger.info("  Saved %d records%s | Running total: %d",
                    len(records),
                    f" + {dl_count} files" if do_download else "",
                    total_docs)

    # ── Summary ────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("DONE")
    logger.info("Institutions processed: %d", len(institutions))
    logger.info("Documents collected  : %d", total_docs)
    if do_download:
        logger.info("Files downloaded     : %d", total_downloaded)
    logger.info("Metadata CSV  → %s", csv_path)
    logger.info("Metadata JSONL→ %s", jsonl_path)
    logger.info("=" * 60)


# ─────────────────────────────────────────────────────────────
# CLI ENTRY POINT
# ─────────────────────────────────────────────────────────────
def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Scrape document metadata (and optionally files) from "
            "https://www.transparencia.gob.sv/ since 2015."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--download", action="store_true",
        help="Also download the actual files (PDFs, XLSX, etc.) into output/transparencia/files/",
    )
    p.add_argument(
        "--id-tipo", type=int, default=None, metavar="N",
        help=(
            "Restrict to a single institution category. "
            "1=Ministerios, 2=Autónomas, 3=Presidencia, 4=Otras dependencias, "
            "5=Municipalidades, 6=Hospitales, 7=Gobernaciones, 8=ONG, "
            "10=Nuevas Municipalidades, 11=Órgano Legislativo"
        ),
    )
    p.add_argument(
        "--institution", type=int, default=None, metavar="ID",
        help="Scrape only one institution by its numeric id_institucion",
    )
    p.add_argument(
        "--resume", action="store_true",
        help="Resume from checkpoint (skip already-completed institutions)",
    )
    p.add_argument(
        "--output-dir", type=Path, default=Path("output/transparencia"),
        help="Root output directory (default: output/transparencia/)",
    )
    p.add_argument(
        "--delay", type=float, default=1.5,
        help="Seconds between requests (default: 1.5)",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    _request_delay = args.delay  # module-level reassignment (no global needed here)

    _setup_logging(args.output_dir / "logs")
    _session = _build_session()

    run(
        only_id_tipo=args.id_tipo,
        only_institution=args.institution,
        do_download=args.download,
        resume=args.resume,
        output_dir=args.output_dir,
    )
