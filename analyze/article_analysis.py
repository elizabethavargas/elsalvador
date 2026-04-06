"""
article_analysis.py
===================
Analyzes the El Salvador Presidencia press release dataset (6,574 articles,
2019–2025) and produces a suite of Plotly visualizations plus a summary CSV.

Run from project root:
    python analyze/article_analysis.py
"""

import os
import math
import warnings
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from collections import Counter

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
INPUT_CSV = "output/el_salvador_political_dataset.csv"
OUTPUT_DIR = "output/article_analysis"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Key events: (label, approximate date string used for vertical lines)
# ---------------------------------------------------------------------------
KEY_EVENTS = [
    ("Bukele inaugurado", "2019-06-01"),
    ("Militares en Asamblea", "2020-02-09"),
    ("COVID emergencia", "2020-03-21"),
    ("Elecciones Nuevas Ideas", "2021-02-28"),
    ("Nueva Asamblea remueve magistrados", "2021-05-01"),
    ("Ley Bitcoin aprobada", "2021-06-09"),
    ("Bitcoin moneda legal", "2021-09-07"),
    ("Reelección aprobada (SC)", "2021-09-03"),
    ("Estado de excepción (pandillas)", "2022-03-27"),
    ("CECOT inaugurado", "2023-11-01"),
    ("Segundo mandato Bukele", "2024-06-01"),
]

# Short labels for crowded charts
SHORT_LABELS = {
    "Bukele inaugurado": "Inauguración",
    "Militares en Asamblea": "Militares",
    "COVID emergencia": "COVID",
    "Elecciones Nuevas Ideas": "Elecciones",
    "Nueva Asamblea remueve magistrados": "Magistrados",
    "Ley Bitcoin aprobada": "Ley BTC",
    "Bitcoin moneda legal": "BTC legal",
    "Reelección aprobada (SC)": "Reelección SC",
    "Estado de excepción (pandillas)": "Excepción",
    "CECOT inaugurado": "CECOT",
    "Segundo mandato Bukele": "2do mandato",
}

# Keyword groups for rhetorical theme analysis
KEYWORD_GROUPS = {
    "Seguridad/Pandillas": [
        "pandill", "ms-13", "maras", "homicidio", "criminal",
        "capturado", "detenido", "extorsion", "violencia", "terroris", "regimen",
    ],
    "Bitcoin/Economía Digital": [
        "bitcoin", "criptomoneda", "chivo", "blockchain", "activo digital",
    ],
    "COVID": [
        "covid", "coronavirus", "pandemia", "cuarentena", "vacuna",
    ],
    "Logros/Obras": [
        "inauguramos", "construimos", "entregamos", "logramos", "obra",
        "proyecto", "infraestructura", "inversion",
    ],
    "Democracia/Instituciones": [
        "democracia", "constitucion", "derechos", "libertad", "justicia",
        "tribunal", "corte suprema",
    ],
    "Economía/Empleo": [
        "empleo", "trabajo", "economia", "crecimiento", "pib",
        "exportacion", "empresa", "inversion",
    ],
}

# Named entities to track over time
ENTITIES_TO_TRACK = [
    "Nayib Bukele",
    "Asamblea",
    "Bitcoin",
    "COVID",
    "pandillas",
    "MS-13",
    "Estados Unidos",
    "FGR",
    "Corte Suprema",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def event_dates():
    """Return list of (label, pd.Timestamp) pairs."""
    return [(lbl, pd.Timestamp(dt)) for lbl, dt in KEY_EVENTS]


def add_event_vlines(fig, y_max=None, row=None, col=None, opacity=0.5):
    """Add dotted vertical lines + annotations for every key event."""
    for lbl, ts in event_dates():
        short = SHORT_LABELS.get(lbl, lbl)
        kw = {}
        if row is not None:
            kw["row"] = row
            kw["col"] = col
        fig.add_vline(
            x=ts.timestamp() * 1000,  # plotly uses ms epoch for dates
            line_dash="dot",
            line_color="gray",
            line_width=1,
            opacity=opacity,
            annotation_text=short,
            annotation_position="top right",
            annotation_font_size=8,
            annotation_textangle=-60,
            **kw,
        )


def save(fig, name):
    path = os.path.join(OUTPUT_DIR, name)
    fig.write_html(path)
    print(f"  -> saved {path}")


def text_hits_group(text, terms):
    """Return True if any term appears (case-insensitive) in text."""
    if not isinstance(text, str):
        return False
    tl = text.lower()
    return any(t in tl for t in terms)


def pct_hitting(df_sub, terms):
    """Percentage of rows whose 'text' column hits any term in list."""
    if len(df_sub) == 0:
        return 0.0
    hits = df_sub["text"].apply(lambda t: text_hits_group(t, terms)).sum()
    return 100.0 * hits / len(df_sub)


def log_odds_ratio(word, fg_counts, fg_total, bg_counts, bg_total, alpha=0.5):
    """
    Smoothed log-odds ratio for a word.
    fg = foreground (window articles), bg = background (all others).
    """
    fg = fg_counts.get(word, 0) + alpha
    bg = bg_counts.get(word, 0) + alpha
    fg_t = fg_total + alpha * len(fg_counts)
    bg_t = bg_total + alpha * len(bg_counts)
    return math.log((fg / fg_t) / (bg / bg_t))


def tokenize_title(title):
    """Simple whitespace tokenizer; strip punctuation, lowercase, drop stopwords."""
    STOPWORDS = {
        "de", "la", "el", "en", "y", "a", "los", "las", "del", "que",
        "se", "por", "con", "un", "una", "para", "al", "es", "su", "lo",
        "más", "no", "como", "o", "pero", "sus", "le", "ya", "fue",
        "desde", "durante", "entre", "sobre", "con", "ha", "han",
        "este", "esta", "estos", "estas", "ese", "esa", "esos", "esas",
        "hay", "ser", "son", "era", "sido", "por", "ante", "ante",
        "presidencia", "presidente", "presidencial", "salvador",
        "nayib", "bukele", "gobierno", "ministerio",
    }
    if not isinstance(title, str):
        return []
    tokens = []
    for w in title.lower().split():
        w = w.strip(".,;:!?\"'()[]{}—–-")
        if w and len(w) > 2 and w not in STOPWORDS:
            tokens.append(w)
    return tokens


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
print("[load] Reading dataset...")
df = pd.read_csv(INPUT_CSV, encoding="utf-8-sig", low_memory=False)
df["date"] = pd.to_datetime(df["date"], errors="coerce")
df = df.dropna(subset=["date"])
df["year_month"] = df["date"].dt.to_period("M")
df["word_count"] = pd.to_numeric(df["word_count"], errors="coerce")
df["days_from_event"] = pd.to_numeric(df["days_from_event"], errors="coerce")
df["mentions_bukele"] = df["mentions_bukele"].astype(bool)
df["has_corruption_keyword"] = df["has_corruption_keyword"].astype(bool)

print(f"[load] Loaded {len(df):,} articles, {df['date'].min().date()} – {df['date'].max().date()}")

# ---------------------------------------------------------------------------
# 1. viz_volume_over_time.html — Monthly article count + event lines
# ---------------------------------------------------------------------------
print("[1/7] Building volume over time chart...")

monthly_counts = (
    df.groupby("year_month")
    .size()
    .reset_index(name="n_articles")
)
monthly_counts["date"] = monthly_counts["year_month"].dt.to_timestamp()

fig1 = go.Figure()
fig1.add_trace(go.Scatter(
    x=monthly_counts["date"],
    y=monthly_counts["n_articles"],
    mode="lines+markers",
    name="Artículos",
    line=dict(color="#1f77b4", width=2),
    marker=dict(size=4),
    hovertemplate="%{x|%b %Y}: %{y} artículos<extra></extra>",
))
add_event_vlines(fig1)
fig1.update_layout(
    title="Volumen mensual de artículos — Presidencia de El Salvador (2019–2025)",
    xaxis_title="Mes",
    yaxis_title="N.º de artículos",
    hovermode="x unified",
    template="plotly_white",
    height=550,
)
save(fig1, "viz_volume_over_time.html")

# ---------------------------------------------------------------------------
# 2. viz_event_volume.html — Before vs. After 30-day article counts per event
# ---------------------------------------------------------------------------
print("[2/7] Building event volume (before/after) chart...")

before_counts, after_counts = [], []
labels = []
for lbl, ts in event_dates():
    window_before = df[(df["date"] >= ts - pd.Timedelta(days=30)) & (df["date"] < ts)]
    window_after  = df[(df["date"] > ts) & (df["date"] <= ts + pd.Timedelta(days=30))]
    before_counts.append(len(window_before))
    after_counts.append(len(window_after))
    labels.append(SHORT_LABELS.get(lbl, lbl))

fig2 = go.Figure()
fig2.add_trace(go.Bar(
    name="30 días ANTES",
    x=labels,
    y=before_counts,
    marker_color="#ff7f0e",
    hovertemplate="%{x}<br>Antes: %{y}<extra></extra>",
))
fig2.add_trace(go.Bar(
    name="30 días DESPUÉS",
    x=labels,
    y=after_counts,
    marker_color="#1f77b4",
    hovertemplate="%{x}<br>Después: %{y}<extra></extra>",
))
fig2.update_layout(
    barmode="group",
    title="Artículos publicados en los 30 días antes vs. después de cada evento clave",
    xaxis_title="Evento",
    yaxis_title="N.º de artículos",
    hovermode="x unified",
    template="plotly_white",
    height=500,
    legend=dict(orientation="h", y=1.05),
)
save(fig2, "viz_event_volume.html")

# ---------------------------------------------------------------------------
# 3. viz_event_keywords.html — Keyword group presence before vs. after each event
# ---------------------------------------------------------------------------
print("[3/7] Building event keyword group chart...")

n_events = len(KEY_EVENTS)
n_groups = len(KEYWORD_GROUPS)
group_names = list(KEYWORD_GROUPS.keys())

# Compute baseline (all articles)
baseline_pcts = {g: pct_hitting(df, terms) for g, terms in KEYWORD_GROUPS.items()}

# Build one subplot per event (arrange in grid: 4 cols)
n_cols = 3
n_rows = math.ceil(n_events / n_cols)

fig3 = make_subplots(
    rows=n_rows, cols=n_cols,
    subplot_titles=[SHORT_LABELS.get(lbl, lbl) for lbl, _ in KEY_EVENTS],
    vertical_spacing=0.08,
    horizontal_spacing=0.06,
)

for idx, (lbl, ts_str) in enumerate(KEY_EVENTS):
    ts = pd.Timestamp(ts_str)
    row = idx // n_cols + 1
    col = idx % n_cols + 1

    before = df[(df["date"] >= ts - pd.Timedelta(days=30)) & (df["date"] < ts)]
    after  = df[(df["date"] > ts) & (df["date"] <= ts + pd.Timedelta(days=30))]

    before_pcts = [pct_hitting(before, KEYWORD_GROUPS[g]) for g in group_names]
    after_pcts  = [pct_hitting(after,  KEYWORD_GROUPS[g]) for g in group_names]

    show_legend = (idx == 0)
    fig3.add_trace(go.Bar(
        name="Antes",
        x=group_names,
        y=before_pcts,
        marker_color="#ff7f0e",
        showlegend=show_legend,
        hovertemplate="%{x}<br>Antes: %{y:.1f}%<extra></extra>",
    ), row=row, col=col)
    fig3.add_trace(go.Bar(
        name="Después",
        x=group_names,
        y=after_pcts,
        marker_color="#1f77b4",
        showlegend=show_legend,
        hovertemplate="%{x}<br>Después: %{y:.1f}%<extra></extra>",
    ), row=row, col=col)

fig3.update_layout(
    barmode="group",
    title="% artículos que mencionan cada grupo temático (±30 días de cada evento)",
    template="plotly_white",
    height=280 * n_rows,
    legend=dict(orientation="h", y=1.02),
)
# Rotate x-axis tick labels for all subplots
for axis in fig3.layout:
    if axis.startswith("xaxis"):
        fig3.layout[axis].tickangle = -40
        fig3.layout[axis].tickfont = dict(size=8)
save(fig3, "viz_event_keywords.html")

# ---------------------------------------------------------------------------
# 4. viz_article_length.html — Rolling 30-day average word count over time
# ---------------------------------------------------------------------------
print("[4/7] Building article length over time chart...")

# Sort by date, compute rolling mean (window=30 articles approximates 30 days
# better than calendar rolling, but we'll use calendar via resample + rolling)
daily_wc = (
    df.groupby("date")["word_count"]
    .mean()
    .reset_index()
    .sort_values("date")
    .set_index("date")
    .resample("D")
    .mean()
)
# 30-day rolling average
daily_wc["rolling"] = daily_wc["word_count"].rolling(30, center=True, min_periods=1).mean()
daily_wc = daily_wc.reset_index()

fig4 = go.Figure()
fig4.add_trace(go.Scatter(
    x=daily_wc["date"],
    y=daily_wc["rolling"],
    mode="lines",
    name="Promedio móvil 30 días",
    line=dict(color="#2ca02c", width=2),
    hovertemplate="%{x|%d %b %Y}: %{y:.0f} palabras<extra></extra>",
))
add_event_vlines(fig4)
fig4.update_layout(
    title="Promedio móvil (30 días) de la longitud de artículos — palabras",
    xaxis_title="Fecha",
    yaxis_title="Palabras (promedio)",
    hovermode="x unified",
    template="plotly_white",
    height=500,
)
save(fig4, "viz_article_length.html")

# ---------------------------------------------------------------------------
# 5. viz_title_words_per_event.html — Distinctive title words per event (log-odds)
# ---------------------------------------------------------------------------
print("[5/7] Building title words per event chart...")

# Build full corpus title word counts (for background)
all_title_tokens = []
for title in df["title"].dropna():
    all_title_tokens.extend(tokenize_title(title))
bg_counts_all = Counter(all_title_tokens)
bg_total_all = len(all_title_tokens)

n_cols5 = 3
n_rows5 = math.ceil(n_events / n_cols5)

fig5 = make_subplots(
    rows=n_rows5, cols=n_cols5,
    subplot_titles=[SHORT_LABELS.get(lbl, lbl) for lbl, _ in KEY_EVENTS],
    vertical_spacing=0.08,
    horizontal_spacing=0.1,
)

for idx, (lbl, ts_str) in enumerate(KEY_EVENTS):
    ts = pd.Timestamp(ts_str)
    row = idx // n_cols5 + 1
    col = idx % n_cols5 + 1

    window = df[
        (df["date"] >= ts - pd.Timedelta(days=30)) &
        (df["date"] <= ts + pd.Timedelta(days=30))
    ]
    outside = df[~df.index.isin(window.index)]

    fg_tokens = []
    for title in window["title"].dropna():
        fg_tokens.extend(tokenize_title(title))
    fg_counts = Counter(fg_tokens)
    fg_total = len(fg_tokens)

    bg_tokens = []
    for title in outside["title"].dropna():
        bg_tokens.extend(tokenize_title(title))
    bg_counts = Counter(bg_tokens)
    bg_total = len(bg_tokens)

    # Only consider words appearing ≥3 times in the window
    candidates = [w for w, c in fg_counts.items() if c >= 3]
    scored = sorted(
        candidates,
        key=lambda w: log_odds_ratio(w, fg_counts, fg_total, bg_counts, bg_total),
        reverse=True,
    )[:10]

    if not scored:
        continue

    lor_vals = [log_odds_ratio(w, fg_counts, fg_total, bg_counts, bg_total) for w in scored]
    # Reverse so highest is at top
    fig5.add_trace(go.Bar(
        x=lor_vals[::-1],
        y=scored[::-1],
        orientation="h",
        marker_color="#9467bd",
        showlegend=False,
        hovertemplate="%{y}: log-odds=%{x:.2f}<extra></extra>",
    ), row=row, col=col)

fig5.update_layout(
    title="Palabras más distintivas en títulos (±30 días de cada evento) — log-odds ratio",
    template="plotly_white",
    height=280 * n_rows5,
)
for axis in fig5.layout:
    if axis.startswith("yaxis"):
        fig5.layout[axis].tickfont = dict(size=9)
save(fig5, "viz_title_words_per_event.html")

# ---------------------------------------------------------------------------
# 6. viz_entities_over_time.html — Key entity frequency (monthly, rolling 3-mo)
# ---------------------------------------------------------------------------
print("[6/7] Building entity frequency over time chart...")

def entity_monthly_freq(entity_term):
    """
    For each article, check if the named_entities field (pipe-separated
    'Name (TYPE)' strings) contains the given term (case-insensitive).
    Return monthly count and pct.
    """
    term_lower = entity_term.lower()
    df["_hit"] = df["named_entities"].apply(
        lambda s: term_lower in str(s).lower() if isinstance(s, str) else False
    )
    monthly = (
        df.groupby("year_month")
        .agg(hits=("_hit", "sum"), total=("_hit", "count"))
        .reset_index()
    )
    monthly["pct"] = 100.0 * monthly["hits"] / monthly["total"].replace(0, np.nan)
    monthly["date"] = monthly["year_month"].dt.to_timestamp()
    monthly["rolling"] = monthly["pct"].rolling(3, center=True, min_periods=1).mean()
    df.drop(columns=["_hit"], inplace=True)
    return monthly

# Color palette
palette = px.colors.qualitative.Plotly

fig6 = go.Figure()
for i, entity in enumerate(ENTITIES_TO_TRACK):
    monthly = entity_monthly_freq(entity)
    fig6.add_trace(go.Scatter(
        x=monthly["date"],
        y=monthly["rolling"],
        mode="lines",
        name=entity,
        line=dict(color=palette[i % len(palette)], width=2),
        hovertemplate=f"{entity}<br>%{{x|%b %Y}}: %{{y:.1f}}%<extra></extra>",
    ))

add_event_vlines(fig6, opacity=0.3)
fig6.update_layout(
    title="Frecuencia mensual de entidades clave en artículos (promedio móvil 3 meses, % artículos)",
    xaxis_title="Mes",
    yaxis_title="% artículos que mencionan la entidad",
    hovermode="x unified",
    template="plotly_white",
    height=550,
    legend=dict(orientation="h", y=-0.25, font=dict(size=10)),
)
save(fig6, "viz_entities_over_time.html")

# ---------------------------------------------------------------------------
# 7. rhetoric_shift.csv — Monthly summary table
# ---------------------------------------------------------------------------
print("[7/7] Building rhetoric shift CSV...")

monthly_summary = (
    df.groupby("year_month")
    .agg(
        n_articles=("date", "count"),
        avg_word_count=("word_count", "mean"),
        pct_mentions_bukele=("mentions_bukele", "mean"),
        pct_has_corruption=("has_corruption_keyword", "mean"),
        avg_abs_days_from_event=("days_from_event", lambda x: x.abs().mean()),
    )
    .reset_index()
)
monthly_summary["month"] = monthly_summary["year_month"].dt.to_timestamp().dt.strftime("%Y-%m")
monthly_summary["pct_mentions_bukele"] = (monthly_summary["pct_mentions_bukele"] * 100).round(2)
monthly_summary["pct_has_corruption"] = (monthly_summary["pct_has_corruption"] * 100).round(2)
monthly_summary["avg_word_count"] = monthly_summary["avg_word_count"].round(1)
monthly_summary["avg_abs_days_from_event"] = monthly_summary["avg_abs_days_from_event"].round(1)

out_cols = [
    "month", "n_articles", "avg_word_count",
    "pct_mentions_bukele", "pct_has_corruption", "avg_abs_days_from_event",
]
csv_path = os.path.join(OUTPUT_DIR, "rhetoric_shift.csv")
monthly_summary[out_cols].to_csv(csv_path, index=False, encoding="utf-8-sig")
print(f"  -> saved {csv_path}")

# ---------------------------------------------------------------------------
# Summary findings
# ---------------------------------------------------------------------------
print("\n" + "=" * 70)
print("SUMMARY OF FINDINGS")
print("=" * 70)

# --- Volume spikes ---
print("\n[Volume spikes — 30-day before vs. after]")
ratio_rows = []
for lbl, ts_str in KEY_EVENTS:
    ts = pd.Timestamp(ts_str)
    before_n = len(df[(df["date"] >= ts - pd.Timedelta(days=30)) & (df["date"] < ts)])
    after_n  = len(df[(df["date"] > ts) & (df["date"] <= ts + pd.Timedelta(days=30))])
    ratio = (after_n / before_n) if before_n > 0 else float("inf")
    ratio_rows.append((lbl, before_n, after_n, ratio))

ratio_rows_sorted = sorted(ratio_rows, key=lambda x: x[3], reverse=True)
for lbl, b, a, r in ratio_rows_sorted:
    print(f"  {SHORT_LABELS.get(lbl, lbl):<28}  before={b:>3}  after={a:>3}  ratio={r:.2f}x")

# --- Language shift: which event had biggest shift in keyword group usage ---
print("\n[Language shift — biggest change in keyword group % after vs. before]")
shift_rows = []
for lbl, ts_str in KEY_EVENTS:
    ts = pd.Timestamp(ts_str)
    before = df[(df["date"] >= ts - pd.Timedelta(days=30)) & (df["date"] < ts)]
    after  = df[(df["date"] > ts) & (df["date"] <= ts + pd.Timedelta(days=30))]
    for gname, terms in KEYWORD_GROUPS.items():
        pb = pct_hitting(before, terms)
        pa = pct_hitting(after, terms)
        shift_rows.append((lbl, gname, pb, pa, pa - pb))

shift_df = pd.DataFrame(shift_rows, columns=["event", "group", "pct_before", "pct_after", "shift"])
top_shifts = shift_df.reindex(shift_df["shift"].abs().nlargest(10).index)
for _, row in top_shifts.iterrows():
    direction = "↑" if row["shift"] > 0 else "↓"
    print(
        f"  {SHORT_LABELS.get(row['event'], row['event']):<28}  "
        f"{row['group']:<26}  "
        f"{row['pct_before']:.1f}% → {row['pct_after']:.1f}%  {direction}{abs(row['shift']):.1f}pp"
    )

# --- Most prolific monthly period ---
print("\n[Top 5 most prolific months]")
top_months = monthly_counts.nlargest(5, "n_articles")[["date", "n_articles"]]
for _, row in top_months.iterrows():
    print(f"  {row['date'].strftime('%b %Y')}: {int(row['n_articles'])} articles")

# --- Bukele mention rate trend ---
print("\n[Bukele mention rate by year]")
yearly = df.groupby("year")["mentions_bukele"].mean() * 100
for yr, pct in yearly.items():
    print(f"  {yr}: {pct:.1f}% of articles mention Bukele")

print("\n[Done] All outputs written to:", OUTPUT_DIR)
