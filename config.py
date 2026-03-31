"""
config.py — Configuration for El Salvador Political Text Dataset Builder

FILTERING PHILOSOPHY:
We only want articles relevant to Salvadoran national politics, governance,
public opinion, and policy. We filter OUT sports, entertainment, lifestyle,
local crime blotter (without political context), and international stories
unrelated to El Salvador.

We filter IN: political speeches, legislative actions, elections, party news,
security policy, economic policy, judicial matters, corruption, protests,
constitutional changes, human rights, and opinion/editorial about any of these.

DATE ENFORCEMENT:
Articles without extractable dates are DROPPED. The dataset is designed for
temporal NLP analysis mapped against key political events.
"""

import os
from datetime import date

# ──────────────────────────────────────────────────────────────
# Time window
# ──────────────────────────────────────────────────────────────
START_DATE = date(2015, 1, 1)
END_DATE = date(2025, 12, 31)
YEARS = list(range(2015, 2026))
MONTHS = list(range(1, 13))

# ──────────────────────────────────────────────────────────────
# Output paths
# ──────────────────────────────────────────────────────────────
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
RAW_HTML_DIR = os.path.join(OUTPUT_DIR, "raw_html")
LOG_DIR = os.path.join(OUTPUT_DIR, "logs")
CSV_OUTPUT = os.path.join(OUTPUT_DIR, "el_salvador_political_dataset.csv")
JSONL_OUTPUT = os.path.join(OUTPUT_DIR, "el_salvador_political_dataset.jsonl")

# ──────────────────────────────────────────────────────────────
# Date enforcement
# ──────────────────────────────────────────────────────────────
REQUIRE_DATE = True  # If True, articles without a parseable date are DROPPED

# ──────────────────────────────────────────────────────────────
# Rate limiting
# ──────────────────────────────────────────────────────────────
DEFAULT_DELAY = 1.5
GOV_DELAY = 2.5
GDELT_DELAY = 1.0
REQUEST_TIMEOUT = 30

# ──────────────────────────────────────────────────────────────
# HTTP settings
# ──────────────────────────────────────────────────────────────
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Full Chrome-level headers — many anti-bot systems check for these.
# Missing Accept-Encoding, Sec-Fetch-*, or Connection triggers 403 on Cloudflare sites.
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7"
    ),
    "Accept-Language": "es-SV,es;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
    "DNT": "1",
}

# Alternate user-agents to rotate on 403 responses
ALTERNATE_USER_AGENTS = [
    # Firefox on Windows
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
        "Gecko/20100101 Firefox/125.0"
    ),
    # Chrome on macOS
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    # Safari on macOS
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.4.1 Safari/605.1.15"
    ),
]

MAX_RETRIES = 3

# ══════════════════════════════════════════════════════════════
# POLITICAL RELEVANCE FILTER
#
# An article must score >= RELEVANCE_THRESHOLD to be included.
# Score = number of matching keywords found in (title + first 1000 chars).
# Higher-weight terms (in RELEVANCE_KEYWORDS_STRONG) count double.
# ══════════════════════════════════════════════════════════════
RELEVANCE_THRESHOLD = 40  # minimum keyword hits to keep an article

# Strong signals (count as 2 points each) — directly political
RELEVANCE_KEYWORDS_STRONG = [
    # People
    "bukele", "nayib bukele", "sánchez cerén", "sanchez ceren",
    "mauricio funes", "félix ulloa", "felix ulloa",
    # Parties
    "nuevas ideas", "fmln", "arena", "gana", "pcn",
    # Institutions
    "asamblea legislativa", "corte suprema", "sala de lo constitucional",
    "fiscalía general", "fiscalia general", "tribunal supremo electoral",
    "corte de cuentas", "procuraduría", "procuraduria",
    # Governance
    "estado de excepción", "estado de excepcion", "régimen de excepción",
    "decreto legislativo", "decreto ejecutivo", "reforma constitucional",
    "reelección", "reeleccion",
    # Key policies
    "bitcoin ley", "ley bitcoin", "chivo wallet",
    "plan control territorial", "guerra contra pandillas",
    # Key events
    "elecciones presidenciales", "elecciones legislativas",
    "toma de posesión", "golpe de estado",
]

# Normal signals (count as 1 point each) — political context
RELEVANCE_KEYWORDS_NORMAL = [
    # General political terms
    "presidente", "gobierno", "ministro", "ministra", "viceministro",
    "diputado", "diputada", "diputados", "congreso", "legislatura",
    "gabinete", "secretario", "política", "politica", "político", "politico",
    "elecciones", "elección", "eleccion", "candidato", "candidata",
    "campaña electoral", "campaña", "voto", "votación", "votacion",
    "oposición", "oposicion", "partido", "coalición", "coalicion",
    # Security & justice
    "seguridad", "pandillas", "maras", "mara salvatrucha", "barrio 18",
    "homicidios", "régimen", "regimen", "militares", "policía", "policia",
    "fuerza armada", "estado de emergencia", "penales", "megacárcel",
    "cecot", "detenciones masivas",
    # Economy & policy
    "economía", "economia", "presupuesto", "deuda pública", "deuda publica",
    "impuestos", "bitcoin", "dólar", "dolar", "inversión", "inversion",
    "remesas", "empleo", "desempleo", "pobreza",
    # Corruption & accountability
    "corrupción", "corrupcion", "corrupto", "soborno", "lavado de dinero",
    "malversación", "malversacion", "impunidad", "transparencia",
    "rendición de cuentas", "CICIES", "auditoría", "auditoria",
    "investigación penal", "acusación", "acusacion",
    # Human rights & civil society
    "derechos humanos", "libertad de prensa", "libertad de expresión",
    "protesta", "manifestación", "manifestacion", "sociedad civil",
    "organizaciones sociales", "ONG",
    # Constitutional & legal
    "constitución", "constitucion", "ley", "decreto", "reforma",
    "inconstitucional", "jurídico", "juridico",
    # Opinion & discourse
    "opinión", "opinion", "editorial", "análisis", "analisis",
    "columna", "encuesta", "aprobación", "aprobacion", "popularidad",
    # International relations (El Salvador specific)
    "relaciones exteriores", "embajador", "estados unidos",
    "cooperación internacional", "migración", "migracion",
    "deportación", "deportacion", "TPS", "asilo",
]

# Negative signals — if title contains ONLY these, likely not political
IRRELEVANCE_KEYWORDS = [
    "deportes", "fútbol", "futbol", "liga mayor", "selecta",
    "béisbol", "beisbol", "baloncesto",
    "farándula", "farandula", "entretenimiento", "celebridad",
    "receta", "cocina", "horóscopo", "horoscopo",
    "clima", "pronóstico del tiempo",
    "clasificados", "bienes raíces", "bienes raices",
]

# ══════════════════════════════════════════════════════════════
# KEY POLITICAL EVENTS TIMELINE (for reference/tagging)
# These are used to tag articles that fall near key dates.
# ══════════════════════════════════════════════════════════════
KEY_EVENTS = [
    {"date": "2015-03-01", "event": "Sánchez Cerén first full year as president"},
    {"date": "2015-03-01", "event": "Legislative elections 2015"},
    {"date": "2016-03-25", "event": "Supreme Court ruling on gang truce"},
    {"date": "2017-03-04", "event": "Legislative elections 2017"},
    {"date": "2018-03-04", "event": "Municipal elections 2018"},
    {"date": "2019-02-03", "event": "Presidential election — Bukele wins"},
    {"date": "2019-06-01", "event": "Bukele inaugurated as president"},
    {"date": "2020-02-09", "event": "Bukele sends military into Asamblea Legislativa"},
    {"date": "2020-03-21", "event": "COVID-19 state of emergency declared"},
    {"date": "2021-02-28", "event": "Legislative elections — Nuevas Ideas supermajority"},
    {"date": "2021-05-01", "event": "New Asamblea removes Supreme Court justices"},
    {"date": "2021-06-09", "event": "Bitcoin Law approved"},
    {"date": "2021-09-07", "event": "Bitcoin becomes legal tender"},
    {"date": "2021-09-03", "event": "Supreme Court allows presidential reelection"},
    {"date": "2022-03-27", "event": "State of exception declared (gang crackdown)"},
    {"date": "2022-03-27", "event": "Régimen de excepción begins"},
    {"date": "2023-11-01", "event": "CECOT mega-prison opens"},
    {"date": "2024-02-04", "event": "Presidential election — Bukele reelected"},
    {"date": "2024-06-01", "event": "Bukele second term inauguration"},
    {"date": "2025-01-01", "event": "Continued régimen de excepción"},
]

# ══════════════════════════════════════════════════════════════
# ENGAGEMENT METRICS EXTRACTION
# CSS selectors and meta tags to look for like/comment/share counts.
# These vary by site; we try multiple patterns.
# ══════════════════════════════════════════════════════════════
ENGAGEMENT_META_PROPERTIES = [
    # Facebook Open Graph
    "og:comments_count",
    "og:likes",
    # Schema.org / article metadata
    "commentCount",
    "interactionCount",
]

ENGAGEMENT_CSS_SELECTORS = {
    # Selector → metric name mapping
    # These target common patterns across WordPress themes and news sites
    "comments": [
        ".comments-count", ".comment-count", ".num-comments",
        ".disqus-comment-count", ".fb-comments-count",
        "span.comments", "a.comments-link span",
        ".comentarios", ".num-comentarios",
        'meta[property="commentCount"]',
    ],
    "likes": [
        ".like-count", ".likes-count", ".num-likes",
        ".fb-like-count", ".reaction-count",
        'span[data-testid="like_count"]',
    ],
    "shares": [
        ".share-count", ".shares-count", ".num-shares",
        ".social-count", ".shared-count",
        ".compartir-count", ".veces-compartido",
    ],
    "views": [
        ".view-count", ".views-count", ".num-views",
        ".post-views", ".entry-views", ".visitas",
    ],
}

# ══════════════════════════════════════════════════════════════
# SOURCES (same as before — trimmed for clarity)
# ══════════════════════════════════════════════════════════════
SITEMAP_SOURCES = [
    {
        "sitemap_url": "https://elfaro.net/sitemap.xml",
        "source_key": "elfaro_sm",
        "source_name": "El Faro",
        "source_type": "news",
        "document_type": "news_article",
        "outlet": "El Faro",
        "delay": DEFAULT_DELAY,
    },
    {
        "sitemap_url": "https://www.laprensagrafica.com/sitemap.xml",
        "source_key": "lpg_sm",
        "source_name": "La Prensa Gráfica",
        "source_type": "news",
        "document_type": "news_article",
        "outlet": "La Prensa Gráfica",
        "delay": DEFAULT_DELAY,
    },
    {
        "sitemap_url": "https://www.elsalvador.com/sitemap.xml",
        "source_key": "elsalvador_sm",
        "source_name": "El Diario de Hoy",
        "source_type": "news",
        "document_type": "news_article",
        "outlet": "El Diario de Hoy",
        "delay": DEFAULT_DELAY,
    },
    {
        "sitemap_url": "https://diario.elmundo.sv/sitemap.xml",
        "source_key": "elmundo_sm",
        "source_name": "Diario El Mundo",
        "source_type": "news",
        "document_type": "news_article",
        "outlet": "Diario El Mundo",
        "delay": DEFAULT_DELAY,
    },
    {
        "sitemap_url": "https://www.presidencia.gob.sv/sitemap.xml",
        "source_key": "presidencia_sm",
        "source_name": "Presidencia de El Salvador",
        "source_type": "government",
        "document_type": "press_release",
        "outlet": "",
        "delay": GOV_DELAY,
    },
    {
        "sitemap_url": "https://www.asamblea.gob.sv/sitemap.xml",
        "source_key": "asamblea_sm",
        "source_name": "Asamblea Legislativa",
        "source_type": "government",
        "document_type": "transcript",
        "outlet": "",
        "delay": GOV_DELAY,
    },
]

GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"

# Focused search terms — all politically relevant
GDELT_SEARCH_TERMS = [
    "El Salvador politica",
    "Bukele El Salvador",
    "Asamblea Legislativa El Salvador",
    "gobierno El Salvador",
    "presidente El Salvador",
    "seguridad El Salvador pandillas",
    "bitcoin ley El Salvador",
    "estado de excepcion El Salvador",
    "FMLN ARENA El Salvador",
    "Nuevas Ideas partido",
    "elecciones El Salvador",
    "corrupcion El Salvador",
    "derechos humanos El Salvador",
    "Constitucion reforma El Salvador",
    "economia presupuesto El Salvador",
    "Sanchez Ceren presidente",
    "Fiscalia General El Salvador",
    "militares Asamblea El Salvador",
    "CECOT El Salvador",
    "regimen excepcion El Salvador",
]

DATE_ARCHIVE_SOURCES = [
    {
        "archive_template": "https://www.presidencia.gob.sv/{year}/{month:02d}/",
        "archive_page_template": "https://www.presidencia.gob.sv/{year}/{month:02d}/page/{page}/",
        "source_key": "presidencia_arch",
        "source_name": "Presidencia de El Salvador",
        "source_type": "government",
        "document_type": "press_release",
        "outlet": "",
        "delay": GOV_DELAY,
        "link_selector": "h2 a, h3 a, .entry-title a, article a[href]",
        "content_selector": ".entry-content, .post-content, article .content, .the-content",
        "max_sub_pages": 20,
        "is_government": True,  # skip relevance filter for govt sources
    },
    {
        "archive_template": "https://elfaro.net/{year}/{month:02d}/",
        "archive_page_template": "https://elfaro.net/{year}/{month:02d}/page/{page}/",
        "source_key": "elfaro_arch",
        "source_name": "El Faro",
        "source_type": "news",
        "document_type": "news_article",
        "outlet": "El Faro",
        "delay": DEFAULT_DELAY,
        "link_selector": "h2 a, h3 a, .entry-title a, article a[href], .story a[href]",
        "content_selector": "article, .entry-content, .post-content, .article-body, .story-body",
        "max_sub_pages": 10,
        "is_government": False,
    },
    {
        "archive_template": "https://www.laprensagrafica.com/{year}/{month:02d}/",
        "archive_page_template": "https://www.laprensagrafica.com/{year}/{month:02d}/page/{page}/",
        "source_key": "lpg_arch",
        "source_name": "La Prensa Gráfica",
        "source_type": "news",
        "document_type": "news_article",
        "outlet": "La Prensa Gráfica",
        "delay": DEFAULT_DELAY,
        "link_selector": "h2 a, h3 a, .entry-title a, article a[href], a.article-link",
        "content_selector": "article, .entry-content, .post-content, .article-body",
        "max_sub_pages": 10,
        "is_government": False,
    },
    {
        "archive_template": "https://www.elsalvador.com/{year}/{month:02d}/",
        "archive_page_template": "https://www.elsalvador.com/{year}/{month:02d}/page/{page}/",
        "source_key": "elsalvador_arch",
        "source_name": "El Diario de Hoy",
        "source_type": "news",
        "document_type": "news_article",
        "outlet": "El Diario de Hoy",
        "delay": DEFAULT_DELAY,
        "link_selector": "h2 a, h3 a, .entry-title a, article a[href]",
        "content_selector": "article, .entry-content, .post-content, .article-body",
        "max_sub_pages": 10,
        "is_government": False,
    },
    {
        "archive_template": "https://diario.elmundo.sv/{year}/{month:02d}/",
        "archive_page_template": "https://diario.elmundo.sv/{year}/{month:02d}/page/{page}/",
        "source_key": "elmundo_arch",
        "source_name": "Diario El Mundo",
        "source_type": "news",
        "document_type": "news_article",
        "outlet": "Diario El Mundo",
        "delay": DEFAULT_DELAY,
        "link_selector": "h2 a, h3 a, .entry-title a, article a[href]",
        "content_selector": "article, .entry-content, .post-content, .article-body",
        "max_sub_pages": 10,
        "is_government": False,
    },
]

SEARCH_KEYWORDS = [
    "Bukele", "gobierno", "politica", "asamblea legislativa",
    "seguridad", "estado de excepcion", "bitcoin",
    "FMLN", "ARENA", "elecciones", "Sanchez Ceren",
    "corrupcion", "pandillas", "Nuevas Ideas",
]

PAGINATED_SOURCES = [
    {
        "search_template": "https://elfaro.net/page/{page}/?s={keyword}",
        "source_key": "elfaro_srch",
        "source_name": "El Faro",
        "source_type": "news",
        "document_type": "news_article",
        "outlet": "El Faro",
        "max_pages_per_keyword": 50,
        "delay": DEFAULT_DELAY,
        "link_selector": "h2 a, h3 a, .entry-title a, article a[href], .story a[href]",
        "content_selector": "article, .entry-content, .post-content, .article-body",
    },
    {
        "search_template": "https://www.laprensagrafica.com/page/{page}/?s={keyword}",
        "source_key": "lpg_srch",
        "source_name": "La Prensa Gráfica",
        "source_type": "news",
        "document_type": "news_article",
        "outlet": "La Prensa Gráfica",
        "max_pages_per_keyword": 50,
        "delay": DEFAULT_DELAY,
        "link_selector": "h2 a, h3 a, .entry-title a, article a[href], a.article-link",
        "content_selector": "article, .entry-content, .post-content, .article-body",
    },
    {
        "search_template": "https://www.elsalvador.com/noticias/page/{page}/?s={keyword}",
        "source_key": "elsalvador_srch",
        "source_name": "El Diario de Hoy",
        "source_type": "news",
        "document_type": "news_article",
        "outlet": "El Diario de Hoy",
        "max_pages_per_keyword": 50,
        "delay": DEFAULT_DELAY,
        "link_selector": "h2 a, h3 a, .entry-title a, article a[href]",
        "content_selector": "article, .entry-content, .post-content, .article-body",
    },
]

RSS_SOURCES = [
    {
        "feed_url": "https://www.presidencia.gob.sv/feed/",
        "source_key": "presidencia_rss",
        "source_name": "Presidencia de El Salvador",
        "source_type": "government",
        "document_type": "press_release",
        "outlet": "", "delay": GOV_DELAY,
        "is_government": True,
    },
    {
        "feed_url": "https://elfaro.net/feed/",
        "source_key": "elfaro_rss",
        "source_name": "El Faro",
        "source_type": "news",
        "document_type": "news_article",
        "outlet": "El Faro", "delay": DEFAULT_DELAY,
    },
    {
        "feed_url": "https://www.elsalvador.com/rss/",
        "source_key": "elsalvador_rss",
        "source_name": "El Diario de Hoy",
        "source_type": "news",
        "document_type": "news_article",
        "outlet": "El Diario de Hoy", "delay": DEFAULT_DELAY,
    },
    {
        "feed_url": "https://www.laprensagrafica.com/rss",
        "source_key": "lpg_rss",
        "source_name": "La Prensa Gráfica",
        "source_type": "news",
        "document_type": "news_article",
        "outlet": "La Prensa Gráfica", "delay": DEFAULT_DELAY,
    },
]

NEWSPAPER3K_SOURCES = [
    {
        "base_url": "https://elfaro.net",
        "source_key": "elfaro_n3k",
        "source_name": "El Faro",
        "source_type": "news",
        "document_type": "news_article",
        "outlet": "El Faro", "max_articles": 500,
    },
    {
        "base_url": "https://www.laprensagrafica.com",
        "source_key": "lpg_n3k",
        "source_name": "La Prensa Gráfica",
        "source_type": "news",
        "document_type": "news_article",
        "outlet": "La Prensa Gráfica", "max_articles": 500,
    },
    {
        "base_url": "https://www.elsalvador.com",
        "source_key": "elsalvador_n3k",
        "source_name": "El Diario de Hoy",
        "source_type": "news",
        "document_type": "news_article",
        "outlet": "El Diario de Hoy", "max_articles": 500,
    },
    {
        "base_url": "https://diario.elmundo.sv",
        "source_key": "elmundo_n3k",
        "source_name": "Diario El Mundo",
        "source_type": "news",
        "document_type": "news_article",
        "outlet": "Diario El Mundo", "max_articles": 500,
    },
    {
        "base_url": "https://www.bbc.com/mundo/topics/c1e9mglz34lt",
        "source_key": "bbc_n3k",
        "source_name": "BBC Mundo",
        "source_type": "news",
        "document_type": "news_article",
        "outlet": "BBC Mundo", "max_articles": 300,
    },
]

# ──────────────────────────────────────────────────────────────
# Key speakers to auto-tag
# ──────────────────────────────────────────────────────────────
KEY_SPEAKERS = {
    "bukele": "Nayib Bukele",
    "nayib bukele": "Nayib Bukele",
    "presidente bukele": "Nayib Bukele",
    "sánchez cerén": "Salvador Sánchez Cerén",
    "sanchez ceren": "Salvador Sánchez Cerén",
    "mauricio funes": "Mauricio Funes",
    "félix ulloa": "Félix Ulloa",
    "felix ulloa": "Félix Ulloa",
}

# ──────────────────────────────────────────────────────────────
# Corruption keywords (for enrichment column)
# ──────────────────────────────────────────────────────────────
CORRUPTION_KEYWORDS = [
    "corrupción", "corrupto", "corruptos", "soborno", "sobornos",
    "lavado de dinero", "lavado de activos", "malversación", "peculado",
    "enriquecimiento ilícito", "fraude", "desvío de fondos", "nepotismo",
    "impunidad", "cohecho", "tráfico de influencias", "conflicto de interés",
    "conflicto de intereses", "desfalco", "colusión", "extorsión",
    "transparencia", "rendición de cuentas", "auditoría", "fiscalización",
    "enriquecimiento", "fondos públicos", "irregularidades",
    "investigación penal", "acusación", "Fiscalía General",
    "Corte de Cuentas", "CICIES", "Sección de Probidad",
]

# ──────────────────────────────────────────────────────────────
# Boilerplate phrases to strip
# ──────────────────────────────────────────────────────────────
BOILERPLATE_PHRASES = [
    "Todos los derechos reservados", "Política de privacidad",
    "Términos y condiciones", "Suscríbete a nuestro boletín",
    "Comparte esta noticia", "Síguenos en redes sociales",
    "Lee también:", "Te puede interesar:", "Contenido relacionado",
    "Copyright ©", "Publicidad", "Más noticias",
    "Noticias relacionadas", "Tags:", "Etiquetas:",
]

# ──────────────────────────────────────────────────────────────
# URL patterns to SKIP
# ──────────────────────────────────────────────────────────────
SKIP_URL_PATTERNS = [
    r"\.(jpg|jpeg|png|gif|svg|webp|ico|pdf|css|js|xml|json|woff|ttf|mp3|mp4|avi)(\?|$)",
    r"/tag/", r"/tags/", r"/category/", r"/autor/", r"/author/",
    r"/feed/", r"/rss/", r"/wp-content/", r"/wp-admin/", r"/wp-includes/",
    r"/wp-json/", r"^https?://[^/]+/?$",
    r"#", r"mailto:", r"javascript:",
    r"/login", r"/register", r"/suscripcion", r"/contacto",
    # Skip non-political sections by URL path segment
    r"/deportes/", r"/sports/", r"/entretenimiento/", r"/farandula/",
    r"/clasificados/", r"/horoscopo/", r"/recetas/", r"/vida/",
    # International news — not El Salvador domestic politics
    r"/internacional/", r"/mundo/", r"/global/",
    # elsalvador.com uses h- prefixed section paths — exclude the non-political ones
    r"/h-deportes/", r"/h-internacional/", r"/h-entretenimiento/",
    r"/h-tecnologia/", r"/h-salud/", r"/h-vida/", r"/h-espectaculos/",
    # Other common non-political sections
    r"/tecnologia/", r"/salud/", r"/espectaculos/", r"/turismo/",
    r"/moda/", r"/belleza/", r"/mascotas/",
]
