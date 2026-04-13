"""
event_framing.py — Compare how government tweets vs independent media
framed the same key political events.

For each event with sufficient coverage on both sides, computes
log-odds(government tweets / media articles) to surface words that
each side emphasized or avoided.

OUTPUTS (output/event_framing/):
  viz_butterfly.html   — per-event diverging bars (event dropdown)
  viz_scatter.html     — word-level scatter govt% vs media%, event dropdown
"""

import csv
import math
import os
import re
from collections import Counter, defaultdict
from datetime import date, timedelta

import plotly.graph_objects as go
from plotly.subplots import make_subplots

REPO_ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TWEETS_CSV = os.path.join(REPO_ROOT, "output", "data", "tweets.csv")
MEDIA_CSV  = os.path.join(REPO_ROOT, "output", "articles_text.csv")
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
    "https","http","co","rt","pic","twitter","amp","via",
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
# VIZ 1: Butterfly chart (event dropdown)
# ─────────────────────────────────────────────
def viz_butterfly(tweet_rows, article_rows):
    print("[viz] butterfly chart ...")
    TOP = 18

    events_data = []
    for label, date_str in KEY_EVENTS:
        ed = date.fromisoformat(date_str)
        t_tok, a_tok = window_tokens(tweet_rows, article_rows, ed)
        t_count = Counter(t_tok)
        a_count = Counter(a_tok)
        n_t, n_a = len(t_tok), len(a_tok)
        if n_t < MIN_TWEETS or n_a < MIN_ARTICLES:
            print(f"  [skip] {label}: {n_t} tweet tokens, {n_a} article tokens")
            continue
        print(f"  {label}: {n_t:,} tweet tokens, {n_a:,} article tokens")

        all_words = (set(t_count) | set(a_count))
        scores = {}
        for w in all_words:
            if t_count[w] < MIN_FREQ and a_count[w] < MIN_FREQ:
                continue
            scores[w] = log_odds(t_count[w], n_t, a_count[w], n_a)

        # top govt words (positive) and top media words (negative)
        sorted_scores = sorted(scores.items(), key=lambda x: x[1])
        media_words = [(w, s) for w, s in sorted_scores[:TOP]]    # most negative
        govt_words  = [(w, s) for w, s in sorted_scores[-TOP:]]   # most positive

        events_data.append({
            "label":       label,
            "media_words": media_words,
            "govt_words":  govt_words,
            "n_tweets":    n_t,
            "n_articles":  n_a,
        })

    if not events_data:
        print("  No events had sufficient data.")
        return

    fig = go.Figure()
    buttons = []

    for i, ev in enumerate(events_data):
        mw = ev["media_words"]   # negative scores → media-dominant
        gw = ev["govt_words"]    # positive scores → govt-dominant

        # Combine into one diverging chart
        # media words: negative bars on left
        m_labels = [w for w, _ in mw]
        m_vals   = [s for _, s in mw]
        # govt words: positive bars on right
        g_labels = [w for w, _ in gw][::-1]
        g_vals   = [s for _, s in gw][::-1]

        all_labels = m_labels + g_labels
        all_vals   = m_vals + g_vals
        colors     = ["#457b9d"] * len(m_labels) + ["#e63946"] * len(g_labels)
        hover      = [
            f"<b>{w}</b><br>log-odds: {s:.2f}<br><i>↑ media emphasis</i>"
            for w, s in mw
        ] + [
            f"<b>{w}</b><br>log-odds: {s:.2f}<br><i>↑ government emphasis</i>"
            for w, s in gw[::-1]
        ]

        fig.add_trace(go.Bar(
            x=all_vals,
            y=all_labels,
            orientation="h",
            marker_color=colors,
            visible=(i == 0),
            name=ev["label"],
            hovertemplate="%{customdata}<extra></extra>",
            customdata=hover,
        ))

        visible = [j == i for j in range(len(events_data))]
        buttons.append(dict(
            method="update",
            label=ev["label"],
            args=[
                {"visible": visible},
                {"title": (
                    f"<b>{ev['label']}</b> — framing gap<br>"
                    f"<span style='color:#e63946'>■ Government tweets</span>"
                    f"  <span style='color:#457b9d'>■ Media articles</span>"
                    f"  ({ev['n_tweets']:,} tweet tokens · "
                    f"{ev['n_articles']:,} article tokens · ±{WINDOW_DAYS}d)"
                )},
            ],
        ))

    first = events_data[0]
    fig.update_layout(
        title=(
            f"<b>{first['label']}</b> — framing gap<br>"
            f"<span style='color:#e63946'>■ Government tweets</span>"
            f"  <span style='color:#457b9d'>■ Media articles</span>"
            f"  ({first['n_tweets']:,} tweet tokens · "
            f"{first['n_articles']:,} article tokens · ±{WINDOW_DAYS}d)"
        ),
        height=680,
        margin=dict(l=160, r=40, t=110, b=60),
        xaxis=dict(
            title="← media emphasis  |  government emphasis →",
            zeroline=True, zerolinecolor="#999", zerolinewidth=2,
            showgrid=True, gridcolor="#eee",
        ),
        yaxis=dict(tickfont_size=12),
        updatemenus=[dict(
            buttons=buttons,
            direction="down",
            showactive=True,
            x=0.0, xanchor="left",
            y=1.15, yanchor="top",
            bgcolor="white",
            bordercolor="#ccc",
        )],
        plot_bgcolor="#fafafa",
        paper_bgcolor="white",
        shapes=[dict(
            type="line", x0=0, x1=0, y0=-0.5, y1=len(events_data[0]["media_words"]) +
            len(events_data[0]["govt_words"]) - 0.5,
            line=dict(color="#666", width=1.5),
        )],
    )

    path = os.path.join(OUTPUT_DIR, "viz_butterfly.html")
    fig.write_html(path)
    print(f"  -> {path}")


# ─────────────────────────────────────────────
# VIZ 2: Scatter — govt% vs media% per word
# ─────────────────────────────────────────────
def viz_scatter(tweet_rows, article_rows):
    print("[viz] framing scatter ...")

    fig = go.Figure()
    buttons = []

    for i, (label, date_str) in enumerate(KEY_EVENTS):
        ed = date.fromisoformat(date_str)
        t_tok, a_tok = window_tokens(tweet_rows, article_rows, ed)
        t_count = Counter(t_tok)
        a_count = Counter(a_tok)
        n_t, n_a = len(t_tok), len(a_tok)
        if n_t < MIN_TWEETS or n_a < MIN_ARTICLES:
            continue

        # word frequency as % of total tokens
        all_words = {w for w in (set(t_count) | set(a_count))
                     if t_count[w] >= MIN_FREQ or a_count[w] >= MIN_FREQ}

        words  = list(all_words)
        x_vals = [t_count.get(w, 0) / n_t * 100 for w in words]  # govt %
        y_vals = [a_count.get(w, 0) / n_a * 100 for w in words]  # media %

        # compute how far each word is from the diagonal (govt - media)
        divergence = [x - y for x, y in zip(x_vals, y_vals)]

        # label the 12 most divergent words on each side
        indexed = sorted(enumerate(divergence), key=lambda t: t[1])
        label_idxs = {idx for idx, _ in indexed[:12]} | {idx for idx, _ in indexed[-12:]}
        text_labels = [words[j] if j in label_idxs else "" for j in range(len(words))]

        # color: red = govt-dominant, blue = media-dominant, gray = shared
        point_colors = []
        for d in divergence:
            if d > 0.05:
                point_colors.append("#e63946")
            elif d < -0.05:
                point_colors.append("#457b9d")
            else:
                point_colors.append("#aaa")

        max_val = max(max(x_vals), max(y_vals), 0.01) * 1.1

        fig.add_trace(go.Scatter(
            x=x_vals, y=y_vals,
            mode="markers+text",
            text=text_labels,
            textposition="top center",
            textfont=dict(size=10),
            marker=dict(
                color=point_colors,
                size=7,
                opacity=0.75,
                line=dict(width=0),
            ),
            visible=(i == 0),
            name=label,
            customdata=[
                f"<b>{w}</b><br>Govt tweets: {x:.2f}%<br>Media articles: {y:.2f}%"
                for w, x, y in zip(words, x_vals, y_vals)
            ],
            hovertemplate="%{customdata}<extra></extra>",
        ))

        # diagonal reference line
        fig.add_trace(go.Scatter(
            x=[0, max_val], y=[0, max_val],
            mode="lines",
            line=dict(color="#ccc", dash="dot", width=1),
            showlegend=False,
            hoverinfo="skip",
            visible=(i == 0),
        ))

        visible_flags = []
        for j in range(i * 2):
            visible_flags.append(False)
        visible_flags.extend([True, True])
        for j in range((len(KEY_EVENTS) - i - 1) * 2):
            visible_flags.append(False)

        buttons.append(dict(
            method="update",
            label=label,
            args=[
                {"visible": visible_flags},
                {"title": (
                    f"<b>{label}</b> — word frequency: government vs media<br>"
                    f"<span style='color:#e63946'>■ govt-dominant</span>  "
                    f"<span style='color:#457b9d'>■ media-dominant</span>  "
                    f"<span style='color:#aaa'>■ shared</span>  "
                    f"(±{WINDOW_DAYS}d window)"
                )},
                {"xaxis.range": [0, max_val], "yaxis.range": [0, max_val]},
            ],
        ))

    if not fig.data:
        return

    first_label = KEY_EVENTS[0][0]
    fig.update_layout(
        title=(
            f"<b>{first_label}</b> — word frequency: government vs media<br>"
            f"<span style='color:#e63946'>■ govt-dominant</span>  "
            f"<span style='color:#457b9d'>■ media-dominant</span>  "
            f"<span style='color:#aaa'>■ shared</span>  "
            f"(±{WINDOW_DAYS}d window)"
        ),
        height=620,
        margin=dict(l=80, r=40, t=110, b=80),
        xaxis=dict(
            title="% of government tweet tokens",
            showgrid=True, gridcolor="#eee",
        ),
        yaxis=dict(
            title="% of media article tokens",
            showgrid=True, gridcolor="#eee",
        ),
        updatemenus=[dict(
            buttons=buttons,
            direction="down",
            showactive=True,
            x=0.0, xanchor="left",
            y=1.15, yanchor="top",
            bgcolor="white",
            bordercolor="#ccc",
        )],
        plot_bgcolor="#fafafa",
        paper_bgcolor="white",
    )

    path = os.path.join(OUTPUT_DIR, "viz_scatter.html")
    fig.write_html(path)
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
    print(f"Government accounts: {', '.join(sorted(GOVT_ACCOUNTS))}")
    print(f"Media outlets: {', '.join(sorted(MEDIA_DOMAINS))}")
    print()

    tweet_rows   = load_tweets()
    article_rows = load_articles()

    viz_butterfly(tweet_rows, article_rows)
    viz_scatter(tweet_rows, article_rows)

    print("\nDone. Outputs in", OUTPUT_DIR)


if __name__ == "__main__":
    main()
