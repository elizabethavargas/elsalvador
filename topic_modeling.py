"""
topic_modeling.py — BERTopic analysis of El Salvador government tweets

REQUIREMENTS:
  pip install bertopic sentence-transformers umap-learn hdbscan pandas plotly

WHAT IT DOES:
  1. Loads tweets.csv, deduplicates by tweet_id
  2. Generates multilingual sentence embeddings (cached to disk for fast re-runs)
  3. Fits BERTopic to discover latent topics in the corpus
  4. Runs topics-over-time analysis (monthly granularity)
  5. Runs per-account topic breakdown
  6. Saves outputs:
       output/topics/topic_info.csv         — topic labels + sizes
       output/topics/tweet_topics.csv        — every tweet with its topic
       output/topics/topics_over_time.csv    — topic prevalence per month
       output/topics/viz_topics.html         — interactive topic overview
       output/topics/viz_over_time.html      — temporal topic chart
       output/topics/viz_heatmap.html        — account × topic heatmap

KEY EL SALVADOR EVENTS annotated on the temporal chart:
  2019-06  Bukele inaugurated as president
  2020-03  COVID state of emergency
  2021-05  Legislative Assembly fires Supreme Court justices + AG
  2021-09  Bitcoin becomes legal tender
  2022-03  Régimen de Excepción (gang crackdown)
  2023-12  CECOT mega-prison opens
  2024-02  Bukele re-elected
"""

import os
import pickle
import csv
import datetime

import numpy as np
import pandas as pd

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
INPUT_CSV       = "tweets.csv"
OUTPUT_DIR      = os.path.join("output", "topics")
EMBEDDINGS_FILE = os.path.join(OUTPUT_DIR, "embeddings.npy")
CORPUS_IDS_FILE = os.path.join(OUTPUT_DIR, "corpus_ids.pkl")  # tweet_ids matching embeddings rows

# Sentence transformer model — multilingual, handles Spanish well, free & local
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

# BERTopic tuning
NR_TOPICS       = "auto"   # let HDBSCAN decide; set an int to force a number
MIN_TOPIC_SIZE  = 30       # minimum tweets to form a topic cluster
TOP_N_WORDS     = 10       # words per topic label

# ─────────────────────────────────────────────
# KEY EVENTS for annotation
# ─────────────────────────────────────────────
KEY_EVENTS = [
    ("2016-01", "Arena/FMLN\npolitical deadlock"),
    ("2019-06", "Bukele\ninaugurated"),
    ("2020-03", "COVID\nemergency"),
    ("2021-05", "Assembly fires\nCSJ + FGR"),
    ("2021-09", "Bitcoin\nlegal tender"),
    ("2022-03", "Régimen de\nExcepción"),
    ("2023-12", "CECOT\nopens"),
    ("2024-02", "Bukele\nre-elected"),
]


# ─────────────────────────────────────────────
# LOAD + DEDUPE
# ─────────────────────────────────────────────
def load_tweets():
    print(f"[load] Reading {INPUT_CSV} ...")
    df = pd.read_csv(INPUT_CSV, dtype=str).fillna("")
    before = len(df)
    df = df.drop_duplicates(subset="tweet_id")
    after = len(df)
    if before != after:
        print(f"[load] Dropped {before - after:,} duplicate rows → {after:,} tweets")
    else:
        print(f"[load] {after:,} tweets (no duplicates)")

    # Parse dates
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["year"]  = df["date"].dt.year.fillna(0).astype(int)
    df["month"] = df["date"].dt.month.fillna(0).astype(int)
    df["year_month"] = df["date"].dt.to_period("M").astype(str)

    # Keep only tweets with parseable dates and non-empty text
    df = df[df["date"].notna() & (df["text"].str.strip() != "")]
    print(f"[load] {len(df):,} tweets with valid date + text")
    return df.reset_index(drop=True)


# ─────────────────────────────────────────────
# EMBEDDINGS (cached)
# ─────────────────────────────────────────────
def get_embeddings(texts: list[str]) -> np.ndarray:
    """
    Generate or load cached sentence embeddings.
    Embedding 160K+ tweets takes ~5–10 min on CPU the first time;
    subsequent runs load from disk in seconds.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    if os.path.exists(EMBEDDINGS_FILE) and os.path.exists(CORPUS_IDS_FILE):
        print("[embed] Loading cached embeddings from disk ...")
        embeddings = np.load(EMBEDDINGS_FILE)
        if embeddings.shape[0] == len(texts):
            return embeddings
        print("[embed] Cache size mismatch — regenerating ...")

    print(f"[embed] Encoding {len(texts):,} tweets with {EMBEDDING_MODEL} ...")
    print("[embed] This takes ~5–15 min on CPU. Go get a coffee ☕")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(EMBEDDING_MODEL)
    embeddings = model.encode(
        texts,
        batch_size=256,
        show_progress_bar=True,
        convert_to_numpy=True,
    )
    np.save(EMBEDDINGS_FILE, embeddings)
    print(f"[embed] Saved embeddings to {EMBEDDINGS_FILE}")
    return embeddings


# ─────────────────────────────────────────────
# BERTOPIC
# ─────────────────────────────────────────────
def fit_topic_model(texts: list[str], embeddings: np.ndarray):
    from bertopic import BERTopic
    from bertopic.vectorizers import ClassTfidfTransformer
    from sklearn.feature_extraction.text import CountVectorizer

    print(f"\n[topic] Fitting BERTopic (nr_topics={NR_TOPICS}, "
          f"min_topic_size={MIN_TOPIC_SIZE}) ...")

    # Spanish-aware stop words — BERTopic's default uses English; extend as needed
    SPANISH_STOPWORDS = [
        "de","la","el","en","y","a","los","las","del","se","que","por",
        "con","una","un","es","para","su","al","lo","como","más","o",
        "pero","sus","le","ya","o","fue","ha","este","entre","cuando",
        "muy","sin","sobre","también","me","hasta","hay","donde","quien",
        "desde","todo","nos","durante","uno","ni","contra","ese","via",
        "https","http","co","amp","rt","gt","lt",
    ]

    vectorizer = CountVectorizer(
        ngram_range=(1, 2),
        stop_words=SPANISH_STOPWORDS,
        min_df=5,
    )
    ctfidf = ClassTfidfTransformer(reduce_frequent_words=True)

    topic_model = BERTopic(
        embedding_model=EMBEDDING_MODEL,
        vectorizer_model=vectorizer,
        ctfidf_model=ctfidf,
        nr_topics=NR_TOPICS,
        min_topic_size=MIN_TOPIC_SIZE,
        top_n_words=TOP_N_WORDS,
        calculate_probabilities=False,
        verbose=True,
    )

    topics, _ = topic_model.fit_transform(texts, embeddings)
    n_topics = len(set(topics)) - (1 if -1 in topics else 0)
    n_outliers = sum(1 for t in topics if t == -1)
    print(f"[topic] Found {n_topics} topics  |  {n_outliers:,} outlier tweets")
    return topic_model, topics


# ─────────────────────────────────────────────
# TOPICS OVER TIME
# ─────────────────────────────────────────────
def run_topics_over_time(topic_model, df: pd.DataFrame, topics: list):
    print("\n[time] Computing topics over time ...")
    timestamps = df["date"].tolist()
    texts      = df["text"].tolist()

    topics_over_time = topic_model.topics_over_time(
        texts,
        timestamps,
        nr_bins=132,           # ~1 bin per month over 11 years
        evolution_tuning=True,
        global_tuning=True,
    )
    return topics_over_time


# ─────────────────────────────────────────────
# VISUALIZATIONS
# ─────────────────────────────────────────────
def add_event_lines(fig, topics_over_time):
    """Overlay vertical lines for key El Salvador events."""
    import plotly.graph_objects as go

    for date_str, label in KEY_EVENTS:
        dt = pd.Timestamp(date_str)
        fig.add_vline(
            x=dt,
            line_width=1.5,
            line_dash="dot",
            line_color="rgba(80,80,80,0.6)",
            annotation_text=label,
            annotation_position="top",
            annotation_font_size=9,
        )
    return fig


def save_visualizations(topic_model, df: pd.DataFrame, topics: list,
                        topics_over_time):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 1. Topic overview (barchart of top words per topic)
    print("[viz] Saving topic overview ...")
    fig_topics = topic_model.visualize_barchart(top_n_topics=20)
    fig_topics.write_html(os.path.join(OUTPUT_DIR, "viz_topics.html"))

    # 2. Topics over time — top 15 topics
    print("[viz] Saving topics-over-time chart ...")
    topic_info = topic_model.get_topic_info()
    top_topics = topic_info[topic_info["Topic"] != -1].head(15)["Topic"].tolist()

    fig_time = topic_model.visualize_topics_over_time(
        topics_over_time,
        topics=top_topics,
        title="El Salvador Government Tweets — Topics Over Time (2015–2025)",
    )
    fig_time = add_event_lines(fig_time, topics_over_time)
    fig_time.write_html(os.path.join(OUTPUT_DIR, "viz_over_time.html"))

    # 3. Per-account topic heatmap
    print("[viz] Saving per-account heatmap ...")
    df_topics = df.copy()
    df_topics["topic"] = topics
    df_topics = df_topics[df_topics["topic"] != -1]

    # Get readable topic labels
    topic_labels = {
        row["Topic"]: f"T{row['Topic']}: {row['Name']}"
        for _, row in topic_model.get_topic_info().iterrows()
        if row["Topic"] != -1
    }

    # Cross-tab: account × topic (normalised by account so percentages sum to 100)
    crosstab = pd.crosstab(
        df_topics["handle"],
        df_topics["topic"].map(topic_labels),
        normalize="index",
    ) * 100

    import plotly.express as px
    fig_heat = px.imshow(
        crosstab,
        text_auto=".1f",
        aspect="auto",
        color_continuous_scale="Blues",
        title="Topic distribution per account (% of account's tweets)",
        labels={"x": "Topic", "y": "Account", "color": "%"},
    )
    fig_heat.update_layout(
        xaxis_tickangle=-45,
        height=400,
        margin=dict(l=120, b=200),
    )
    fig_heat.write_html(os.path.join(OUTPUT_DIR, "viz_heatmap.html"))

    print(f"[viz] All charts saved to {OUTPUT_DIR}/")


# ─────────────────────────────────────────────
# CSV EXPORTS
# ─────────────────────────────────────────────
def save_csvs(topic_model, df: pd.DataFrame, topics: list, topics_over_time):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # topic_info.csv
    topic_info = topic_model.get_topic_info()
    topic_info.to_csv(os.path.join(OUTPUT_DIR, "topic_info.csv"), index=False)
    print(f"[csv] Saved topic_info.csv ({len(topic_info)} topics)")

    # tweet_topics.csv — original df with topic assignment
    df_out = df[["tweet_id", "handle", "account", "date", "year", "month",
                 "text", "likes", "retweets", "replies", "views"]].copy()
    df_out["topic_id"] = topics
    topic_names = {
        row["Topic"]: row["Name"]
        for _, row in topic_info.iterrows()
    }
    df_out["topic_name"] = df_out["topic_id"].map(topic_names).fillna("outlier")
    df_out.to_csv(os.path.join(OUTPUT_DIR, "tweet_topics.csv"), index=False)
    print(f"[csv] Saved tweet_topics.csv ({len(df_out):,} rows)")

    # topics_over_time.csv
    topics_over_time.to_csv(os.path.join(OUTPUT_DIR, "topics_over_time.csv"), index=False)
    print(f"[csv] Saved topics_over_time.csv ({len(topics_over_time):,} rows)")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    print("=" * 65)
    print("El Salvador Tweet Topic Modeling — BERTopic")
    print("=" * 65)

    # 1. Load data
    df = load_tweets()

    # 2. Embeddings (cached after first run)
    texts      = df["text"].tolist()
    embeddings = get_embeddings(texts)

    # Save corpus IDs alongside embeddings for cache validation
    with open(CORPUS_IDS_FILE, "wb") as f:
        pickle.dump(df["tweet_id"].tolist(), f)

    # 3. Fit BERTopic
    topic_model, topics = fit_topic_model(texts, embeddings)

    # 4. Topics over time
    topics_over_time = run_topics_over_time(topic_model, df, topics)

    # 5. Save CSVs
    save_csvs(topic_model, df, topics, topics_over_time)

    # 6. Save visualizations
    save_visualizations(topic_model, df, topics, topics_over_time)

    # 7. Print topic summary to terminal
    print("\n" + "=" * 65)
    print("TOP 20 TOPICS")
    print("=" * 65)
    topic_info = topic_model.get_topic_info()
    for _, row in topic_info[topic_info["Topic"] != -1].head(20).iterrows():
        print(f"  T{row['Topic']:3d}  {row['Count']:6,} tweets  {row['Name']}")

    print(f"\n✓ Done. Open output/topics/viz_over_time.html to explore trends.")


if __name__ == "__main__":
    main()
