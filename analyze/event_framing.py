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
import sys
csv.field_size_limit(sys.maxsize)
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
MEDIA_CSV  = os.path.join(REPO_ROOT, "output", "articles_master.csv")
OUTPUT_DIR = os.path.join(REPO_ROOT, "output", "event_framing")

# Government accounts used as "official narrative" side
GOVT_ACCOUNTS = {"nayibbukele", "presidenciasv", "gobierno_sv", "asambleasv", "fgr_sv"}

# Independent media only (exclude government-run outlets)
MEDIA_DOMAINS = {
    "lapagina.com.sv", "elmundo.sv", "diariocolatino.com",
    "elfaro.net", "diario1.com", "ultimahora.sv",
}

KEY_EVENTS = [
    ("Bukele Inauguration",            "2019-06-01"),
    ("Military Surrounds Legislature", "2020-02-09"),
    ("COVID Emergency Decree",         "2020-03-21"),
    ("Elections: Nuevas Ideas Wins",   "2021-02-28"),
    ("CECOT Mega-Prison Opens",        "2023-11-01"),
    ("Bukele Second Term Begins",      "2024-06-01"),
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
    # ── HTML / CSS class artifacts from CMS scraping ──────────────────────
    "align","aligncenter","alignleft","alignright","alignnone",
    "wp","caption","size","full","large","medium","thumbnail","attachment",
    "class","style","width","height","src","alt","href","rel","type","data",
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
    # ── Social-media / CMS UI artifacts ──────────────────────────────────────
    "comentarios","comentario","desactivados","desactivado","vistas","vista",
    "compartidos","compartido","reacciones","reaccion","reacción",
    "publicado","publicar","editar","eliminar","reportar","guardar","seguir",
    # ── Days of week (date metadata leaking into article text) ────────────────
    "lunes","martes","miércoles","miercoles","jueves","viernes",
    "sábado","sabado","domingo",
    # ── Standalone geography prefixes (noise without their second word) ───────
    "san","santa","nueva",
    # ── Outlet self-references ────────────────────────────────────────────────
    "diariocolatino","lapagina","elfaro","elmundo","presidencia","faro",
    # ── Drop-cap residue ──────────────────────────────────────────────────────
    "ste","nte","uego","uatro","iembros","iputados","olona","urante","oen","ctón",
    # ── Encoding garble artifacts ─────────────────────────────────────────────
    "repã","blica","redacciã","oacute","aacute","eacute","iacute","uacute",
    "yeerles","intimissimun","administraador",
    # ── Navigation / section labels ───────────────────────────────────────────
    "columna","columnas","portada","articulos","tags","tag","psd","lnf",
    # ── Common abbreviations that become noise tokens ─────────────────────────
    "sra","mlls","dep","pes","cbc","fsv","emp",
}



# ─────────────────────────────────────────────
# ENGLISH TOKEN FILTER
# ─────────────────────────────────────────────
ENGLISH = {
    "the","and","for","are","but","not","you","all","can","her","was","one",
    "our","out","had","him","his","how","man","new","now","old","see","two",
    "who","did","its","let","put","say","she","too","use","from","have",
    "that","this","they","will","with","been","than","then","when","some",
    "what","know","come","said","each","time","your","their","there","would",
    "other","about","which","could","these","those","more","also","into",
    "over","just","even","made","after","before","under","first","where",
    "while","should","through","between","because","without","within",
    "against","however","whether","another","during","monday","tuesday",
    "wednesday","thursday","friday","saturday","sunday","subscribe",
    "newsletter","read","here","click","follow","share","like","views",
    "loading","section","browser","menu","search","back","next","national",
    "international","news","people","year","years","state","city","country",
    "president","government","police","security","january","february",
    "march","april","june","july","august","september","october","november",
    "december","watch","join","get","make","take","give","find","think",
    "look","want","need","help","work","way","good","great","well","much",
    "many","show","tell","play","move","live","feel","try","ask","seem",
    "lead","keep","walk","draw","believe","hold","bring","happen","carry",
    "talk","appear","produce","sit","stand","lose","pay","meet","include",
    "continue","set","learn","change","turn","close","start","stop","end",
    "open","send","receive","run","build","create","write","call","day",
    "week","month","days","weeks","months","hour","hours","went","still",
    "own","right","left","few","most","least","less","high","low","large",
    "small","big","little","full","free","real","true","false","early",
    "late","near","far","hard","easy","fast","slow","report","reports",
    "according","press","release","official","statement","including",
    "despite","although","therefore","moreover","wrote","told","added",
    "noted","reported","whose","whom","may","might","must","shall","does",
    "were","said","have","has","had","will","can","could","would","should",
    # Finance / Bitcoin
    "bank","banks","banking","million","billion","trillion","bonds","bond",
    "debt","loan","loans","fund","funds","money","tax","taxes","budget",
    "economy","economic","finance","financial","invest","investment","market",
    "bitcoin","crypto","wallet","token","coin","exchange","dollar","dollars",
    # Common English words missed in first pass
    "only","them","being","every","public","future","society","speech",
    "god","countries","world","today","never","always","again","really",
    "gone","came","won","done","thought","together","nation","peace",
    "hope","freedom","justice","love","power","force","law","laws",
    "proud","pride","game","history","promise","vote","leader","leadership",
    "strong","strength","success","plan","plans","rights","court","courts",
    "news","media","video","live","watch","show","shows","post","posts",
    "tweet","tweets","account","accounts","user","users","profile","link",
    "join","sign","email","address","message","messages","reply","replies",
    "dear","thanks","thank","sorry","please","welcome","hello",
    "yes","yeah","nope","okay","wow","amazing","awesome","incredible",
    "wonderful","beautiful","perfect","important","serious","critical",
    "official","private","global","local","political","military","army",
    "president","minister","congress","senate","party","election","votes",
    "voter","voters","democratic","constitution","legal","illegal","crime",
    "crimes","criminal","criminals","prison","jail","arrest","arrested",
    "detained","detention","trial","human","truth","fact","facts","evidence",
    "proof","statistics","numbers","percent","number","children","women",
    "family","families","person","citizen","citizens","community","communities",
    "globe","earth","land","city","cities","state","states","region","regions",
    "area","areas","place","places",
    # Sports/culture English
    "longboard","longboards","freestyle","gang","gangs","united","heat",
    "surf","surfing","skate","skateboard","skating","bmx","crossfit",
    "startup","startups","app","apps","software","hardware",
    "platform","platforms","cloud","server","servers",
    # elfaro.net English articles (press freedom, spyware coverage)
    "support","journalists","journalist","salvadoran","salvadorans","american",
    "americans","group","groups","spyware","apple","crook","round","protected",
    "freedom","press","expression","civil","organizations","org",
    "nso","pegasus","surveillance","hacking","hack","hacked",
    "targets","targeted","targeting","expose","exposed","exposing",
    "investigation","investigations","investigate","investigated","investigative",
    "report","reporting","reporter","reporters","coverage","cover","covered",
    "threat","threats","threatened","threatening","opposition","dissident",
    "dissidents","exile","exiled","abroad","overseas","foreign","foreigner",
    # Remaining stragglers
    "english","interview","interviews","approval","subtitles","going","safest",
    "safe","getting","something","anything","everything","nothing",
    "someone","anyone","everyone","nobody","everybody","somewhere","anywhere",
    "everywhere","somehow","anyway","already","almost","actually",
    "basically","literally","honestly","clearly","exactly","absolutely",
    "definitely","certainly","probably","possibly","obviously","simply",
    "totally","entirely","completely","seriously","especially","generally",
    "finally","recently","currently","previously","suddenly","immediately",
    "quickly","slowly","carefully","easily","perhaps","maybe","sometimes",
    "often","usually","soon","later","unless","nevertheless","meanwhile",
    "afterward","otherwise","instead",
}

# ─────────────────────────────────────────────
# MULTI-WORD EXPRESSION COLLOCATIONS
# (joined with _ before tokenizing so compound names stay together)
# ─────────────────────────────────────────────
COLLOCATION_SUBS = [
    # Geography
    (re.compile(r'san\s+salvador'),                        'san_salvador'),
    (re.compile(r'santa\s+ana'),                           'santa_ana'),
    (re.compile(r'san\s+miguel'),                          'san_miguel'),
    (re.compile(r'santa\s+tecla'),                         'santa_tecla'),
    (re.compile(r'san\s+marcos'),                          'san_marcos'),
    (re.compile(r'san\s+pedro'),                           'san_pedro'),
    (re.compile(r'santa\s+rosa'),                          'santa_rosa'),
    (re.compile(r'san\s+vicente'),                         'san_vicente'),
    (re.compile(r'la\s+libertad'),                         'la_libertad'),
    (re.compile(r'la\s+unión|la\s+union'),          'la_union'),
    (re.compile(r'la\s+paz'),                              'la_paz'),
    # Political entities
    (re.compile(r'nuevas\s+ideas'),                        'nuevas_ideas'),
    (re.compile(r'nayib\s+bukele'),                        'nayib_bukele'),
    # Estado de Excepción in various forms
    (re.compile(r'estado\s+de\s+excepción'),        'estado_excepcion'),
    (re.compile(r'estado\s+de\s+excepcion'),              'estado_excepcion'),
    (re.compile(r'régimen\s+de\s+excepción'), 'regimen_excepcion'),
    (re.compile(r'regimen\s+de\s+excepcion'),             'regimen_excepcion'),
    (re.compile(r'estado\s+excepción'),               'estado_excepcion'),
    (re.compile(r'estado\s+excepcion'),                    'estado_excepcion'),
    # Institutions & key phrases
    (re.compile(r'derechos\s+humanos'),                    'derechos_humanos'),
    (re.compile(r'asamblea\s+legislativa'),                'asamblea_legislativa'),
    (re.compile(r'corte\s+suprema'),                       'corte_suprema'),
    (re.compile(r'sala\s+constitucional'),                 'sala_constitucional'),
    (re.compile(r'fiscalía\s+general|fiscalia\s+general'), 'fiscalia_general'),
    (re.compile(r'naciones\s+unidas'),                     'naciones_unidas'),
    (re.compile(r'estados\s+unidos'),                      'estados_unidos'),
    (re.compile(r'bitcoin\s+city'),                        'bitcoin_city'),
    (re.compile(r'centros\s+penales'),                     'centros_penales'),
    (re.compile(r'centro\s+penal'),                        'centro_penal'),
    (re.compile(r'fuerza\s+armada'),                       'fuerza_armada'),
    (re.compile(r'seguridad\s+pública|seguridad\s+publica'), 'seguridad_publica'),
    (re.compile(r'libertad\s+de\s+expresión|libertad\s+de\s+expresion'), 'libertad_expresion'),
]


def join_collocations(text):
    """Join known multi-word political expressions into underscore-linked tokens."""
    t = text.lower()
    for pat, repl in COLLOCATION_SUBS:
        t = pat.sub(repl, t)
    return t


def is_mostly_english(text, threshold=0.40):
    """Return True if >threshold fraction of alpha tokens are common English words."""
    tokens = re.findall(r'[a-z]{3,}', text.lower())
    if len(tokens) < 15:
        return False
    return sum(1 for t in tokens if t in ENGLISH) / len(tokens) > threshold

def tokenize(text):
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"@\w+", " ", text)
    text = re.sub(r"#\w+", " ", text)
    text = join_collocations(text)
    # Match underscore-joined collocations OR plain Spanish words (3+ chars)
    tokens = re.findall(
        r"[a-z\u00e0-\u00ff][a-z\u00e0-\u00ff]*(?:_[a-z\u00e0-\u00ff][a-z\u00e0-\u00ff]*)+"
        r"|[a-z\u00e0-\u00ff]{3,}",
        text.lower()
    )
    return [t for t in tokens if t not in STOP and t not in ENGLISH]


def log_odds(c_a, total_a, c_b, total_b):
    p_a = (c_a + 0.5) / (total_a + 0.5)
    p_b = (c_b + 0.5) / (total_b + 0.5)
    p_a = min(max(p_a, 1e-9), 1 - 1e-9)
    p_b = min(max(p_b, 1e-9), 1 - 1e-9)
    return math.log(p_a / (1 - p_a)) - math.log(p_b / (1 - p_b))


# ─────────────────────────────────────────────
# LOAD DATA
# ─────────────────────────────────────────────
def clean_text(text):
    """Strip HTML tags and CSS artifacts; fix drop-cap scraping artifacts."""
    text = text.replace('\xa0', ' ').replace('​', '')
    text = re.sub(r'<[^>]{0,300}>', ' ', text)
    # Fix drop-cap artifact: "L uego" → "Luego", "M iembros" → "Miembros"
    text = re.sub(r'(?<!\w)([A-ZÁÉÍÓÚÑÜ])\s+([a-záéíóúñ]{2,})', r'\1\2', text)
    text = re.sub(r'\balign(?:center|left|right|none)?\b', ' ', text)
    text = re.sub(r'\bwp-[a-z0-9_-]+', ' ', text)
    return text


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
            text = clean_text(r.get("text", ""))
            # Skip mostly-English tweets (short tweet check uses lower threshold)
            raw_alpha = re.findall(r'[a-z]{3,}', text.lower())
            if len(raw_alpha) >= 4:
                eng_frac = sum(1 for t in raw_alpha if t in ENGLISH) / len(raw_alpha)
                if eng_frac > 0.40:
                    continue
            rows.append((d, tokenize(text)))
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
            text = clean_text(r.get("title", "") + " " + r.get("text", "")[:800])
            if is_mostly_english(text):
                continue
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
        t_freq = {w.replace("_", " "): c for w, c in t_count.items() if c >= MIN_FREQ}
        a_freq = {w.replace("_", " "): c for w, c in a_count.items() if c >= MIN_FREQ}

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
