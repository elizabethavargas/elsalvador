"""
rhetoric_analysis.py — Rhetorical & thematic trend analysis of SV government tweets

No new packages required beyond pandas + plotly (already installed).

WHAT IT PRODUCES (all in output/rhetoric/):

  viz_themes.html
      Stacked area / line chart: thematic keyword groups (security, Bitcoin,
      COVID, confrontation language, democracy/institutions, etc.) tracked
      monthly for all accounts combined.  Key SV events annotated.

  viz_rhetoric_per_account.html
      4-panel time series per account showing:
        - Emotional punctuation rate  (!/? per tweet)
        - ALL-CAPS word rate
        - First-person singular rate  ("yo / mi / mío" — populist signal)
        - Avg tweet length (chars)

  viz_bukele_shift.html
      Bukele-only deep-dive showing rhetorical escalation from mayor (2019)
      through re-election (2024): confrontation words, caps rate, I-language,
      and anti-institution terms plotted together.

  viz_event_windows.html
      For each key event: bar chart comparing term-group share of tweets
      in the 60 days BEFORE vs. 60 days AFTER, per account.

  rhetoric_metrics.csv
      Monthly per-account metrics table — ready for regression / further stats.
"""

import os
import re
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

INPUT_CSV  = os.path.join("output", "data", "tweets.csv")
OUTPUT_DIR = os.path.join("output", "rhetoric")

# ─────────────────────────────────────────────
# THEMATIC KEYWORD GROUPS
# ─────────────────────────────────────────────
# Each group is a list of Spanish root strings (matched as substrings,
# case-insensitive, so "pandill" catches pandilla/pandillas/pandillero).
TERM_GROUPS = {
    "Seguridad / Crimen": [
        "pandill", "mara", "ms-13", "ms13", "barrio 18",
        "homicidio", "asesinato", "delincuenci", "criminal",
        "capturado", "detenido", "arrestado", "extorsion",
        "violencia", "terroris",
    ],
    "Regimen de Excepcion": [
        "regimen de excepcion", "estado de excepcion", "regimen",
        "excepcion", "suspension de garantias", "prision preventiva",
    ],
    "Bitcoin / Economia Digital": [
        "bitcoin", " btc", "criptomoneda", "crypto", "billetera",
        "chivo", "blockchain", "dolar digital", "activo digital",
    ],
    "COVID-19": [
        "covid", "coronavirus", "pandemia", "cuarentena",
        "vacuna", "contagio", "positivo covid", "pcr",
    ],
    "Confrontacion / Enemigos": [
        "enemigo", "traidor", "mentira", "miente", "corrupto",
        "corrupcion", "oligarquia", "oposicion", "lo quieren",
        "no nos dejan", "ellos quieren", "nos atacan",
        "fake news", "desinformacion",
    ],
    "Democracia / Instituciones": [
        "democracia", "constitucion", "derechos humanos",
        "estado de derecho", "separacion de poderes",
        "libertad de prensa", "independencia judicial",
        "tribunal", "corte suprema",
    ],
    "Economia / Desarrollo": [
        "inversion", "empleos", "infraestructura", "crecimiento",
        "pib", "proyecto", "construcc", "manufactura",
        "exportacion", "turismo",
    ],
    "Orgullo / Nacionalismo": [
        "orgullo", "salvadoreno", "patria", "nacion salvadore",
        "mejor pais", "lo logramos", "historico",
        "primer pais", "primera vez en la historia",
    ],
}

# ─────────────────────────────────────────────
# RHETORICAL INTENSITY MARKERS
# ─────────────────────────────────────────────
# First-person singular — marker of personalised/populist rhetoric
I_WORDS = re.compile(r"\b(yo|mi\b|mis\b|mio|mia|me\b|conmigo)\b", re.IGNORECASE)

# Confrontation word list (broader than the theme group — single words)
CONFRONTATION_WORDS = re.compile(
    r"\b(enemigo|traidor|mentira|corrupto|corrupcion|oligarca|"
    r"ataque|atacan|conspiracion|manipulacion|fake|mentiroso|"
    r"hipocrita|fracasado|delincuente politico)\b",
    re.IGNORECASE
)

# ─────────────────────────────────────────────
# KEY EVENTS
# ─────────────────────────────────────────────
KEY_EVENTS = [
    ("2016-01-01", "Arena/FMLN deadlock"),
    ("2019-06-01", "Bukele inaugurated"),
    ("2020-03-01", "COVID emergency"),
    ("2021-05-01", "Assembly fires CSJ+FGR"),
    ("2021-09-01", "Bitcoin legal tender"),
    ("2022-03-01", "Regimen de Excepcion"),
    ("2023-12-01", "CECOT opens"),
    ("2024-02-01", "Bukele re-elected"),
]

ACCOUNT_COLORS = {
    "PresidenciaSV": "#1f77b4",
    "Gobierno_SV":   "#2ca02c",
    "nayibbukele":   "#d62728",
    "AsambleaSV":    "#9467bd",
    "FGR_SV":        "#8c564b",
}


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def add_events(fig, y_frac=1.02, row=None, col=None):
    """Add dotted event lines to a figure."""
    kwargs = {}
    if row is not None:
        kwargs = {"row": row, "col": col}
    for dt_str, label in KEY_EVENTS:
        dt = pd.Timestamp(dt_str)
        fig.add_vline(
            x=dt.timestamp() * 1000,
            line_width=1.1, line_dash="dot",
            line_color="rgba(60,60,60,0.4)",
            annotation_text=label,
            annotation_position="top left",
            annotation_font_size=7,
            **kwargs,
        )
    return fig


def rolling(series, window=3):
    """3-month centred rolling mean to smooth monthly noise."""
    return series.rolling(window, center=True, min_periods=1).mean()


def hits(text, terms):
    """Return 1 if any term in list appears in text (substring, lowercase)."""
    t = text.lower()
    return int(any(term in t for term in terms))


# ─────────────────────────────────────────────
# LOAD DATA
# ─────────────────────────────────────────────
def load():
    print(f"[load] {INPUT_CSV} ...")
    df = pd.read_csv(INPUT_CSV, dtype=str).fillna("")
    df = df.drop_duplicates(subset="tweet_id")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df[df["date"].notna()].copy()
    df["ym"] = df["date"].dt.to_period("M").dt.to_timestamp()
    print(f"[load] {len(df):,} tweets across {df['handle'].nunique()} accounts")
    return df


# ─────────────────────────────────────────────
# BUILD MONTHLY METRICS
# ─────────────────────────────────────────────
def compute_metrics(df):
    """
    Returns a monthly per-account DataFrame with columns:
      n_tweets, theme_*, exclaim_rate, caps_rate, i_rate,
      confront_rate, avg_len, reply_rate
    """
    print("[metrics] Computing monthly rhetorical metrics ...")
    rows = []
    for _, tw in df.iterrows():
        t = tw["text"]
        words = t.split()
        n_words = max(len(words), 1)

        # Thematic hits (binary per tweet)
        theme_vals = {
            grp: hits(t, terms) for grp, terms in TERM_GROUPS.items()
        }

        # Rhetorical metrics (per-tweet floats, averaged over month later)
        exclaim = (t.count("!") + t.count("?")) / max(len(t), 1) * 100
        caps    = sum(1 for w in words if w.isupper() and len(w) > 1) / n_words * 100
        i_lang  = len(I_WORDS.findall(t)) / n_words * 100
        confront = len(CONFRONTATION_WORDS.findall(t)) / n_words * 100
        length  = len(t)

        row = {
            "ym":     tw["ym"],
            "handle": tw["handle"],
            "exclaim": exclaim,
            "caps":    caps,
            "i_lang":  i_lang,
            "confront": confront,
            "length":  length,
        }
        row.update(theme_vals)
        rows.append(row)

    raw = pd.DataFrame(rows)

    # Aggregate by account × month
    agg_funcs = {
        "exclaim":  "mean",
        "caps":     "mean",
        "i_lang":   "mean",
        "confront": "mean",
        "length":   "mean",
    }
    agg_funcs.update({grp: "mean" for grp in TERM_GROUPS})  # pct tweets with theme
    agg_funcs["handle"] = "count"   # gives n_tweets

    monthly = (raw.groupby(["ym", "handle"])
                  .agg({**agg_funcs, "handle": "count"})
                  .rename(columns={"handle": "n_tweets"})
                  .reset_index())

    # Multiply theme means by 100 → "% of account's tweets that month"
    for grp in TERM_GROUPS:
        monthly[grp] = monthly[grp] * 100

    print(f"[metrics] {len(monthly):,} account-month rows")
    return monthly


# ─────────────────────────────────────────────
# VIZ 1: THEMES OVER TIME (all accounts)
# ─────────────────────────────────────────────
def viz_themes(monthly):
    print("[viz] themes over time ...")
    all_months = monthly.groupby("ym")[list(TERM_GROUPS.keys())].mean().reset_index()
    all_months = all_months.sort_values("ym")

    fig = go.Figure()
    colors = px.colors.qualitative.Safe
    for i, grp in enumerate(TERM_GROUPS):
        y = rolling(all_months[grp])
        fig.add_trace(go.Scatter(
            x=all_months["ym"], y=y,
            name=grp,
            mode="lines",
            line=dict(width=2, color=colors[i % len(colors)]),
            fill="tonexty" if i > 0 else None,
            opacity=0.8,
        ))

    add_events(fig)
    fig.update_layout(
        title="Thematic discourse over time — all accounts (3-month rolling avg, % of tweets)",
        xaxis_title="Month", yaxis_title="% tweets containing theme",
        height=550, hovermode="x unified",
        legend=dict(font_size=9, orientation="h", y=-0.25),
    )
    path = os.path.join(OUTPUT_DIR, "viz_themes.html")
    fig.write_html(path)
    print(f"  -> {path}")


# ─────────────────────────────────────────────
# VIZ 2: RHETORIC METRICS PER ACCOUNT
# ─────────────────────────────────────────────
def viz_rhetoric(monthly):
    print("[viz] per-account rhetoric metrics ...")
    metrics = [
        ("exclaim",  "Emotional punctuation rate (!? per 100 chars)"),
        ("caps",     "ALL-CAPS word rate (% of words)"),
        ("i_lang",   "First-person singular rate (yo/mi/me per 100 words)"),
        ("confront", "Confrontation word rate (per 100 words)"),
    ]
    accounts = sorted(monthly["handle"].unique())
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=[m[1] for m in metrics],
        shared_xaxes=True, vertical_spacing=0.12,
    )
    positions = [(1,1),(1,2),(2,1),(2,2)]

    for (metric, title), (r, c) in zip(metrics, positions):
        for acct in accounts:
            sub = monthly[monthly["handle"] == acct].sort_values("ym")
            if len(sub) < 3:
                continue
            y = rolling(sub[metric])
            fig.add_trace(go.Scatter(
                x=sub["ym"], y=y,
                name=acct,
                legendgroup=acct,
                showlegend=(r == 1 and c == 1),
                mode="lines",
                line=dict(width=1.8,
                          color=ACCOUNT_COLORS.get(acct, "#888")),
            ), row=r, col=c)

    # Event lines on each subplot
    for dt_str, label in KEY_EVENTS:
        dt = pd.Timestamp(dt_str)
        for r, c in positions:
            fig.add_vline(
                x=dt.timestamp() * 1000,
                line_width=1, line_dash="dot",
                line_color="rgba(60,60,60,0.35)",
                row=r, col=c,
            )

    fig.update_layout(
        title="Rhetorical intensity per account (3-month rolling avg)",
        height=700,
        legend=dict(font_size=10),
        hovermode="x unified",
    )
    path = os.path.join(OUTPUT_DIR, "viz_rhetoric_per_account.html")
    fig.write_html(path)
    print(f"  -> {path}")


# ─────────────────────────────────────────────
# VIZ 3: BUKELE DEEP-DIVE
# ─────────────────────────────────────────────
def viz_bukele(monthly):
    buk = monthly[monthly["handle"] == "nayibbukele"].sort_values("ym").copy()
    if len(buk) == 0:
        print("[viz] No Bukele tweets found, skipping deep-dive.")
        return

    print("[viz] Bukele rhetorical shift ...")
    series = {
        "Confrontation words": rolling(buk["confront"]),
        "ALL-CAPS rate":       rolling(buk["caps"]),
        "I-language (yo/mi)":  rolling(buk["i_lang"]),
        "Seguridad/Crimen %":  rolling(buk["Seguridad / Crimen"]),
        "Confrontacion %":     rolling(buk["Confrontacion / Enemigos"]),
        "Democracia/Inst. %":  rolling(buk["Democracia / Instituciones"]),
    }
    colors_list = ["#d62728","#ff7f0e","#9467bd","#8c564b","#e377c2","#17becf"]

    fig = go.Figure()
    for (name, vals), col in zip(series.items(), colors_list):
        fig.add_trace(go.Scatter(
            x=buk["ym"].values, y=vals.values,
            name=name, mode="lines",
            line=dict(width=2, color=col),
        ))

    add_events(fig)

    # Shade presidential terms
    fig.add_vrect(x0="2019-06-01", x1="2024-06-01",
                  fillcolor="rgba(200,200,255,0.08)",
                  annotation_text="1st term", annotation_position="top left",
                  annotation_font_size=8, line_width=0)
    fig.add_vrect(x0="2024-02-01", x1="2025-12-31",
                  fillcolor="rgba(255,200,200,0.10)",
                  annotation_text="2nd term", annotation_position="top left",
                  annotation_font_size=8, line_width=0)

    fig.update_layout(
        title="@nayibbukele — Rhetorical escalation over time (3-month rolling avg)",
        xaxis_title="Month",
        yaxis_title="Rate / % of tweets",
        height=550, hovermode="x unified",
        legend=dict(font_size=10, orientation="h", y=-0.22),
    )
    path = os.path.join(OUTPUT_DIR, "viz_bukele_shift.html")
    fig.write_html(path)
    print(f"  -> {path}")


# ─────────────────────────────────────────────
# VIZ 4: EVENT WINDOWS  (before vs. after)
# ─────────────────────────────────────────────
def viz_event_windows(df):
    print("[viz] event windows (before/after) ...")
    WINDOW_DAYS = 60
    themes = list(TERM_GROUPS.keys())

    # Precompute theme hit columns on full df
    for grp, terms in TERM_GROUPS.items():
        df[grp] = df["text"].apply(lambda t: hits(t, terms))

    n_events = len(KEY_EVENTS)
    fig = make_subplots(
        rows=(n_events + 1) // 2, cols=2,
        subplot_titles=[label for _, label in KEY_EVENTS],
        vertical_spacing=0.08,
    )

    for idx, (dt_str, label) in enumerate(KEY_EVENTS):
        pivot = pd.Timestamp(dt_str)
        before = df[(df["date"] >= pivot - pd.Timedelta(days=WINDOW_DAYS)) &
                    (df["date"] <  pivot)]
        after  = df[(df["date"] >= pivot) &
                    (df["date"] <  pivot + pd.Timedelta(days=WINDOW_DAYS))]

        r = idx // 2 + 1
        c = idx %  2 + 1

        vals_before = [before[g].mean() * 100 for g in themes]
        vals_after  = [after[g].mean()  * 100 for g in themes]
        short_names = [g.split("/")[0].strip()[:18] for g in themes]

        fig.add_trace(go.Bar(name="Before", x=short_names, y=vals_before,
                             marker_color="steelblue",
                             showlegend=(idx == 0)), row=r, col=c)
        fig.add_trace(go.Bar(name="After",  x=short_names, y=vals_after,
                             marker_color="firebrick",
                             showlegend=(idx == 0)), row=r, col=c)

    fig.update_layout(
        title=f"Theme share 60 days BEFORE vs AFTER each key event (% of tweets)",
        barmode="group",
        height=250 * ((n_events + 1) // 2),
        legend=dict(font_size=10),
    )
    fig.update_xaxes(tickangle=-35, tickfont_size=8)

    path = os.path.join(OUTPUT_DIR, "viz_event_windows.html")
    fig.write_html(path)
    print(f"  -> {path}")


# ─────────────────────────────────────────────
# VIZ 5: TOP DISTINCTIVE WORDS PER ACCOUNT
# ─────────────────────────────────────────────
def viz_distinctive_words(df):
    """
    For each account, find the words it uses proportionally MORE than
    all other accounts combined (log-odds ratio). Shows what each
    account 'sounds like' vs. the others.
    """
    print("[viz] distinctive words per account ...")
    from sklearn.feature_extraction.text import CountVectorizer

    accounts = sorted(df["handle"].unique())
    # Build one corpus per account
    corpora = {}
    for acct in accounts:
        texts = df[df["handle"] == acct]["text"].tolist()
        corpora[acct] = " ".join(texts)

    vec = CountVectorizer(
        ngram_range=(1, 2), max_features=8000,
        token_pattern=r"(?u)\b[a-zA-ZáéíóúüñÁÉÍÓÚÜÑ]{3,}\b",
        min_df=2,
    )
    mat = vec.fit_transform(list(corpora.values())).toarray().astype(float)
    vocab = vec.get_feature_names_out()

    # Smoothed log-odds: for each account, log(p_acct / p_others)
    eps = 0.5
    fig = make_subplots(rows=1, cols=len(accounts),
                        subplot_titles=accounts)
    for i, acct in enumerate(accounts):
        acct_counts  = mat[i] + eps
        other_counts = mat.sum(axis=0) - mat[i] + eps
        log_odds = np.log(acct_counts / acct_counts.sum()) \
                 - np.log(other_counts / other_counts.sum())
        top_idx  = log_odds.argsort()[-20:][::-1]
        top_words  = [vocab[j] for j in top_idx][::-1]
        top_scores = [log_odds[j] for j in top_idx][::-1]

        fig.add_trace(go.Bar(
            x=top_scores, y=top_words,
            orientation="h",
            marker_color=ACCOUNT_COLORS.get(acct, "#888"),
            showlegend=False,
        ), row=1, col=i+1)

    fig.update_layout(
        title="Most distinctive words per account (log-odds vs. all others)",
        height=600, margin=dict(l=10, r=10),
    )
    fig.update_xaxes(title_text="log-odds", title_font_size=9)

    path = os.path.join(OUTPUT_DIR, "viz_distinctive_words.html")
    fig.write_html(path)
    print(f"  -> {path}")


# ─────────────────────────────────────────────
# CSV EXPORT
# ─────────────────────────────────────────────
def save_csv(monthly):
    path = os.path.join(OUTPUT_DIR, "rhetoric_metrics.csv")
    monthly.to_csv(path, index=False)
    print(f"[csv] {path} ({len(monthly):,} rows)")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print("=" * 65)
    print("El Salvador — Rhetorical & Thematic Analysis")
    print("=" * 65)

    df      = load()
    monthly = compute_metrics(df)

    save_csv(monthly)
    viz_themes(monthly)
    viz_rhetoric(monthly)
    viz_bukele(monthly)
    viz_event_windows(df)
    viz_distinctive_words(df)

    print("\n" + "=" * 65)
    print("Done. Open these files:")
    print("  output/rhetoric/viz_themes.html          — thematic discourse trends")
    print("  output/rhetoric/viz_rhetoric_per_account.html — caps/exclaim/I-lang")
    print("  output/rhetoric/viz_bukele_shift.html    — Bukele escalation")
    print("  output/rhetoric/viz_event_windows.html   — before/after each event")
    print("  output/rhetoric/viz_distinctive_words.html — each account's vocabulary")


if __name__ == "__main__":
    main()
