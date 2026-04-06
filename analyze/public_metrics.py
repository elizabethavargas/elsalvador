"""
public_metrics.py — Freedom House scores + Bukele approval ratings overlaid
against the tweet rhetoric and article data.

OUTPUTS (output/public_metrics/):
  viz_democracy_vs_approval.html   — the central paradox: FH score declining
                                     while approval stays 80-96%
  viz_fh_subscores.html            — which specific FH dimensions collapsed
                                     (judicial independence, corruption safeguards)
  viz_approval_timeline.html       — all approval polls on one timeline with
                                     key events annotated
  viz_crackdown_support.html       — gang crackdown support vs. civil liberties score
  viz_combined_dashboard.html      — FH score + approval + rhetoric metrics
                                     (confrontation language from tweets) on one chart
  public_metrics.csv               — clean annual/monthly table for further stats

SOURCES:
  Freedom House Freedom in the World reports 2017-2024
    https://freedomhouse.org/country/el-salvador/freedom-world/{year}
  Approval ratings compiled from CID Gallup, TResearch, LPG Datos, IUDOP,
    Funda Ungo, CIESCA — via Wikipedia polling page and elsalvadorinfo.net
"""

import os
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

OUTPUT_DIR = os.path.join("output", "public_metrics")

# ─────────────────────────────────────────────
# HARDCODED DATA (scraped from Freedom House + polling aggregators)
# ─────────────────────────────────────────────

# Freedom House Freedom in the World — El Salvador
# Overall score /100, political rights /40, civil liberties /60
FREEDOM_HOUSE = {
    2017: {"overall": 70, "status": "Free",         "pol_rights": 34, "civil_lib": 36},
    2018: {"overall": 70, "status": "Free",         "pol_rights": 34, "civil_lib": 36},
    2019: {"overall": 67, "status": "Free",         "pol_rights": 32, "civil_lib": 35},
    2020: {"overall": 66, "status": "Partly Free",  "pol_rights": 32, "civil_lib": 34},
    2021: {"overall": 63, "status": "Partly Free",  "pol_rights": 30, "civil_lib": 33},
    2022: {"overall": 59, "status": "Partly Free",  "pol_rights": 26, "civil_lib": 33},
    2023: {"overall": 56, "status": "Partly Free",  "pol_rights": 25, "civil_lib": 31},
    2024: {"overall": 53, "status": "Partly Free",  "pol_rights": 21, "civil_lib": 32},
}

# Sub-category scores (each question is 0-4)
# A=Electoral Process  B=Political Pluralism  C=Functioning of Government
# D=Freedom of Expression  E=Associational Rights  F=Rule of Law  G=Personal Autonomy
FH_QUESTIONS = {
    2019: {"A1":4,"A2":3,"A3":4, "B1":4,"B2":4,"B3":2,"B4":3,
           "C1":3,"C2":2,"C3":3, "D1":2,"D2":4,"D3":3,"D4":3,
           "E1":3,"E2":3,"E3":2, "F1":2,"F2":2,"F3":1,"F4":2,
           "G1":2,"G2":2,"G3":2,"G4":2},
    2020: {"A1":4,"A2":3,"A3":4, "B1":4,"B2":4,"B3":2,"B4":3,
           "C1":3,"C2":2,"C3":3, "D1":2,"D2":3,"D3":3,"D4":3,
           "E1":3,"E2":3,"E3":2, "F1":2,"F2":2,"F3":1,"F4":2,
           "G1":2,"G2":2,"G3":2,"G4":2},
    2021: {"A1":4,"A2":3,"A3":4, "B1":4,"B2":4,"B3":2,"B4":3,
           "C1":2,"C2":2,"C3":2, "D1":2,"D2":3,"D3":3,"D4":3,
           "E1":3,"E2":3,"E3":2, "F1":2,"F2":2,"F3":1,"F4":2,
           "G1":1,"G2":2,"G3":2,"G4":2},
    2022: {"A1":4,"A2":3,"A3":3, "B1":3,"B2":4,"B3":2,"B4":3,
           "C1":2,"C2":1,"C3":1, "D1":2,"D2":3,"D3":3,"D4":3,
           "E1":3,"E2":3,"E3":2, "F1":1,"F2":1,"F3":2,"F4":2,
           "G1":2,"G2":2,"G3":2,"G4":2},
    2023: {"A1":4,"A2":3,"A3":3, "B1":3,"B2":4,"B3":2,"B4":3,
           "C1":2,"C2":0,"C3":1, "D1":2,"D2":4,"D3":3,"D4":2,
           "E1":3,"E2":2,"E3":2, "F1":0,"F2":0,"F3":2,"F4":2,
           "G1":3,"G2":2,"G3":2,"G4":2},
    2024: {"A1":4,"A2":3,"A3":2, "B1":2,"B2":3,"B3":2,"B4":3,
           "C1":2,"C2":0,"C3":0, "D1":2,"D2":4,"D3":3,"D4":2,
           "E1":3,"E2":2,"E3":2, "F1":0,"F2":0,"F3":2,"F4":2,
           "G1":3,"G2":3,"G3":2,"G4":2},
}

QUESTION_LABELS = {
    "A1": "Free/fair presidential elections",
    "A2": "Free/fair legislative elections",
    "A3": "Fair electoral framework",
    "B1": "Right to organize parties",
    "B2": "Opposition can gain power",
    "B3": "Choices free from domination",
    "B4": "Equal political rights",
    "C1": "Elected officials determine policy",
    "C2": "Safeguards against corruption",
    "C3": "Government transparency",
    "D1": "Free and independent media",
    "D2": "Religious freedom",
    "D3": "Academic freedom",
    "D4": "Personal expression without fear",
    "E1": "Freedom of assembly",
    "E2": "NGO freedom",
    "E3": "Trade union freedom",
    "F1": "Independent judiciary",
    "F2": "Due process of law",
    "F3": "Protection from physical force",
    "F4": "Equal treatment under law",
    "G1": "Freedom of movement",
    "G2": "Property rights",
    "G3": "Personal social freedoms",
    "G4": "Freedom from exploitation",
}

CATEGORY_QUESTIONS = {
    "A Electoral Process":          ["A1","A2","A3"],
    "B Political Pluralism":        ["B1","B2","B3","B4"],
    "C Government Functioning":     ["C1","C2","C3"],
    "D Freedom of Expression":      ["D1","D2","D3","D4"],
    "E Associational Rights":       ["E1","E2","E3"],
    "F Rule of Law":                ["F1","F2","F3","F4"],
    "G Personal Autonomy":          ["G1","G2","G3","G4"],
}

# Approval ratings (date, approval %, disapproval %, organization)
APPROVAL_POLLS = [
    ("2019-09", 90.4,  0.4, "LPG Datos"),
    ("2020-02", 85.9, 10.4, "LPG Datos"),
    ("2020-05", 92.5,  5.4, "LPG Datos"),
    ("2020-11", 96.0, None, "CID Gallup"),
    ("2020-12", 89.0, 10.0, "CID Gallup"),
    ("2021-03", 96.0,  3.0, "CID Gallup"),
    ("2021-05", 86.5,  9.1, "LPG Datos"),
    ("2021-05", 94.0,  6.0, "CIESCA"),
    ("2021-08", 84.7, 12.3, "LPG Datos"),
    ("2021-08", 87.0, 11.0, "CID Gallup"),
    ("2021-11", 85.1, 11.7, "LPG Datos"),
    ("2021-12", 84.5, 10.1, "Funda Ungo"),
    ("2022-01", 84.0, 12.0, "CID Gallup"),
    ("2022-05", 91.6,  3.2, "CIESCA"),
    ("2022-06", 80.7, 10.9, "TResearch"),
    ("2022-06", 89.0,  6.7, "Funda Ungo"),
    ("2022-07", 82.7,  8.9, "TResearch"),
    ("2022-08", 83.8,  8.1, "TResearch"),
    ("2022-09", 82.0, 13.2, "TResearch"),
    ("2022-10", 83.7, 12.0, "TResearch"),
    ("2022-11", 81.6, 13.9, "TResearch"),
    ("2022-11", 87.8,  9.5, "LPG Datos"),
    ("2022-12", 80.1, 14.8, "TResearch"),
    ("2023-01", 84.8, 11.5, "TResearch"),
    ("2023-01", 90.0,  4.0, "CID Gallup"),
    ("2023-02", 87.6, 10.1, "TResearch"),
    ("2023-02", 91.0,  6.9, "LPG Datos"),
    ("2023-03", 89.2,  9.2, "TResearch"),
    ("2023-04", 90.7,  7.0, "TResearch"),
    ("2023-05", 90.0,  7.0, "CID Gallup"),
    ("2023-05", 91.5,  7.2, "TResearch"),
    ("2023-06", 92.9,  5.3, "TResearch"),
    ("2023-09", 90.0,  5.0, "CID Gallup"),
    ("2023-11", 92.0,  6.0, "CID Gallup"),
    ("2024-01", 92.0,  5.0, "CID Gallup"),
    ("2024-05", 92.0,  6.0, "CID Gallup"),
    ("2024-09", 89.0,  4.0, "CID Gallup"),
    ("2024-11", 91.0,  6.0, "CID Gallup"),
    ("2025-05", 85.2, 10.8, "LPG Datos"),
]

# Gang crackdown / Estado de Excepcion support
CRACKDOWN_SUPPORT = [
    ("2022-05", 90.1,  7.1, "CIESCA"),
    ("2022-09", 75.9, None, "UCA"),
    ("2022-09", 91.0,  6.0, "CID Gallup"),
    ("2023-02", 92.0, None, "CID Gallup"),
    ("2023-06", 92.4,  5.1, "TResearch"),
    ("2023-09", 84.0, 12.0, "CID Gallup"),
    ("2024-01", 88.0,  8.0, "CID Gallup"),
    ("2024-09", 83.0, 12.0, "CID Gallup"),
]

KEY_EVENTS = [
    ("2019-06-01", "Bukele inaugurated"),
    ("2020-02-09", "Military enters Assembly"),
    ("2020-03-21", "COVID emergency"),
    ("2021-05-01", "Assembly fires CSJ + FGR"),
    ("2021-09-07", "Bitcoin legal tender"),
    ("2022-03-27", "Régimen de Excepción"),
    ("2023-11-01", "CECOT opens"),
    ("2024-02-04", "Bukele re-elected"),
]


def add_events(fig, rows=None, cols=None):
    for dt_str, label in KEY_EVENTS:
        dt = pd.Timestamp(dt_str)
        kwargs = {}
        if rows and cols:
            for r, c in zip(rows, cols):
                fig.add_vline(x=dt.timestamp()*1000, line_width=1, line_dash="dot",
                              line_color="rgba(60,60,60,0.35)",
                              annotation_text=label, annotation_font_size=7,
                              annotation_position="top left", row=r, col=c)
        else:
            fig.add_vline(x=dt.timestamp()*1000, line_width=1.2, line_dash="dot",
                          line_color="rgba(60,60,60,0.4)",
                          annotation_text=label, annotation_font_size=8,
                          annotation_position="top left")
    return fig


# ─────────────────────────────────────────────
# BUILD DATAFRAMES
# ─────────────────────────────────────────────
def build_fh_df():
    rows = []
    for year, d in FREEDOM_HOUSE.items():
        rows.append({"year": year, "date": pd.Timestamp(f"{year}-01-01"), **d})
    return pd.DataFrame(rows)


def build_approval_df():
    rows = []
    for ym, approval, disapproval, org in APPROVAL_POLLS:
        rows.append({
            "date": pd.Timestamp(ym + "-01"),
            "approval": approval,
            "disapproval": disapproval,
            "org": org,
        })
    df = pd.DataFrame(rows).sort_values("date")
    # Monthly median across all pollsters
    df["ym"] = df["date"].dt.to_period("M").dt.to_timestamp()
    return df


def build_crackdown_df():
    rows = []
    for ym, support, oppose, org in CRACKDOWN_SUPPORT:
        rows.append({
            "date": pd.Timestamp(ym + "-01"),
            "support": support,
            "oppose": oppose,
            "org": org,
        })
    return pd.DataFrame(rows).sort_values("date")


def build_subscore_df():
    rows = []
    for year, qs in FH_QUESTIONS.items():
        row = {"year": year, "date": pd.Timestamp(f"{year}-01-01")}
        for cat, qlist in CATEGORY_QUESTIONS.items():
            cat_key = cat.split()[0]  # "A", "B", etc.
            scores = [qs.get(q, None) for q in qlist]
            scores = [s for s in scores if s is not None]
            row[f"cat_{cat_key}"] = sum(scores)
            row[f"cat_{cat_key}_max"] = len(qlist) * 4
            row[f"cat_{cat_key}_pct"] = sum(scores) / (len(qlist) * 4) * 100
            # Individual questions
            for q in qlist:
                row[q] = qs.get(q, None)
        rows.append(row)
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────
# VIZ 1: The Central Paradox
# ─────────────────────────────────────────────
def viz_democracy_vs_approval(fh_df, approval_df):
    print("[viz] democracy vs approval paradox ...")
    monthly_approval = (approval_df.groupby("ym")["approval"]
                        .median().reset_index().rename(columns={"ym": "date"}))

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # Approval (right axis)
    fig.add_trace(go.Scatter(
        x=monthly_approval["date"], y=monthly_approval["approval"],
        name="Bukele approval % (median polls)",
        mode="lines+markers", marker_size=5,
        line=dict(color="#d62728", width=2),
    ), secondary_y=True)

    # Freedom House overall (left axis) — step line since it's annual
    fig.add_trace(go.Scatter(
        x=fh_df["date"], y=fh_df["overall"],
        name="Freedom House score (/100)",
        mode="lines+markers", marker_size=8,
        line=dict(color="#1f77b4", width=3, shape="hv"),
        text=fh_df["status"],
        hovertemplate="%{y}/100 — %{text}<extra>Freedom House</extra>",
    ), secondary_y=False)

    # Shade "Free" vs "Partly Free" zones
    fig.add_hrect(y0=60, y1=100, line_width=0,
                  fillcolor="rgba(0,180,0,0.05)", secondary_y=False)
    fig.add_hrect(y0=0, y1=60, line_width=0,
                  fillcolor="rgba(255,140,0,0.07)", secondary_y=False)
    fig.add_annotation(x="2017-06-01", y=95, text="FREE", font_size=9,
                       font_color="green", showarrow=False)
    fig.add_annotation(x="2020-06-01", y=55, text="PARTLY FREE", font_size=9,
                       font_color="orange", showarrow=False)

    add_events(fig)
    fig.update_yaxes(title_text="Freedom House score (/100)", range=[40, 100],
                     secondary_y=False)
    fig.update_yaxes(title_text="Approval rating (%)", range=[60, 100],
                     secondary_y=True)
    fig.update_layout(
        title=("El Salvador: Democratic Decline vs. Presidential Approval (2017–2025)<br>"
               "<sup>Freedom House score falls 17 points while approval stays above 80% — the authoritarian popularity paradox</sup>"),
        xaxis_title="",
        hovermode="x unified",
        height=520,
        legend=dict(x=0.01, y=0.15),
    )
    path = os.path.join(OUTPUT_DIR, "viz_democracy_vs_approval.html")
    fig.write_html(path)
    print(f"  -> {path}")


# ─────────────────────────────────────────────
# VIZ 2: FH Sub-score breakdown
# ─────────────────────────────────────────────
def viz_fh_subscores(fh_df, sub_df):
    print("[viz] FH sub-scores ...")
    cat_cols = ["cat_A_pct","cat_B_pct","cat_C_pct","cat_D_pct",
                "cat_E_pct","cat_F_pct","cat_G_pct"]
    cat_names = ["A Electoral Process","B Political Pluralism",
                 "C Gov. Functioning","D Free Expression",
                 "E Assoc. Rights","F Rule of Law","G Personal Autonomy"]
    colors = px.colors.qualitative.Safe

    fig = go.Figure()
    # Overall score on secondary axis
    fig.add_trace(go.Scatter(
        x=fh_df["date"], y=fh_df["overall"],
        name="Overall score (/100)",
        mode="lines+markers", marker_size=7,
        line=dict(color="black", width=2.5, dash="dash"),
        yaxis="y2",
    ))

    for col, name, color in zip(cat_cols, cat_names, colors):
        if col not in sub_df.columns:
            continue
        fig.add_trace(go.Scatter(
            x=sub_df["date"], y=sub_df[col],
            name=name, mode="lines+markers",
            line=dict(color=color, width=1.8),
            marker_size=6,
        ))

    add_events(fig)
    fig.update_layout(
        title=("Freedom House Sub-scores: Where Democratic Backsliding Hit Hardest<br>"
               "<sup>C (Government Functioning) and F (Rule of Law) collapsed; "
               "A (Elections) stayed relatively stable</sup>"),
        yaxis=dict(title="Category score (% of max)", range=[0, 105]),
        yaxis2=dict(title="Overall score (/100)", range=[0, 105],
                    overlaying="y", side="right", showgrid=False),
        xaxis_title="",
        height=560,
        hovermode="x unified",
        legend=dict(font_size=9, x=1.05, y=1),
    )
    path = os.path.join(OUTPUT_DIR, "viz_fh_subscores.html")
    fig.write_html(path)
    print(f"  -> {path}")


# ─────────────────────────────────────────────
# VIZ 3: Key question heat-map (which specific questions dropped to 0)
# ─────────────────────────────────────────────
def viz_question_heatmap(sub_df):
    print("[viz] FH question heatmap ...")
    years = sorted(sub_df["year"].tolist())
    qs = [q for cat in CATEGORY_QUESTIONS.values() for q in cat]
    labels = [QUESTION_LABELS.get(q, q) for q in qs]

    matrix = []
    for q in qs:
        row = [sub_df[sub_df["year"]==y][q].values[0] if q in sub_df.columns
               and len(sub_df[sub_df["year"]==y]) > 0 else None for y in years]
        matrix.append(row)

    fig = go.Figure(go.Heatmap(
        z=matrix,
        x=[str(y) for y in years],
        y=[f"{qs[i]}: {labels[i]}" for i in range(len(qs))],
        colorscale=[[0,"#d62728"],[0.5,"#ffed6f"],[1,"#2ca02c"]],
        zmin=0, zmax=4,
        text=matrix,
        texttemplate="%{text}",
        colorbar=dict(title="Score<br>(0-4)"),
        hovertemplate="%{y}<br>%{x}: %{z}/4<extra></extra>",
    ))

    # Horizontal lines between categories
    cat_sizes = [len(v) for v in CATEGORY_QUESTIONS.values()]
    boundary = 0
    for i, sz in enumerate(cat_sizes[:-1]):
        boundary += sz
        fig.add_hline(y=boundary - 0.5, line_color="white", line_width=2)

    fig.update_layout(
        title="Freedom House Question-level Scores 2019–2024 (0=worst, 4=best)",
        height=700,
        xaxis_title="Year",
        yaxis=dict(autorange="reversed", tickfont_size=9),
        margin=dict(l=300),
    )
    path = os.path.join(OUTPUT_DIR, "viz_fh_question_heatmap.html")
    fig.write_html(path)
    print(f"  -> {path}")


# ─────────────────────────────────────────────
# VIZ 4: Approval timeline with all polls
# ─────────────────────────────────────────────
def viz_approval_timeline(approval_df):
    print("[viz] approval timeline ...")
    orgs = approval_df["org"].unique()
    colors = dict(zip(orgs, px.colors.qualitative.Set2[:len(orgs)]))

    fig = go.Figure()
    for org in orgs:
        sub = approval_df[approval_df["org"]==org]
        fig.add_trace(go.Scatter(
            x=sub["date"], y=sub["approval"],
            name=org, mode="markers+lines",
            marker_size=6, line=dict(width=1, color=colors[org]),
            opacity=0.75,
        ))

    # Median line
    monthly = (approval_df.groupby("ym")["approval"]
               .median().reset_index().rename(columns={"ym":"date"}))
    fig.add_trace(go.Scatter(
        x=monthly["date"], y=monthly["approval"],
        name="Monthly median (all pollsters)",
        mode="lines", line=dict(color="black", width=2.5),
    ))

    # Disapproval
    disap = approval_df.dropna(subset=["disapproval"])
    monthly_dis = (disap.groupby("ym")["disapproval"]
                   .median().reset_index().rename(columns={"ym":"date"}))
    fig.add_trace(go.Scatter(
        x=monthly_dis["date"], y=monthly_dis["disapproval"],
        name="Monthly median disapproval",
        mode="lines", line=dict(color="#d62728", width=1.5, dash="dot"),
    ))

    add_events(fig)
    fig.update_layout(
        title=("Bukele Presidential Approval Ratings 2019–2025<br>"
               "<sup>Multiple pollsters — lowest ever: 80.1% (TResearch Dec 2022); "
               "highest: 96% (CID Gallup Mar 2021 post-COVID response)</sup>"),
        yaxis=dict(title="% approval / disapproval", range=[0, 100]),
        xaxis_title="",
        height=520, hovermode="x unified",
        legend=dict(font_size=9),
    )
    path = os.path.join(OUTPUT_DIR, "viz_approval_timeline.html")
    fig.write_html(path)
    print(f"  -> {path}")


# ─────────────────────────────────────────────
# VIZ 5: Crackdown support vs civil liberties
# ─────────────────────────────────────────────
def viz_crackdown(fh_df, crack_df):
    print("[viz] crackdown support vs civil liberties ...")
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(go.Scatter(
        x=crack_df["date"], y=crack_df["support"],
        name="Régimen de Excepción support (%)",
        mode="markers+lines", marker_size=7,
        line=dict(color="#d62728", width=2),
    ), secondary_y=False)

    fig.add_trace(go.Scatter(
        x=fh_df["date"], y=fh_df["civil_lib"],
        name="Civil liberties score (/60)",
        mode="lines+markers", marker_size=8,
        line=dict(color="#1f77b4", width=2.5, shape="hv"),
    ), secondary_y=True)

    fig.add_vline(x=pd.Timestamp("2022-03-27").timestamp()*1000,
                  line_width=1.5, line_dash="dash", line_color="gray",
                  annotation_text="Régimen declared",
                  annotation_position="top left", annotation_font_size=9)

    fig.update_yaxes(title_text="Support for gang crackdown (%)",
                     range=[60, 100], secondary_y=False)
    fig.update_yaxes(title_text="Civil liberties score (/60)",
                     range=[25, 45], secondary_y=True)
    fig.update_layout(
        title=("Gang Crackdown Popularity vs. Civil Liberties Score<br>"
               "<sup>El Salvadorans broadly support the crackdown even as Freedom House "
               "flags due process and judicial independence concerns</sup>"),
        height=460, hovermode="x unified",
        legend=dict(x=0.01, y=0.1),
    )
    path = os.path.join(OUTPUT_DIR, "viz_crackdown_support.html")
    fig.write_html(path)
    print(f"  -> {path}")


# ─────────────────────────────────────────────
# VIZ 6: Combined dashboard — FH + approval + rhetoric
# ─────────────────────────────────────────────
def viz_combined(fh_df, approval_df):
    print("[viz] combined dashboard ...")

    monthly_approval = (approval_df.groupby("ym")["approval"]
                        .median().reset_index().rename(columns={"ym":"date"}))

    # Try to load rhetoric metrics from tweet analysis (optional)
    rhetoric_path = os.path.join("output", "rhetoric", "rhetoric_metrics.csv")
    rhetoric_df = None
    if os.path.exists(rhetoric_path):
        rhetoric_df = pd.read_csv(rhetoric_path, parse_dates=["ym"])
        bukele = rhetoric_df[rhetoric_df["handle"]=="nayibbukele"].copy()
        if len(bukele) > 0:
            bukele = bukele.sort_values("ym")
            rhetoric_df = bukele
        else:
            rhetoric_df = None

    rows = 3 if rhetoric_df is not None else 2
    titles = ["Freedom House Overall Score", "Bukele Approval Rating (%)"]
    if rhetoric_df is not None:
        titles.append("Bukele Confrontation Language (tweets)")

    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True,
                        subplot_titles=titles, vertical_spacing=0.08)

    # FH score
    fig.add_trace(go.Scatter(
        x=fh_df["date"], y=fh_df["overall"],
        name="FH score", mode="lines+markers",
        line=dict(color="#1f77b4", width=2.5, shape="hv"),
        marker_size=8,
    ), row=1, col=1)

    # Approval
    fig.add_trace(go.Scatter(
        x=monthly_approval["date"], y=monthly_approval["approval"],
        name="Approval %", mode="lines",
        line=dict(color="#d62728", width=2),
    ), row=2, col=1)

    # Rhetoric (if available)
    if rhetoric_df is not None:
        y = rhetoric_df["confront"].rolling(3, center=True, min_periods=1).mean()
        fig.add_trace(go.Scatter(
            x=rhetoric_df["ym"], y=y,
            name="Confrontation words/100 (Bukele tweets)",
            mode="lines", line=dict(color="#9467bd", width=2),
        ), row=3, col=1)

    # Event lines on all rows
    for dt_str, label in KEY_EVENTS:
        dt = pd.Timestamp(dt_str)
        for r in range(1, rows+1):
            fig.add_vline(x=dt.timestamp()*1000, line_width=1, line_dash="dot",
                          line_color="rgba(60,60,60,0.35)",
                          annotation_text=label if r==1 else "",
                          annotation_font_size=7,
                          annotation_position="top left",
                          row=r, col=1)

    fig.update_yaxes(title_text="Score /100", row=1, col=1)
    fig.update_yaxes(title_text="Approval %", range=[70,100], row=2, col=1)
    if rhetoric_df is not None:
        fig.update_yaxes(title_text="Rate per 100 words", row=3, col=1)
    fig.update_layout(
        title="El Salvador Political Dashboard: Institutions, Popularity & Rhetoric",
        height=200*rows + 150, showlegend=True,
        hovermode="x unified", legend=dict(font_size=9),
    )
    path = os.path.join(OUTPUT_DIR, "viz_combined_dashboard.html")
    fig.write_html(path)
    print(f"  -> {path}")


# ─────────────────────────────────────────────
# CSV EXPORT
# ─────────────────────────────────────────────
def save_csv(fh_df, approval_df, crack_df):
    monthly_approval = (approval_df.groupby("ym")[["approval","disapproval"]]
                        .median().reset_index().rename(columns={"ym":"date"}))
    monthly_approval["year"] = monthly_approval["date"].dt.year
    monthly_approval["month"] = monthly_approval["date"].dt.month

    merged = pd.merge(monthly_approval,
                      fh_df[["year","overall","status","pol_rights","civil_lib"]],
                      on="year", how="left")

    crack_df["year"]  = crack_df["date"].dt.year
    crack_df["month"] = crack_df["date"].dt.month
    merged = pd.merge(merged, crack_df[["year","month","support"]].rename(
                          columns={"support":"crackdown_support"}),
                      on=["year","month"], how="left")

    path = os.path.join(OUTPUT_DIR, "public_metrics.csv")
    merged.to_csv(path, index=False)
    print(f"[csv] {path} ({len(merged):,} rows)")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print("="*65)
    print("El Salvador — Public Metrics Overlay")
    print("="*65)

    fh_df       = build_fh_df()
    approval_df = build_approval_df()
    crack_df    = build_crackdown_df()
    sub_df      = build_subscore_df()

    save_csv(fh_df, approval_df, crack_df)
    viz_democracy_vs_approval(fh_df, approval_df)
    viz_fh_subscores(fh_df, sub_df)
    viz_question_heatmap(sub_df)
    viz_approval_timeline(approval_df)
    viz_crackdown(fh_df, crack_df)
    viz_combined(fh_df, approval_df)

    print("\n" + "="*65)
    print("KEY NUMBERS")
    print("="*65)
    print(f"  FH score 2017→2024: 70 → 53  (-17 points, Free → Partly Free)")
    print(f"  Questions at 0/4 in 2024: F1 (judiciary), F2 (due process),")
    print(f"    C2 (anti-corruption safeguards), C3 (transparency)")
    print(f"  Approval range 2019-2025: {min(p[1] for p in APPROVAL_POLLS):.1f}% – "
          f"{max(p[1] for p in APPROVAL_POLLS):.1f}%")
    print(f"  Crackdown support range: "
          f"{min(p[1] for p in CRACKDOWN_SUPPORT):.1f}% – "
          f"{max(p[1] for p in CRACKDOWN_SUPPORT):.1f}%")
    print(f"\nOpen output/public_metrics/viz_democracy_vs_approval.html first —")
    print(f"it tells the whole story in one chart.")


if __name__ == "__main__":
    main()
