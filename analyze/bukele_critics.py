"""
bukele_critics.py — How Bukele responds to international criticism

Analyses @nayibbukele tweets (non-RT, non-quote) for rhetoric aimed at:
  - Human rights organizations (CIDH, Amnesty, HRW, etc.)
  - International bodies (ONU, OEA)
  - Foreign governments / US officials
  - NGO/media delegitimization ("periodistas pagados", Open Society/Soros)
  - Reframing criticism as criminal sympathy

NOTE: This dataset excludes retweets and quote-tweets by design (cost savings
during collection). Many of Bukele's most direct attacks appear in quote-tweets,
so counts here are a lower bound. The rhetorical patterns visible in the ~236
matching tweets are consistent and clear enough to analyze.

OUTPUTS (output/bukele_critics/):
  viz_volume_over_time.html    — monthly volume of critic-targeting tweets
  viz_targets.html             — which entities get attacked most
  viz_strategies.html          — rhetorical strategies used over time
  viz_examples.html            — quoted tweet text for each strategy
  critic_tweets.csv            — all matching tweets tagged with category/strategy
"""

import os
import re
import csv
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from collections import Counter, defaultdict

INPUT_CSV  = os.path.join("output", "data", "tweets.csv")
OUTPUT_DIR = os.path.join("output", "bukele_critics")

# ─────────────────────────────────────────────
# TARGET ENTITIES — who Bukele is responding to
# ─────────────────────────────────────────────
TARGETS = {
    "CIDH / IACHR": [
        r"\bcidh\b", r"\biachr\b", r"comisión interamericana",
        r"comision interamericana", r"\bvivanco\b",
    ],
    "OEA / OAS": [
        r"\boea\b", r"\boas\b", r"organización de estados",
        r"ministerio de colonias",   # his own label for the OEA
    ],
    "ONU / UN": [
        r"\bonu\b", r"naciones unidas", r"\bunesco\b", r"\bunicef\b",
        r"expertos de la onu", r"relatora",
    ],
    "Amnesty / HRW": [
        r"amnist", r"\bhrw\b", r"human rights watch",
        r"@amnesty",
    ],
    "Open Society / Soros": [
        r"open society", r"\bsoros\b",
    ],
    "NGOs (generic)": [
        r"\bong\b", r"\bngo\b", r"ong pagada", r"ngo pagada",
        r"organizaciones de.{0,20}derechos", r"defensores de.{0,20}derechos",
    ],
    "US Government": [
        r"estados unidos", r"\beeuu\b", r"\bwashington\b",
        r"\bbiden\b", r"\btrump\b", r"departamento de estado",
        r"state department", r"\bcongress\b", r"congreso de ee",
        r"\bsenate\b", r"\bsenado\b",
    ],
    "International media": [
        r"the guardian", r"france 24", r"el país", r"el pais",
        r"periodistas.{0,30}pagad", r"medios.{0,20}open society",
        r"activistas.{0,20}pagad",
    ],
    '"Comunidad Internacional"': [
        r"comunidad internacional",
    ],
}

# ─────────────────────────────────────────────
# RHETORICAL STRATEGIES
# ─────────────────────────────────────────────
STRATEGIES = {
    "Scare quotes": [
        # Uses quotes to mock/undermine legitimacy of the term
        r'["""]derechos humanos["""]',
        r'["""]human rights["""]',
        r'["""]periodistas["""]',
        r'["""]expertos["""]',
        r'["""]defensores["""]',
        r'["""]dictad',
        r'["""]democracia["""]',
        r'["""]régimen["""]',
        r'["""]regimen["""]',
    ],
    "NGO delegitimization": [
        # Links HR orgs to financial corruption / foreign control
        r"pagad[oa]s? por", r"financiad[oa]s? por", r"financiamiento",
        r"open society", r"\bsoros\b", r"agenda[s]?\b",
        r"intereses.{0,30}(extranjero|político)",
    ],
    "Criminal sympathy framing": [
        # Accuses critics of siding with gangs
        r"defiendes? (a )?los pandilleros",
        r"socios de los pandilleros",
        r"defiend.{0,20}pandill",
        r"protect.{0,20}(pandill|criminal|terroris)",
        r"del lado de los",
        r"apoy.{0,20}(pandill|criminal|terroris)",
        r"no.{0,5}(les|te) importa.{0,30}(víctima|victima|muerto|asesinado)",
    ],
    "Double standard / hypocrisy": [
        # Points out critics don't apply same standards elsewhere
        r"¿[Oo] solo aplica",
        r"doble (rasero|estándar|estandar)",
        r"por qué no (condena|critica)",
        r"cuando (pasa|ocurre|sucede).{0,30}en (ee\.?uu|estados unidos|europa|otro)",
        r"no dijeron nada cuando",
        r"dónde estaban",
        r"¿[Yy] (en|sobre) .{0,20}\?",
    ],
    "Whataboutism (crime stats)": [
        # Deflects by pointing to crime reduction achievements
        r"(antes|cuando|recuerdan).{0,40}(homicidio|asesinato|muerto|pandill)",
        r"(sin|0|cero).{0,15}(homicidio|muerto|asesinato)",
        r"pa[íi]s (m[aá]s seguro|en paz|sin pandill)",
        r"tasa de homicidios",
        r"rentable para las ong",
    ],
    "Colonial / sovereignty framing": [
        # Frames criticism as foreign interference / neo-colonialism
        r"ministerio de colonias",
        r"injerencia", r"soberan[íi]a",
        r"(no|nadie).{0,20}(va a|puede).{0,20}(decidir|ordenar|mandar)",
        r"(nuestro|este).{0,15}pa[íi]s.{0,20}(nuestro|nosotros|soberanos)",
        r"se atreven.{0,30}(decir|criticar|juzgar)",
    ],
    "Mockery / ridicule": [
        # Sarcasm, dismissal, jokes at critics' expense
        r"me imagino que (ya|ahora) (saldrán|condenarán|dirán)",
        r"(jaja|😂|🤣|😅)",
        r"[Rr]ídículo", r"ridículo", r"absurdo",
        r"qué gracioso", r"esto es lo que",
    ],
}

KEY_EVENTS = [
    ("2019-06-01", "Bukele inaugurated"),
    ("2020-02-09", "Military enters Assembly"),
    ("2020-03-21", "COVID emergency"),
    ("2021-05-01", "Assembly fires CSJ+FGR"),
    ("2021-09-07", "Bitcoin legal tender"),
    ("2022-03-27", "Régimen de Excepción"),
    ("2023-11-01", "CECOT opens"),
    ("2024-02-04", "Bukele re-elected"),
]


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def match_patterns(text, pattern_dict):
    """Return list of keys whose patterns match text."""
    t = text.lower()
    matched = []
    for key, patterns in pattern_dict.items():
        for pat in patterns:
            if re.search(pat, t, re.IGNORECASE):
                matched.append(key)
                break
    return matched


def add_events(fig, row=None, col=None):
    for dt_str, label in KEY_EVENTS:
        dt = pd.Timestamp(dt_str)
        kwargs = {"row": row, "col": col} if row else {}
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


def wrap(text, width=90):
    """Wrap long text for display in Plotly."""
    words = text.split()
    lines, line = [], []
    for w in words:
        if sum(len(x)+1 for x in line) + len(w) > width:
            lines.append(" ".join(line))
            line = [w]
        else:
            line.append(w)
    if line:
        lines.append(" ".join(line))
    return "<br>".join(lines)


# ─────────────────────────────────────────────
# LOAD + TAG
# ─────────────────────────────────────────────
def load_and_tag():
    print("[load] Reading tweets and tagging ...")
    rows = []
    with open(INPUT_CSV, encoding="utf-8-sig", errors="replace") as f:
        for r in csv.DictReader(f):
            if r.get("handle", "").lower() != "nayibbukele":
                continue
            text = r.get("text", "")
            targets    = match_patterns(text, TARGETS)
            strategies = match_patterns(text, STRATEGIES)
            if targets or strategies:
                r["targets"]    = "|".join(targets)
                r["strategies"] = "|".join(strategies)
                rows.append(r)

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df[df["date"].notna()].copy()
    df["ym"] = df["date"].dt.to_period("M").dt.to_timestamp()
    df["year"] = df["date"].dt.year
    print(f"[load] {len(df):,} tweets match target/strategy patterns")
    return df


# ─────────────────────────────────────────────
# VIZ 1: Volume over time
# ─────────────────────────────────────────────
def viz_volume(df):
    print("[viz] volume over time ...")
    monthly = df.groupby("ym").size().reset_index(name="n")
    total = df.groupby("ym").size()  # for % calculation

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=monthly["ym"], y=monthly["n"],
        name="Tweets targeting critics",
        marker_color="#d62728", opacity=0.8,
    ))

    add_events(fig)
    fig.update_layout(
        title=("@nayibbukele — Tweets targeting international critics / HR orgs (monthly)<br>"
               "<sup>Non-RT, non-quote tweets only — quote-tweets (excluded from dataset) "
               "would add more</sup>"),
        xaxis_title="", yaxis_title="Number of tweets",
        height=440, hovermode="x unified",
    )
    path = os.path.join(OUTPUT_DIR, "viz_volume_over_time.html")
    fig.write_html(path)
    print(f"  -> {path}")


# ─────────────────────────────────────────────
# VIZ 2: Target breakdown
# ─────────────────────────────────────────────
def viz_targets(df):
    print("[viz] targets ...")
    counts = Counter()
    for targets in df["targets"]:
        for t in targets.split("|"):
            if t:
                counts[t] += 1

    tdf = pd.DataFrame(counts.most_common(), columns=["target", "n"])

    fig = go.Figure(go.Bar(
        x=tdf["n"], y=tdf["target"],
        orientation="h",
        marker_color=px.colors.qualitative.Set2[:len(tdf)],
        text=tdf["n"], textposition="outside",
    ))
    fig.update_layout(
        title=("Most-targeted entities in Bukele's critic-response tweets<br>"
               "<sup>\"NGOs (generic)\" includes any tweet mentioning ONG/NGO "
               "in a critical context</sup>"),
        xaxis_title="Tweet count",
        yaxis=dict(autorange="reversed"),
        height=420,
        margin=dict(l=200),
    )
    path = os.path.join(OUTPUT_DIR, "viz_targets.html")
    fig.write_html(path)
    print(f"  -> {path}")


# ─────────────────────────────────────────────
# VIZ 3: Rhetorical strategies over time
# ─────────────────────────────────────────────
def viz_strategies(df):
    print("[viz] strategies over time ...")
    # Expand strategies column into one row per strategy
    strat_rows = []
    for _, row in df.iterrows():
        for s in row["strategies"].split("|"):
            if s:
                strat_rows.append({"ym": row["ym"], "strategy": s})
    if not strat_rows:
        print("  (no strategy matches found)")
        return

    sdf = pd.DataFrame(strat_rows)
    pivot = sdf.groupby(["ym","strategy"]).size().unstack(fill_value=0)

    colors = px.colors.qualitative.Safe
    fig = go.Figure()
    for i, col in enumerate(pivot.columns):
        fig.add_trace(go.Bar(
            x=pivot.index, y=pivot[col],
            name=col,
            marker_color=colors[i % len(colors)],
        ))

    add_events(fig)
    fig.update_layout(
        title="Rhetorical strategies in Bukele's critic-targeting tweets (monthly)",
        barmode="stack",
        xaxis_title="", yaxis_title="Tweet count",
        height=500, hovermode="x unified",
        legend=dict(font_size=9, orientation="h", y=-0.3),
    )
    path = os.path.join(OUTPUT_DIR, "viz_strategies.html")
    fig.write_html(path)
    print(f"  -> {path}")


# ─────────────────────────────────────────────
# VIZ 4: Example tweets per strategy
# ─────────────────────────────────────────────
def viz_examples(df):
    print("[viz] example tweets per strategy ...")
    strat_examples = defaultdict(list)
    for _, row in df.iterrows():
        for s in row["strategies"].split("|"):
            if s:
                strat_examples[s].append((row["date"], row["text"]))

    if not strat_examples:
        print("  (no examples)")
        return

    strategies_found = sorted(strat_examples.keys())
    n = len(strategies_found)
    fig = make_subplots(
        rows=n, cols=1,
        subplot_titles=strategies_found,
        vertical_spacing=0.04,
    )
    # Invisible scatter traces — we use annotations for the text
    for i, strategy in enumerate(strategies_found):
        examples = sorted(strat_examples[strategy], key=lambda x: x[0])
        # Pick 3 most illustrative (spread across timeline)
        if len(examples) <= 3:
            picks = examples
        else:
            idxs = [0, len(examples)//2, -1]
            picks = [examples[j] for j in idxs]

        y_positions = list(range(len(picks), 0, -1))
        for (dt, text), y in zip(picks, y_positions):
            short = wrap(text[:400] + ("…" if len(text)>400 else ""), 100)
            fig.add_trace(go.Scatter(
                x=[dt], y=[y],
                mode="markers",
                marker=dict(size=10, color="#d62728"),
                text=f"<b>{dt.strftime('%Y-%m-%d')}</b><br>{short}",
                hovertemplate="%{text}<extra></extra>",
                showlegend=False,
            ), row=i+1, col=1)

        fig.update_yaxes(showticklabels=False, showgrid=False, row=i+1, col=1)
        fig.update_xaxes(showgrid=False, row=i+1, col=1)

    fig.update_layout(
        title="Example tweets by rhetorical strategy (hover to read)",
        height=220 * n,
        margin=dict(l=20, r=20),
    )
    path = os.path.join(OUTPUT_DIR, "viz_examples.html")
    fig.write_html(path)
    print(f"  -> {path}")


# ─────────────────────────────────────────────
# VIZ 5: Strategies × Targets heatmap
# ─────────────────────────────────────────────
def viz_strategy_target_heatmap(df):
    print("[viz] strategy × target heatmap ...")
    MAX_HOVER_TWEETS = 5   # tweets shown per cell on hover
    PREVIEW_CHARS    = 130 # characters per tweet preview

    rows_exp = []
    for _, row in df.iterrows():
        for t in row["targets"].split("|"):
            for s in row["strategies"].split("|"):
                if t and s:
                    rows_exp.append({
                        "target":   t,
                        "strategy": s,
                        "text":     row["text"],
                        "date":     str(row["date"])[:10] if pd.notna(row["date"]) else "",
                        "likes":    row.get("likes", 0),
                    })
    if not rows_exp:
        return

    cross    = pd.DataFrame(rows_exp)
    pivot    = cross.groupby(["strategy", "target"]).size().unstack(fill_value=0)
    strategies = list(pivot.index)
    targets    = list(pivot.columns)

    # Build customdata: 2-D list matching pivot shape.
    # Each cell holds a pre-formatted HTML string with the top tweets.
    hover_texts = []
    for strat in strategies:
        row_texts = []
        for targ in targets:
            mask   = (cross["strategy"] == strat) & (cross["target"] == targ)
            subset = cross[mask].sort_values("likes", ascending=False)
            if subset.empty:
                row_texts.append("(no tweets)")
            else:
                lines = []
                for _, r in subset.head(MAX_HOVER_TWEETS).iterrows():
                    preview = r["text"][:PREVIEW_CHARS]
                    if len(r["text"]) > PREVIEW_CHARS:
                        preview += "…"
                    # escape angle brackets so Plotly renders the text safely
                    preview = preview.replace("<", "&lt;").replace(">", "&gt;")
                    lines.append(f"• [{r['date']}] {preview}")
                extra = len(subset) - MAX_HOVER_TWEETS
                if extra > 0:
                    lines.append(f"  <i>… and {extra} more</i>")
                row_texts.append("<br>".join(lines))
        hover_texts.append(row_texts)

    fig = go.Figure(go.Heatmap(
        z=pivot.values,
        x=targets,
        y=strategies,
        colorscale="Reds",
        text=pivot.values,
        texttemplate="%{text}",
        customdata=hover_texts,
        hovertemplate=(
            "<b>%{y}</b>  →  <b>%{x}</b><br>"
            "Count: %{z}<br><br>"
            "%{customdata}"
            "<extra></extra>"
        ),
        colorbar=dict(title="# tweets"),
    ))
    fig.update_layout(
        title="Which rhetoric strategies does Bukele use against which targets?",
        height=500,
        margin=dict(l=220, b=180),
        xaxis=dict(tickangle=-40, tickfont_size=10),
        yaxis=dict(tickfont_size=10),
        hoverlabel=dict(
            bgcolor="white",
            font_size=12,
            font_family="monospace",
            namelength=-1,
        ),
    )
    path = os.path.join(OUTPUT_DIR, "viz_strategy_target_heatmap.html")
    fig.write_html(path)
    print(f"  -> {path}")


# ─────────────────────────────────────────────
# CSV EXPORT
# ─────────────────────────────────────────────
def save_csv(df):
    out = df[["tweet_id","date","text","likes","retweets","targets","strategies"]].copy()
    path = os.path.join(OUTPUT_DIR, "critic_tweets.csv")
    out.to_csv(path, index=False)
    print(f"[csv] {path} ({len(out):,} rows)")


# ─────────────────────────────────────────────
# TERMINAL SUMMARY
# ─────────────────────────────────────────────
def print_summary(df):
    print("\n" + "="*65)
    print("SUMMARY")
    print("="*65)

    print(f"\n{len(df):,} tweets match critic-targeting patterns")
    print(f"({len(df)/6931*100:.1f}% of all Bukele tweets in dataset)\n")

    # Top targets
    target_counts = Counter()
    for t in df["targets"]:
        for x in t.split("|"):
            if x: target_counts[x] += 1
    print("Top targets:")
    for t, n in target_counts.most_common(8):
        print(f"  {t:40s} {n:3d}")

    # Top strategies
    strat_counts = Counter()
    for s in df["strategies"]:
        for x in s.split("|"):
            if x: strat_counts[x] += 1
    print("\nTop rhetorical strategies:")
    for s, n in strat_counts.most_common():
        print(f"  {s:40s} {n:3d}")

    # Most engaged critic-targeting tweets
    df["likes_int"] = pd.to_numeric(df["likes"], errors="coerce").fillna(0)
    top = df.nlargest(5, "likes_int")[["date","likes_int","text"]]
    print("\nMost-liked critic-targeting tweets:")
    for _, r in top.iterrows():
        print(f"  [{r['date'].strftime('%Y-%m-%d')}] {int(r['likes_int']):,} likes")
        print(f"  {r['text'][:200]}")
        print()

    print("IMPORTANT NOTE: This dataset excludes retweets and quote-tweets.")
    print("Bukele's most direct attacks on critics are often quote-tweets,")
    print("so these ~236 tweets are a lower bound. The patterns are consistent:")
    print("  1. Scare quotes undermine legitimacy of the 'human rights' label")
    print("  2. Links HR orgs to Open Society/Soros funding (delegitimization)")
    print("  3. Frames all critics as 'defenders of pandilleros'")
    print("  4. Claims double standard: 'why doesn't CIDH condemn X?'")
    print("  5. Frames international pressure as neo-colonial interference")
    print("  6. OEA is 'el Ministerio de Colonias de Washington'")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print("="*65)
    print("Bukele Critic-Response Rhetoric Analysis")
    print("="*65)

    df = load_and_tag()
    if len(df) == 0:
        print("No matching tweets found.")
        return

    save_csv(df)
    viz_volume(df)
    viz_targets(df)
    viz_strategies(df)
    viz_examples(df)
    viz_strategy_target_heatmap(df)
    print_summary(df)

    print(f"\nOpen output/bukele_critics/viz_strategies.html for the overview.")
    print(f"Open output/bukele_critics/viz_examples.html to read actual tweets.")


if __name__ == "__main__":
    main()
