"""
ngram_comparison.py — Top bigrams per tweet account and media outlet

OUTPUTS (output/ngram_comparison/):
  viz_tweet_bigrams.html   — top 20 bigrams per Twitter account (5 panels)
  viz_media_bigrams.html   — top 20 bigrams per media outlet (4 panels)
  viz_distinctive_bigrams.html — log-odds most distinctive bigrams per source

USAGE:
  python3 analyze/ngram_comparison.py
"""

import csv
import sys
csv.field_size_limit(sys.maxsize)
import math
import os
import re
from collections import Counter, defaultdict

import plotly.graph_objects as go
from plotly.subplots import make_subplots

REPO_ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TWEETS_CSV = os.path.join(REPO_ROOT, "output", "data", "tweets.csv")
MEDIA_CSV  = os.path.join(REPO_ROOT, "output", "articles_master.csv")
OUTPUT_DIR = os.path.join(REPO_ROOT, "output", "ngram_comparison")

# ─────────────────────────────────────────────
# STOP WORDS  (same as event_framing.py)
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
    "hemos","vamos","han","fué","deja","dicho","algo","nada","nadie",
    "otro","otros","otra","otras","ellos","ellas","ella","él","usted",
    "ustedes","nos","vos","eso","algo","ahí","allí","aquí","acá",
    "https","http","co","rt","pic","twitter","amp","via","hace","meses","horas",
    # ── El Salvador / demonyms ────────────────────────────────────────────
    "salvador","salvadoreño","salvadoreña","salvadoreños","salvadoreñas",
    "elsalvador",
    # ── Media outlet names / branding ─────────────────────────────────────
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

# Bigrams that are pure broadcast / platform boilerplate in tweets
TWEET_BOILERPLATE_BIGRAMS = {
    "siguiente enlace", "facebook youtube", "nuestras plataformas",
    "plataformas digitales", "redes sociales", "ver transmisión",
    "transmisión vivo", "vivo siguiente", "sesión plenaria",
    "plenaria siguiente",
}

ACCOUNT_ORDER = ["nayibbukele", "PresidenciaSV", "Gobierno_SV", "AsambleaSV", "FGR_SV"]
ACCOUNT_COLORS = {
    "nayibbukele":   "#e63946",
    "PresidenciaSV": "#457b9d",
    "Gobierno_SV":   "#2a9d8f",
    "AsambleaSV":    "#e76f51",
    "FGR_SV":        "#6a4c93",
}

MEDIA_ORDER = ["lapagina.com.sv", "diariocolatino.com", "elfaro.net", "diario1.com"]
MEDIA_COLORS = {
    "lapagina.com.sv":    "#e63946",
    "diariocolatino.com": "#2a9d8f",
    "elfaro.net":         "#e76f51",
    "diario1.com":        "#457b9d",
}
MEDIA_LABELS = {
    "lapagina.com.sv":    "La Página",
    "diariocolatino.com": "Diario Co Latino",
    "elfaro.net":         "El Faro",
    "diario1.com":        "Diario 1",
}


# ─────────────────────────────────────────────
# TOKENIZE + BIGRAMS
# ─────────────────────────────────────────────
def tokenize(text: str) -> "list":
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"@\w+", " ", text)
    text = re.sub(r"#\w+", " ", text)
    tokens = re.findall(r"\b[a-záéíóúüñ]{3,}\b", text.lower())
    return [t for t in tokens if t not in STOP]


def bigrams(tokens: "list") -> "list":
    return [f"{tokens[i]} {tokens[i+1]}" for i in range(len(tokens) - 1)]


# ─────────────────────────────────────────────
# LOAD DATA
# ─────────────────────────────────────────────
def load_tweet_bigrams() -> "dict":
    """Returns {handle: Counter of bigrams}."""
    print("[load] tweets ...")
    counts: "dict" = defaultdict(Counter)
    with open(TWEETS_CSV, encoding="utf-8-sig", errors="replace") as f:
        for r in csv.DictReader(f):
            handle = r.get("handle", "").strip()
            if handle not in ACCOUNT_ORDER:
                continue
            toks = tokenize(r.get("text", ""))
            bg = bigrams(toks)
            for b in bg:
                if b not in TWEET_BOILERPLATE_BIGRAMS:
                    counts[handle][b] += 1
    for h, c in counts.items():
        print(f"  {h}: {sum(c.values()):,} bigram tokens, {len(c):,} unique")
    return counts


def load_media_bigrams() -> "dict":
    """Returns {domain: Counter of bigrams}, with lapagina deduplicated by title."""
    print("[load] media articles ...")
    counts: "dict" = defaultdict(Counter)
    seen_titles: "dict" = defaultdict(set)  # domain -> set of seen titles

    with open(MEDIA_CSV, encoding="utf-8-sig", errors="replace") as f:
        for r in csv.DictReader(f):
            domain = r.get("domain", "").strip()
            if domain not in MEDIA_ORDER:
                continue
            title = r.get("title", "").strip().lower()
            # Deduplicate: skip if we've seen this title for this domain
            if title and title in seen_titles[domain]:
                continue
            seen_titles[domain].add(title)

            text = r.get("title", "") + " " + r.get("text", "")[:1200]
            toks = tokenize(text)
            bg = bigrams(toks)
            for b in bg:
                counts[domain][b] += 1

    for d, c in counts.items():
        print(f"  {d}: {sum(c.values()):,} bigram tokens, {len(c):,} unique")
    return counts


# ─────────────────────────────────────────────
# LOG-ODDS
# ─────────────────────────────────────────────
def log_odds(c_a: int, total_a: int, c_b: int, total_b: int) -> float:
    p_a = (c_a + 0.5) / (total_a + 0.5)
    p_b = (c_b + 0.5) / (total_b + 0.5)
    p_a = min(max(p_a, 1e-9), 1 - 1e-9)
    p_b = min(max(p_b, 1e-9), 1 - 1e-9)
    return math.log(p_a / (1 - p_a)) - math.log(p_b / (1 - p_b))


def distinctive_bigrams(target_counter: Counter, all_counter: Counter,
                         top_n: int = 20, min_count: int = 10) -> "list":
    """Return top_n bigrams most distinctive for target vs all (combined)."""
    total_target = sum(target_counter.values())
    total_all    = sum(all_counter.values())

    scores = []
    for bg, c_t in target_counter.items():
        if c_t < min_count:
            continue
        c_a = all_counter[bg]
        score = log_odds(c_t, total_target, c_a - c_t, total_all - total_target)
        scores.append((bg, score))
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[:top_n]


# ─────────────────────────────────────────────
# VIZ: Top bigrams per account
# ─────────────────────────────────────────────
def viz_tweet_bigrams(tweet_counts: "dict"):
    print("[viz] tweet bigrams ...")
    accounts = [a for a in ACCOUNT_ORDER if a in tweet_counts]
    n = len(accounts)
    fig = make_subplots(
        rows=n, cols=1,
        subplot_titles=accounts,
        vertical_spacing=0.06,
    )

    for i, acct in enumerate(accounts, start=1):
        top = tweet_counts[acct].most_common(20)
        if not top:
            continue
        labels = [b for b, _ in reversed(top)]
        values = [c for _, c in reversed(top)]
        color  = ACCOUNT_COLORS.get(acct, "#888")

        fig.add_trace(
            go.Bar(x=values, y=labels, orientation="h",
                   marker_color=color, showlegend=False,
                   hovertemplate="%{y}: %{x:,}<extra></extra>"),
            row=i, col=1,
        )
        fig.update_xaxes(title_text="count", row=i, col=1)

    fig.update_layout(
        title="Top 20 Bigrams per Twitter Account",
        height=340 * n,
        font=dict(size=12),
        plot_bgcolor="white",
        paper_bgcolor="#f9f9f9",
        margin=dict(l=200, r=40, t=60, b=40),
    )

    path = os.path.join(OUTPUT_DIR, "viz_tweet_bigrams.html")
    fig.write_html(path, include_plotlyjs="cdn")
    print(f"  -> {path}")


# ─────────────────────────────────────────────
# VIZ: Top bigrams per media outlet
# ─────────────────────────────────────────────
def viz_media_bigrams(media_counts: "dict"):
    print("[viz] media bigrams ...")
    outlets = [o for o in MEDIA_ORDER if o in media_counts]
    n = len(outlets)
    fig = make_subplots(
        rows=n, cols=1,
        subplot_titles=[MEDIA_LABELS.get(o, o) for o in outlets],
        vertical_spacing=0.06,
    )

    for i, outlet in enumerate(outlets, start=1):
        top = media_counts[outlet].most_common(20)
        if not top:
            continue
        labels = [b for b, _ in reversed(top)]
        values = [c for _, c in reversed(top)]
        color  = MEDIA_COLORS.get(outlet, "#888")

        fig.add_trace(
            go.Bar(x=values, y=labels, orientation="h",
                   marker_color=color, showlegend=False,
                   hovertemplate="%{y}: %{x:,}<extra></extra>"),
            row=i, col=1,
        )
        fig.update_xaxes(title_text="count", row=i, col=1)

    fig.update_layout(
        title="Top 20 Bigrams per Media Outlet",
        height=340 * n,
        font=dict(size=12),
        plot_bgcolor="white",
        paper_bgcolor="#f9f9f9",
        margin=dict(l=200, r=40, t=60, b=40),
    )

    path = os.path.join(OUTPUT_DIR, "viz_media_bigrams.html")
    fig.write_html(path, include_plotlyjs="cdn")
    print(f"  -> {path}")


# ─────────────────────────────────────────────
# VIZ: Distinctive bigrams (log-odds) — tweets + media combined
# ─────────────────────────────────────────────
def viz_distinctive_bigrams(tweet_counts: "dict",
                             media_counts: "dict"):
    print("[viz] distinctive bigrams ...")

    # Build combined "all" counter for each corpus
    all_tweet_counter: Counter = Counter()
    for c in tweet_counts.values():
        all_tweet_counter.update(c)

    all_media_counter: Counter = Counter()
    for c in media_counts.values():
        all_media_counter.update(c)

    sources = (
        [(acct, tweet_counts[acct], all_tweet_counter, ACCOUNT_COLORS.get(acct, "#888"), "tweet")
         for acct in ACCOUNT_ORDER if acct in tweet_counts]
        +
        [(MEDIA_LABELS.get(dom, dom), media_counts[dom], all_media_counter,
          MEDIA_COLORS.get(dom, "#888"), "media")
         for dom in MEDIA_ORDER if dom in media_counts]
    )

    n = len(sources)
    ncols = 2
    nrows = math.ceil(n / ncols)

    titles = [s[0] for s in sources]
    fig = make_subplots(
        rows=nrows, cols=ncols,
        subplot_titles=titles,
        vertical_spacing=0.08,
        horizontal_spacing=0.12,
    )

    for idx, (label, counter, all_counter, color, _) in enumerate(sources):
        row = idx // ncols + 1
        col = idx % ncols + 1

        top = distinctive_bigrams(counter, all_counter, top_n=15, min_count=5)
        if not top:
            continue
        labels = [b for b, _ in reversed(top)]
        scores = [s for _, s in reversed(top)]

        fig.add_trace(
            go.Bar(x=scores, y=labels, orientation="h",
                   marker_color=color, showlegend=False,
                   hovertemplate="%{y}: log-odds %{x:.2f}<extra></extra>"),
            row=row, col=col,
        )
        fig.update_xaxes(title_text="log-odds", row=row, col=col)

    fig.update_layout(
        title="Most Distinctive Bigrams per Source (log-odds vs rest of corpus)",
        height=420 * nrows,
        font=dict(size=11),
        plot_bgcolor="white",
        paper_bgcolor="#f9f9f9",
        margin=dict(l=180, r=40, t=80, b=40),
    )

    path = os.path.join(OUTPUT_DIR, "viz_distinctive_bigrams.html")
    fig.write_html(path, include_plotlyjs="cdn")
    print(f"  -> {path}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print("=" * 60)
    print("N-gram Comparison: Twitter Accounts & Media Outlets")
    print("=" * 60)
    print()

    tweet_counts = load_tweet_bigrams()
    media_counts = load_media_bigrams()

    print()
    viz_tweet_bigrams(tweet_counts)
    viz_media_bigrams(media_counts)
    viz_distinctive_bigrams(tweet_counts, media_counts)

    print("\nDone. Outputs in", OUTPUT_DIR)


if __name__ == "__main__":
    main()
