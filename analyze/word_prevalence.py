"""
word_prevalence.py — Word frequency and distinctiveness across all datasets

OUTPUTS (output/word_prevalence/):
  viz_tweets_distinctive.html    — log-odds most distinctive words per account (5-panel)
  viz_tweets_heatmap.html        — word × year frequency heatmap, account dropdown
  viz_press_heatmap.html         — word × year heatmap for Presidencia press releases
  viz_media_distinctive.html     — log-odds distinctive words per media outlet
"""

import csv
import sys
csv.field_size_limit(sys.maxsize)
import math
import os
import re
from collections import Counter, defaultdict

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

REPO_ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TWEETS_CSV = os.path.join(REPO_ROOT, "output", "data", "tweets.csv")
PRESS_CSV  = os.path.join(REPO_ROOT, "output", "el_salvador_political_dataset.csv")
MEDIA_CSV  = os.path.join(REPO_ROOT, "output", "articles_master.csv")
OUTPUT_DIR = os.path.join(REPO_ROOT, "output", "word_prevalence")

# ─────────────────────────────────────────────
# STOP WORDS  (Spanish + Twitter artifacts)
# ─────────────────────────────────────────────
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
    "hemos","vamos","nuestro","ser","sido","por","les","les",
    "deja","dicho","dar","dar","les","han","fue","fué",
    "https","http","co","rt","pic","twitter","amp","hace","meses","horas",
    # extra common filler
    "aquí","ahí","allí","allá","acá","qué","cómo","cuándo","quién","cuál",
    "eso","esa","esos","algo","nada","nadie","cada","otro","otros","otra",
    "otras","ellos","ellas","ella","él","usted","ustedes","nos","vos",
    # ── El Salvador / demonyms ────────────────────────────────────────────
    "salvador","salvadoreño","salvadoreña","salvadoreños","salvadoreñas",
    "elsalvador",
    # ── Media outlet names / branding ─────────────────────────────────────
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
    # ── Drop-cap residue (single capital letters left after joining attempt) ──
    "ste","nte","uego","uatro","iembros","iputados","olona","urante","oen","ctón",
    # ── Encoding garble artifacts ─────────────────────────────────────────────
    "repã","blica","redacciã","oacute","aacute","eacute","iacute","uacute",
    "yeerles","intimissimun","administraador",
    # ── Navigation / section labels ───────────────────────────────────────────
    "columna","columnas","portada","articulos","tags","tag","psd","lnf",
    # ── Common abbreviations that become noise tokens ─────────────────────────
    "sra","mlls","dep","pes","cbc","fsv","emp",
}

ACCOUNT_COLORS = {
    "nayibbukele":  "#e63946",
    "PresidenciaSV":"#457b9d",
    "Gobierno_SV":  "#2a9d8f",
    "AsambleaSV":   "#e76f51",
    "FGR_SV":       "#6a4c93",
}

MEDIA_COLORS = {
    "lapagina.com.sv":     "#e63946",
    "diario.elmundo.sv":   "#457b9d",
    "diariocolatino.com":  "#2a9d8f",
    "elfaro.net":          "#e76f51",
    "presidencia.gob.sv":  "#6a4c93",
}

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

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
    # Finance / Bitcoin (Bukele tweets extensively in English on these)
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
    "born","born","long","wrong","ago","ago","away","away","back","once",
    "news","media","video","live","watch","show","shows","post","posts",
    "tweet","tweets","account","accounts","user","users","profile","link",
    "join","sign","email","address","message","messages","reply","replies",
    "dear","dear","thanks","thank","sorry","please","welcome","hello",
    "yes","yeah","yep","nope","okay","ok","wow","omg","lol","great",
    "amazing","awesome","incredible","wonderful","beautiful","perfect",
    "important","serious","critical","major","significant","special",
    "official","public","private","global","local","national","international",
    "political","economic","social","military","security","police","army",
    "president","minister","government","congress","senate","party","election",
    "vote","votes","voter","voters","democracy","democratic","constitution",
    "law","laws","legal","illegal","crime","crimes","criminal","criminals",
    "prison","jail","arrest","arrested","detained","detention","trial",
    "human","rights","freedom","liberty","justice","truth","fact","facts",
    "evidence","proof","data","statistics","numbers","percent","number",
    "children","women","men","family","families","people","person","citizen",
    "citizens","community","communities","country","countries","nation",
    "nations","world","globe","global","earth","land","city","cities",
    "state","states","region","regions","area","areas","place","places",
    # Sports/culture English (lapagina uses English sports terminology)
    "longboard","longboards","freestyle","gang","gangs","united","heat",
    "surf","surfing","skate","skateboard","skating","bmx","crossfit",
    "startup","startups","app","apps","online","software","hardware",
    "platform","platforms","digital","cloud","server","servers",
    # elfaro.net English articles (press freedom, spyware coverage)
    "support","journalists","journalist","salvadoran","salvadorans","american",
    "americans","group","groups","spyware","apple","crook","round","protected",
    "freedom","press","expression","civil","society","organizations","org",
    "nso","pegasus","surveillance","hacking","hack","hacked","hack",
    "targets","targeted","targeting","expose","exposed","exposing",
    "investigation","investigations","investigate","investigated","investigative",
    "report","reporting","reporter","reporters","coverage","cover","covered",
    "threat","threats","threatened","threatening","opposition","dissident",
    "dissidents","exile","exiled","abroad","overseas","foreign","foreigner",
    # Gobierno_SV / misc English stragglers
    "round",
    # Remaining stragglers found in Bukele distinctive words
    "english","interview","interviews","approval","subtitles","going","safest",
    "safe","hooah","getting","something","anything","everything","nothing",
    "someone","anyone","everyone","nobody","everybody","somebody","anywhere",
    "everywhere","nowhere","somehow","anyway","already","almost","actually",
    "basically","literally","honestly","clearly","exactly","absolutely",
    "definitely","certainly","probably","possibly","obviously","simply",
    "totally","entirely","completely","seriously","especially","generally",
    "finally","recently","currently","previously","originally","suddenly",
    "immediately","quickly","slowly","carefully","easily","perhaps",
    "maybe","sometimes","often","usually","soon","later","unless",
    "nevertheless","meanwhile","afterward","otherwise","instead",
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

def clean_text(text):
    """Strip HTML tags and CSS artifacts; fix drop-cap scraping artifacts."""
    # Normalize non-breaking spaces and other unicode whitespace
    text = text.replace('\xa0', ' ').replace('​', '')
    # Strip HTML tags
    text = re.sub(r'<[^>]{0,300}>', ' ', text)
    # Fix drop-cap artifact: "L uego" → "Luego", "M iembros" → "Miembros"
    # (lapagina and similar sites use CSS first-letter, which scrapes as single capital + space + fragment)
    text = re.sub(r'(?<!\w)([A-ZÁÉÍÓÚÑÜ])\s+([a-záéíóúñ]{2,})', r'\1\2', text)
    # CSS class artifacts
    text = re.sub(r'\balign(?:center|left|right|none)?\b', ' ', text)
    text = re.sub(r'\bwp-[a-z0-9_-]+', ' ', text)
    return text


def tokenize(text):
    text = re.sub(r'https?://\S+', ' ', text)
    text = re.sub(r'@\w+', ' ', text)
    text = re.sub(r'#\w+', ' ', text)
    text = join_collocations(text)
    # Match underscore-joined collocations OR plain Spanish words (3+ chars)
    tokens = re.findall(
        r'[a-z\u00e0-\u00ff][a-z\u00e0-\u00ff]*(?:_[a-z\u00e0-\u00ff][a-z\u00e0-\u00ff]*)+'
        r'|[a-z\u00e0-\u00ff]{3,}',
        text.lower()
    )
    return [t for t in tokens if t not in STOP and t not in ENGLISH]


def log_odds_scores(count_in, total_in, count_out, total_out, min_freq=5):
    """
    For each word, compute log-odds ratio (group A vs rest).
    Returns dict {word: score}, filtered to words with min_freq in group A.
    """
    scores = {}
    all_words = set(count_in) | set(count_out)
    for w in all_words:
        c_in  = count_in.get(w, 0)
        c_out = count_out.get(w, 0)
        if c_in < min_freq:
            continue
        p_in  = (c_in  + 0.5) / (total_in  + 0.5)
        p_out = (c_out + 0.5) / (total_out + 0.5)
        p_in  = min(max(p_in,  1e-9), 1 - 1e-9)
        p_out = min(max(p_out, 1e-9), 1 - 1e-9)
        scores[w] = math.log(p_in / (1 - p_in)) - math.log(p_out / (1 - p_out))
    return scores


def top_n(scores, n=20):
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)[:n]


# ─────────────────────────────────────────────
# DATA LOADERS
# ─────────────────────────────────────────────
def load_tweets():
    """Returns {account: {"words": Counter, "by_year": {year: Counter},
                           "total_words": int}}"""
    print("[tweets] loading ...")
    data = {}
    skipped = 0
    with open(TWEETS_CSV, encoding="utf-8-sig", errors="replace") as f:
        for r in csv.DictReader(f):
            handle = r.get("handle", "").strip()
            if not handle:
                continue
            year = r.get("year", "").strip()
            text = clean_text(r.get("text", ""))
            # Skip tweets that are mostly English (lower threshold for short tweets)
            raw_alpha = re.findall(r'[a-z]{3,}', text.lower())
            if len(raw_alpha) >= 4:
                eng_frac = sum(1 for t in raw_alpha if t in ENGLISH) / len(raw_alpha)
                if eng_frac > 0.40:
                    skipped += 1
                    continue
            tokens = tokenize(text)
            if handle not in data:
                data[handle] = {"words": Counter(), "by_year": defaultdict(Counter),
                                "total_words": 0, "doc_by_year": defaultdict(set)}
            data[handle]["words"].update(tokens)
            data[handle]["total_words"] += len(tokens)
            # track which tweets (by index) contain each word, per year
            data[handle]["by_year"][year].update(tokens)
    print(f"[tweets] {sum(v['total_words'] for v in data.values()):,} total tokens across "
          f"{len(data)} accounts ({skipped:,} English tweets skipped)")
    return data


def load_press():
    """Returns {year: Counter} of word counts from press release text+title."""
    print("[press] loading ...")
    by_year = defaultdict(Counter)
    total = 0
    with open(PRESS_CSV, encoding="utf-8-sig", errors="replace") as f:
        for r in csv.DictReader(f):
            year = r.get("year", "").strip()
            text = clean_text(r.get("title", "") + " " + r.get("text", ""))
            tokens = tokenize(text)
            by_year[year].update(tokens)
            total += len(tokens)
    print(f"[press] {total:,} tokens, years: {sorted(by_year.keys())}")
    return by_year


def load_media():
    """Returns {domain: Counter} — title + first 600 chars of text per article."""
    print("[media] loading ...")
    KEEP_DOMAINS = set(MEDIA_COLORS.keys())
    data = defaultdict(Counter)
    totals = defaultdict(int)
    with open(MEDIA_CSV, encoding="utf-8-sig", errors="replace") as f:
        for r in csv.DictReader(f):
            domain = r.get("domain", "").strip()
            if domain not in KEEP_DOMAINS:
                continue
            text = clean_text(r.get("title", "") + " " + r.get("text", "")[:600])
            if is_mostly_english(text):
                continue
            tokens = tokenize(text)
            data[domain].update(tokens)
            totals[domain] += len(tokens)
    for d in KEEP_DOMAINS:
        print(f"  {d}: {totals[d]:,} tokens")
    return data


# ─────────────────────────────────────────────
# VIZ 1: Tweets — log-odds per account
# ─────────────────────────────────────────────
def viz_tweets_distinctive(tweet_data):
    print("[viz] tweets distinctive words ...")
    accounts = list(tweet_data.keys())
    n = len(accounts)
    cols = 2
    rows = math.ceil(n / cols)

    fig = make_subplots(
        rows=rows, cols=cols,
        subplot_titles=accounts,
        horizontal_spacing=0.18,
        vertical_spacing=0.12,
    )

    for idx, account in enumerate(accounts):
        row = idx // cols + 1
        col = idx % cols + 1
        color = ACCOUNT_COLORS.get(account, "#888")

        count_in  = tweet_data[account]["words"]
        total_in  = tweet_data[account]["total_words"]
        count_out = Counter()
        total_out = 0
        for other, v in tweet_data.items():
            if other != account:
                count_out.update(v["words"])
                total_out += v["total_words"]

        scores = log_odds_scores(count_in, total_in, count_out, total_out, min_freq=8)
        top    = top_n(scores, 20)
        words  = [w.replace('_', ' ') for w, _ in top][::-1]
        vals   = [s for _, s in top][::-1]

        fig.add_trace(go.Bar(
            x=vals, y=words,
            orientation="h",
            marker_color=color,
            showlegend=False,
            hovertemplate="<b>%{y}</b><br>log-odds: %{x:.2f}<extra></extra>",
        ), row=row, col=col)

    fig.update_layout(
        title="Most distinctive words per account (log-odds vs all other accounts)",
        height=220 * rows,
        margin=dict(l=160, r=40, t=80, b=40),
        plot_bgcolor="#fafafa",
        paper_bgcolor="white",
    )
    for axis in fig.layout:
        if axis.startswith("xaxis"):
            fig.layout[axis].update(showgrid=True, gridcolor="#eee", zeroline=True,
                                    zerolinecolor="#ccc")
        if axis.startswith("yaxis"):
            fig.layout[axis].update(tickfont_size=11)

    path = os.path.join(OUTPUT_DIR, "viz_tweets_distinctive.html")
    fig.write_html(path)
    print(f"  -> {path}")


# ─────────────────────────────────────────────
# VIZ 2: Tweets — word × year heatmap (dropdown per account)
# ─────────────────────────────────────────────
def viz_tweets_heatmap(tweet_data):
    print("[viz] tweets word×year heatmap ...")
    accounts = list(tweet_data.keys())
    years_all = sorted({
        yr for v in tweet_data.values() for yr in v["by_year"]
        if yr.isdigit() and 2015 <= int(yr) <= 2025
    })

    TOP_WORDS = 40

    fig = go.Figure()
    button_list = []

    for idx, account in enumerate(accounts):
        by_year = tweet_data[account]["by_year"]

        # pick top words overall for this account
        overall = tweet_data[account]["words"]
        top_words = [w for w, _ in overall.most_common(TOP_WORDS * 3)
                     if len(w) >= 4][:TOP_WORDS]

        # build matrix: rows=words, cols=years — value = % of tokens that year
        z = []
        for w in top_words:
            row = []
            for yr in years_all:
                c = by_year.get(yr, Counter())
                total = sum(c.values())
                row.append(round(c.get(w, 0) / total * 100, 3) if total else 0)
            z.append(row)

        fig.add_trace(go.Heatmap(
            z=z,
            x=years_all,
            y=top_words,
            colorscale="Blues",
            visible=(idx == 0),
            name=account,
            colorbar=dict(title="% tokens"),
            hovertemplate="Word: <b>%{y}</b><br>Year: %{x}<br>%{z:.2f}% of tokens<extra></extra>",
            zmin=0,
        ))

    # dropdown buttons
    for idx, account in enumerate(accounts):
        visible = [i == idx for i in range(len(accounts))]
        button_list.append(dict(
            method="update",
            label=account,
            args=[{"visible": visible},
                  {"title": f"Word frequency by year — @{account}"}],
        ))

    fig.update_layout(
        title=f"Word frequency by year — @{accounts[0]}",
        height=700,
        margin=dict(l=160, r=40, t=80, b=60),
        xaxis=dict(tickmode="array", tickvals=years_all, dtick=1),
        yaxis=dict(tickfont_size=11, autorange="reversed"),
        updatemenus=[dict(
            buttons=button_list,
            direction="down",
            showactive=True,
            x=0.01, xanchor="left",
            y=1.12, yanchor="top",
            bgcolor="white",
            bordercolor="#ccc",
        )],
    )

    path = os.path.join(OUTPUT_DIR, "viz_tweets_heatmap.html")
    fig.write_html(path)
    print(f"  -> {path}")


# ─────────────────────────────────────────────
# VIZ 3: Press releases — word × year heatmap
# ─────────────────────────────────────────────
def viz_press_heatmap(press_data):
    print("[viz] press releases word×year heatmap ...")
    years = sorted(y for y in press_data if y.isdigit() and int(y) >= 2019)
    TOP_WORDS = 50

    # Top words overall across all years
    overall = Counter()
    for yr in years:
        overall.update(press_data[yr])
    top_words = [w for w, _ in overall.most_common(TOP_WORDS * 3)
                 if len(w) >= 4][:TOP_WORDS]

    z = []
    for w in top_words:
        row = []
        for yr in years:
            c = press_data.get(yr, Counter())
            total = sum(c.values())
            row.append(round(c.get(w, 0) / total * 100, 3) if total else 0)
        z.append(row)

    fig = go.Figure(go.Heatmap(
        z=z,
        x=years,
        y=top_words,
        colorscale="Greens",
        colorbar=dict(title="% tokens"),
        hovertemplate="Word: <b>%{y}</b><br>Year: %{x}<br>%{z:.2f}% of tokens<extra></extra>",
        zmin=0,
    ))
    fig.update_layout(
        title="Word frequency by year — Presidencia press releases",
        height=900,
        margin=dict(l=160, r=40, t=80, b=60),
        xaxis=dict(tickmode="array", tickvals=years),
        yaxis=dict(tickfont_size=11, autorange="reversed"),
        paper_bgcolor="white",
        plot_bgcolor="#fafafa",
    )

    path = os.path.join(OUTPUT_DIR, "viz_press_heatmap.html")
    fig.write_html(path)
    print(f"  -> {path}")


# ─────────────────────────────────────────────
# VIZ 4: Media — log-odds per outlet
# ─────────────────────────────────────────────
def viz_media_distinctive(media_data):
    print("[viz] media distinctive words ...")
    domains = [d for d in MEDIA_COLORS if d in media_data]
    if len(domains) < 2:
        print("  [skip] not enough domains with data")
        return

    n    = len(domains)
    cols = 2
    rows = math.ceil(n / cols)

    fig = make_subplots(
        rows=rows, cols=cols,
        subplot_titles=domains,
        horizontal_spacing=0.18,
        vertical_spacing=0.14,
    )

    for idx, domain in enumerate(domains):
        row = idx // cols + 1
        col = idx % cols + 1
        color = MEDIA_COLORS.get(domain, "#888")

        count_in  = media_data[domain]
        total_in  = sum(count_in.values())
        count_out = Counter()
        total_out = 0
        for other, c in media_data.items():
            if other != domain:
                count_out.update(c)
                total_out += sum(c.values())

        scores = log_odds_scores(count_in, total_in, count_out, total_out, min_freq=3)
        top    = top_n(scores, 20)
        words  = [w.replace('_', ' ') for w, _ in top][::-1]
        vals   = [s for _, s in top][::-1]

        fig.add_trace(go.Bar(
            x=vals, y=words,
            orientation="h",
            marker_color=color,
            showlegend=False,
            hovertemplate="<b>%{y}</b><br>log-odds: %{x:.2f}<extra></extra>",
        ), row=row, col=col)

    fig.update_layout(
        title="Most distinctive words per media outlet (log-odds vs all other outlets)",
        height=220 * rows,
        margin=dict(l=200, r=40, t=80, b=40),
        plot_bgcolor="#fafafa",
        paper_bgcolor="white",
    )
    for axis in fig.layout:
        if axis.startswith("xaxis"):
            fig.layout[axis].update(showgrid=True, gridcolor="#eee", zeroline=True,
                                    zerolinecolor="#ccc")
        if axis.startswith("yaxis"):
            fig.layout[axis].update(tickfont_size=11)

    path = os.path.join(OUTPUT_DIR, "viz_media_distinctive.html")
    fig.write_html(path)
    print(f"  -> {path}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print("=" * 60)
    print("Word Prevalence Analysis")
    print("=" * 60)

    tweet_data = load_tweets()
    viz_tweets_distinctive(tweet_data)
    viz_tweets_heatmap(tweet_data)
    del tweet_data  # free memory before loading next dataset

    press_data = load_press()
    viz_press_heatmap(press_data)

    media_data = load_media()
    viz_media_distinctive(media_data)

    print("\nDone. Outputs in", OUTPUT_DIR)


if __name__ == "__main__":
    main()
