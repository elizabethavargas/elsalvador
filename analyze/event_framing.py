"""
event_framing.py — Compare how government tweets vs independent media
framed the same key political events.

For each event, generates a side-by-side word cloud pair:
  LEFT  (red)  — words most used in government tweets
  RIGHT (blue) — words most used in media articles
Word size reflects frequency within the ±30-day window.

OUTPUTS (output/event_framing/):
  viz_wordclouds.html  — all events stacked, govt vs media clouds
"""

import base64
import csv
import io
import math
import os
import re
from collections import Counter, defaultdict
from datetime import date, timedelta

import matplotlib
matplotlib.use("Agg")
from wordcloud import WordCloud

REPO_ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TWEETS_CSV = os.path.join(REPO_ROOT, "output", "data", "tweets.csv")
MEDIA_CSV  = os.path.join(REPO_ROOT, "output", "articles_text_clean.csv")
OUTPUT_DIR = os.path.join(REPO_ROOT, "output", "event_framing")

# Government accounts used as "official narrative" side
GOVT_ACCOUNTS = {"nayibbukele", "presidenciasv", "gobierno_sv", "asambleasv", "fgr_sv"}

# Independent media only (exclude government-run outlets)
MEDIA_DOMAINS = {
    "lapagina.com.sv", "elmundo.sv", "diariocolatino.com",
    "elfaro.net", "diario1.com", "ultimahora.sv",
}

KEY_EVENTS = [
    ("Inauguración de Bukele",         "2019-06-01"),
    ("Militares en Asamblea",          "2020-02-09"),
    ("Emergencia COVID",               "2020-03-21"),
    ("Elecciones (Nuevas Ideas gana)", "2021-02-28"),
    ("CECOT inaugurado",               "2023-11-01"),
    ("Segundo mandato Bukele",         "2024-06-01"),
]
WINDOW_DAYS = 30
MIN_TWEETS   = 100
MIN_ARTICLES = 20
MIN_FREQ     = 5   # minimum occurrences in window to be shown

STOP = {
    "de","la","el","en","y","a","que","los","las","del","se","por","con",
    "una","es","su","al","le","no","si","lo","les","más","para","como",
    "pero","sus","me","mi","fue","ha","un","te","yo","son","ya","o","hay",
    "este","esta","esto","estos","estas","era","ser","han","he","ni",
    "también","muy","tan","todo","todos","toda","todas","ese","esa","esos",
    "esas","porque","cuando","sobre","entre","sin","hasta","desde","donde",
    "bien","solo","puede","tienen","hacer","tiene","así","vez","años","año",
    "día","días","hoy","ahora","país","parte","ante","cada","quien",
    "qué","cómo","cuál","cuándo","nosotros","nuestros","nuestra","nuestras",
    "nuestro","durante","mediante","dentro","fuera","mismo","misma","menos",
    "mayor","mejor","bajo","tanto","aunque","según","pues","junto","hacia",
    "tras","contra","través","están","estamos","estaba","estar","había",
    "hemos","vamos","han","fué","deja","dicho","algo","nada","nadie",
    "otro","otros","otra","otras","ellos","ellas","ella","él","usted",
    "ustedes","nos","vos","eso","algo","ahí","allí","aquí","acá",
    "https","http","co","rt","pic","twitter","amp","via","hace","meses","horas",
    # ── El Salvador / demonyms (appear in every document, uninformative) ──
    "salvador","salvadoreño","salvadoreña","salvadoreños","salvadoreñas",
    "elsalvador",
    # ── Media outlet names / branding artifacts ───────────────────────────
    "diario","colatino","lapagina","pagina","página","elfaro","elmundo",
    "mundo","prensa","grafica","noticias","noticia","redaccion","redacción",
    "periodico","periódico","digital","online","web","sitio",
    # ── Scraping split-word / section-name artifacts ──────────────────────
    "gina","smoda","moda","talento",
    # ── Scraping / navigation / 404 artifacts ─────────────────────────────
    "not","found","error","page","section","loading","enabled","browser",
    "existe","encontramos","buscas","regresando","encontrar","encontrado",
    "buscar","búsqueda","busqueda","regresar","volviendo","intentalo",
    "inténtalo","disponible","eliminada","movida","trasladada",
    "navegando","leer","continuar","siguiente","anterior","volver","inicio",
    "menu","menú","home","cookies","privacidad","términos","terminos",
    "política","reservados","derechos","copyright","publicidad","anuncio",
    "suscribete","suscríbete","suscribirse","subscríbete","registrate",
    "compartir","facebook","instagram","youtube","whatsapp","telegram",
    "javascript","archivo","enlace","acceso","buscar","search","click",
    "ver","leer","nota","artículo","articulo","imagen","foto","video",
}


def tokenize(text):
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"@\w+", " ", text)
    text = re.sub(r"#\w+", " ", text)
    tokens = re.findall(r"\b[a-záéíóúüñ]{3,}\b", text.lower())
    return [t for t in tokens if t not in STOP]


def log_odds(c_a, total_a, c_b, total_b):
    p_a = (c_a + 0.5) / (total_a + 0.5)
    p_b = (c_b + 0.5) / (total_b + 0.5)
    p_a = min(max(p_a, 1e-9), 1 - 1e-9)
    p_b = min(max(p_b, 1e-9), 1 - 1e-9)
    return math.log(p_a / (1 - p_a)) - math.log(p_b / (1 - p_b))


# ─────────────────────────────────────────────
# LOAD DATA
# ─────────────────────────────────────────────
def load_tweets():
    """Returns list of (date_obj, tokens) for government accounts."""
    print("[load] tweets ...")
    rows = []
    with open(TWEETS_CSV, encoding="utf-8-sig", errors="replace") as f:
        for r in csv.DictReader(f):
            if r.get("handle", "").lower() not in GOVT_ACCOUNTS:
                continue
            try:
                d = date.fromisoformat(r["date"][:10])
            except Exception:
                continue
            rows.append((d, tokenize(r.get("text", ""))))
    print(f"  {len(rows):,} government tweets loaded")
    return rows


def load_articles():
    """Returns list of (year_month str 'YYYY-MM', tokens) for independent media."""
    print("[load] media articles ...")
    rows = []
    with open(MEDIA_CSV, encoding="utf-8-sig", errors="replace") as f:
        for r in csv.DictReader(f):
            if r.get("domain", "") not in MEDIA_DOMAINS:
                continue
            ym = r.get("year", "") + "-" + r.get("month", "").zfill(2)
            text = r.get("title", "") + " " + r.get("text", "")[:800]
            rows.append((ym, tokenize(text)))
    print(f"  {len(rows):,} media articles loaded")
    return rows


# ─────────────────────────────────────────────
# WINDOW HELPERS
# ─────────────────────────────────────────────
def months_in_window(event_date, window=WINDOW_DAYS):
    """Return set of 'YYYY-MM' strings that overlap with the ±window day range."""
    start = event_date - timedelta(days=window)
    end   = event_date + timedelta(days=window)
    months = set()
    d = start.replace(day=1)
    while d <= end:
        months.add(d.strftime("%Y-%m"))
        # advance one month
        if d.month == 12:
            d = d.replace(year=d.year + 1, month=1)
        else:
            d = d.replace(month=d.month + 1)
    return months


def window_tokens(tweet_rows, article_rows, event_date):
    """
    Returns (tweet_tokens_flat, article_tokens_flat) for the ±WINDOW_DAYS window.
    """
    ed = event_date
    lo = ed - timedelta(days=WINDOW_DAYS)
    hi = ed + timedelta(days=WINDOW_DAYS)
    months = months_in_window(ed)

    t_tokens = []
    for d, tokens in tweet_rows:
        if lo <= d <= hi:
            t_tokens.extend(tokens)

    a_tokens = []
    for ym, tokens in article_rows:
        if ym in months:
            a_tokens.extend(tokens)

    return t_tokens, a_tokens


# ─────────────────────────────────────────────
# WORD CLOUD HELPERS
# ─────────────────────────────────────────────
def make_cloud_png(freq_dict, colormap, max_words=80, width=700, height=380):
    """Render a WordCloud to a base64 PNG string."""
    if not freq_dict:
        return None
    wc = WordCloud(
        width=width, height=height,
        background_color="white",
        colormap=colormap,
        max_words=max_words,
        prefer_horizontal=0.85,
        min_font_size=10,
        max_font_size=100,
        relative_scaling=0.55,
        collocations=False,
    ).generate_from_frequencies(freq_dict)
    buf = io.BytesIO()
    wc.to_image().save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


# ─────────────────────────────────────────────
# VIZ: Side-by-side word clouds per event
# ─────────────────────────────────────────────
def viz_wordclouds(tweet_rows, article_rows):
    print("[viz] word clouds ...")

    sections = []   # list of HTML blocks, one per event

    for label, date_str in KEY_EVENTS:
        ed = date.fromisoformat(date_str)
        t_tok, a_tok = window_tokens(tweet_rows, article_rows, ed)
        t_count = Counter(t_tok)
        a_count = Counter(a_tok)
        n_t, n_a = len(t_tok), len(a_tok)

        if n_t < MIN_TWEETS or n_a < MIN_ARTICLES:
            print(f"  [skip] {label}: {n_t} tweet tokens / {n_a} article tokens")
            continue

        print(f"  {label}: {n_t:,} tweet tokens, {n_a:,} article tokens")

        # filter to words with at least MIN_FREQ occurrences on their dominant side
        t_freq = {w: c for w, c in t_count.items() if c >= MIN_FREQ}
        a_freq = {w: c for w, c in a_count.items() if c >= MIN_FREQ}

        govt_png  = make_cloud_png(t_freq, "Reds")
        media_png = make_cloud_png(a_freq, "Blues")

        def img_tag(b64):
            if not b64:
                return "<p style='color:#aaa;text-align:center;padding:60px'>no data</p>"
            return f"<img src='data:image/png;base64,{b64}' style='width:100%;border-radius:6px'>"

        sections.append(f"""
<div class="event-block">
  <h2>{label}
    <span class="meta">±{WINDOW_DAYS} days &nbsp;·&nbsp;
      <span style="color:#c0392b">{n_t:,} tweet tokens</span> &nbsp;·&nbsp;
      <span style="color:#2471a3">{n_a:,} article tokens</span>
    </span>
  </h2>
  <div class="cloud-row">
    <div class="cloud-col">
      <div class="cloud-label govt">Government tweets</div>
      {img_tag(govt_png)}
    </div>
    <div class="cloud-col">
      <div class="cloud-label media">Media articles</div>
      {img_tag(media_png)}
    </div>
  </div>
</div>
""")

    if not sections:
        print("  No events had sufficient data.")
        return

    html = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Event Framing: Government vs Media</title>
<style>
  body { font-family: 'Helvetica Neue', sans-serif; max-width: 1300px;
         margin: 0 auto; padding: 24px 32px; background: #f9f9f9; color: #222; }
  h1   { font-size: 1.5em; margin-bottom: 4px; }
  .subtitle { color: #666; font-size: 0.9em; margin-bottom: 36px; }
  .event-block { background: white; border-radius: 10px;
                 box-shadow: 0 1px 4px rgba(0,0,0,.08);
                 padding: 24px 28px; margin-bottom: 36px; }
  .event-block h2 { font-size: 1.2em; margin: 0 0 16px; }
  .meta { font-size: 0.72em; font-weight: normal; color: #888;
          margin-left: 10px; }
  .cloud-row { display: flex; gap: 20px; }
  .cloud-col { flex: 1; }
  .cloud-label { font-size: 0.82em; font-weight: bold; letter-spacing: .04em;
                 text-transform: uppercase; margin-bottom: 8px; }
  .cloud-label.govt  { color: #c0392b; }
  .cloud-label.media { color: #2471a3; }
</style>
</head>
<body>
<h1>Event Framing: Government Tweets vs Media Articles</h1>
<p class="subtitle">
  Each word cloud shows the most frequent words used within ±""" + str(WINDOW_DAYS) + """ days of the event.<br>
  Word size = raw frequency in that window &nbsp;·&nbsp;
  Government accounts: nayibbukele, PresidenciaSV, Gobierno_SV, AsambleaSV, FGR_SV<br>
  Media outlets: La Página, El Mundo, Diario Co Latino, El Faro, Diario 1
</p>
""" + "\n".join(sections) + """
</body>
</html>"""

    path = os.path.join(OUTPUT_DIR, "viz_wordclouds.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  -> {path}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print("=" * 60)
    print("Event Framing: Government Tweets vs Media Articles")
    print("=" * 60)
    print(f"Window: ±{WINDOW_DAYS} days around each event")
    print()

    tweet_rows   = load_tweets()
    article_rows = load_articles()

    viz_wordclouds(tweet_rows, article_rows)

    print("\nDone. Outputs in", OUTPUT_DIR)


if __name__ == "__main__":
    main()
