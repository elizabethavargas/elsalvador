"""
topic_modeling.py — Topic modeling of El Salvador government tweets

No BERTopic or standalone hdbscan required. Pipeline:
  1. Sentence embeddings  (sentence-transformers, cached)
  2. UMAP dimensionality reduction  (umap-learn)
  3. HDBSCAN clustering  (sklearn.cluster.HDBSCAN, sklearn >= 1.3)
  4. c-TF-IDF topic labels  (custom, pure numpy/sklearn)
  5. Topics-over-time aggregation  (monthly bins)
  6. Interactive Plotly charts + CSV exports

REQUIREMENTS:
  pip install sentence-transformers umap-learn pandas plotly scikit-learn>=1.3

OUTPUTS (all in output/topics/):
  topic_info.csv          topic id, label, size
  tweet_topics.csv        every tweet with its topic_id + topic_name
  topics_over_time.csv    monthly topic frequency table (wide format)
  viz_topics.html         bar chart of top words per topic
  viz_over_time.html      temporal line chart with key SV events
  viz_heatmap.html        account × topic heatmap

KEY EL SALVADOR EVENTS annotated on the temporal chart:
  2016-01  Arena/FMLN political deadlock
  2019-06  Bukele inaugurated as president
  2020-03  COVID state of emergency
  2021-05  Legislative Assembly fires Supreme Court justices + AG
  2021-09  Bitcoin becomes legal tender
  2022-03  Regimen de Excepcion (gang crackdown)
  2023-12  CECOT mega-prison opens
  2024-02  Bukele re-elected
"""

import os

# Force PyTorch backend before any transformers import
os.environ["USE_TF"] = "0"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import pickle
import numpy as np
import pandas as pd
from collections import defaultdict

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
INPUT_CSV       = "tweets.csv"
OUTPUT_DIR      = os.path.join("output", "topics")
EMBEDDINGS_FILE = os.path.join(OUTPUT_DIR, "embeddings.npy")
CORPUS_IDS_FILE = os.path.join(OUTPUT_DIR, "corpus_ids.pkl")

EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

# PCA settings
PCA_N_COMPONENTS = 50    # dims before clustering (preserves ~80% variance)

# Clustering — KMeans assigns every tweet (no outliers)
N_TOPICS    = 25         # number of topics; tune up/down to taste
TOP_N_WORDS = 10         # keywords shown per topic

# ─────────────────────────────────────────────
# KEY EVENTS
# ─────────────────────────────────────────────
KEY_EVENTS = [
    ("2016-01", "Arena/FMLN<br>deadlock"),
    ("2019-06", "Bukele<br>inaugurated"),
    ("2020-03", "COVID<br>emergency"),
    ("2021-05", "Assembly fires<br>CSJ + FGR"),
    ("2021-09", "Bitcoin<br>legal tender"),
    ("2022-03", "Regimen de<br>Excepcion"),
    ("2023-12", "CECOT<br>opens"),
    ("2024-02", "Bukele<br>re-elected"),
]

SPANISH_STOPWORDS = set([
    "de","la","el","en","y","a","los","las","del","se","que","por",
    "con","una","un","es","para","su","al","lo","como","mas","o",
    "pero","sus","le","ya","fue","ha","este","entre","cuando",
    "muy","sin","sobre","tambien","me","hasta","hay","donde","quien",
    "desde","todo","nos","durante","uno","ni","contra","ese",
    "https","http","co","amp","rt","gt","lt","via","hoy","ser",
    "han","si","this","the","of","in","to","is","are","pic",
    "twitter","t","s","e","i","u","k",
])


# ─────────────────────────────────────────────
# 1. LOAD + DEDUPE
# ─────────────────────────────────────────────
def load_tweets():
    print(f"[load] Reading {INPUT_CSV} ...")
    df = pd.read_csv(INPUT_CSV, dtype=str).fillna("")
    before = len(df)
    df = df.drop_duplicates(subset="tweet_id")
    after  = len(df)
    if before != after:
        print(f"[load] Dropped {before - after:,} duplicates -> {after:,} tweets")
    else:
        print(f"[load] {after:,} tweets (no duplicates)")

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df[df["date"].notna() & (df["text"].str.strip() != "")]
    df["year_month"] = df["date"].dt.to_period("M").astype(str)
    print(f"[load] {len(df):,} tweets with valid date + text")
    return df.reset_index(drop=True)


# ─────────────────────────────────────────────
# 2. EMBEDDINGS (cached)
# ─────────────────────────────────────────────
def get_embeddings(texts):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if os.path.exists(EMBEDDINGS_FILE):
        print("[embed] Loading cached embeddings ...")
        emb = np.load(EMBEDDINGS_FILE)
        if emb.shape[0] == len(texts):
            return emb
        print("[embed] Cache size mismatch — regenerating ...")

    print(f"[embed] Encoding {len(texts):,} tweets with {EMBEDDING_MODEL} ...")
    print("[embed] First run takes ~5-15 min on CPU. Go get a coffee.")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(EMBEDDING_MODEL)
    emb = model.encode(texts, batch_size=256, show_progress_bar=True,
                       convert_to_numpy=True)
    np.save(EMBEDDINGS_FILE, emb)
    with open(CORPUS_IDS_FILE, "wb") as f:
        pickle.dump(list(range(len(texts))), f)
    print(f"[embed] Saved to {EMBEDDINGS_FILE}")
    return emb


# ─────────────────────────────────────────────
# 3. PCA dimensionality reduction
# ─────────────────────────────────────────────
def reduce_embeddings(embeddings):
    print(f"[pca] Reducing {embeddings.shape} -> (n, {PCA_N_COMPONENTS}) ...")
    from sklearn.decomposition import PCA
    reducer = PCA(n_components=PCA_N_COMPONENTS, random_state=42)
    reduced = reducer.fit_transform(embeddings)
    explained = reducer.explained_variance_ratio_.sum() * 100
    print(f"[pca] Done. Shape: {reduced.shape}  "
          f"({explained:.1f}% variance explained)")
    return reduced


# ─────────────────────────────────────────────
# 4. KMeans clustering (no outliers)
# ─────────────────────────────────────────────
def cluster(reduced):
    print(f"[cluster] KMeans (n_topics={N_TOPICS}) ...")
    from sklearn.cluster import KMeans
    model = KMeans(n_clusters=N_TOPICS, random_state=42, n_init=10)
    labels = model.fit_predict(reduced)
    print(f"[cluster] Done. {N_TOPICS} topics, 0 outliers.")
    return labels


# ─────────────────────────────────────────────
# 5. c-TF-IDF TOPIC LABELS
# ─────────────────────────────────────────────
def make_topic_labels(texts, labels):
    """
    Class-based TF-IDF: for each topic, concatenate all tweets and compute
    TF-IDF against the other topics as 'documents'. Returns:
      topic_words  : {topic_id -> [(word, score), ...]}
      topic_labels : {topic_id -> "word1 word2 word3"}
    """
    print("[label] Computing c-TF-IDF topic labels ...")
    from sklearn.feature_extraction.text import TfidfVectorizer

    topic_ids = sorted(set(labels))

    # Build one mega-document per topic
    docs = []
    for tid in topic_ids:
        idxs = [i for i, l in enumerate(labels) if l == tid]
        merged = " ".join(texts[i] for i in idxs)
        docs.append(merged)

    vec = TfidfVectorizer(
        ngram_range=(1, 2),
        max_features=20000,
        sublinear_tf=True,
        token_pattern=r"(?u)\b[a-zA-ZáéíóúüñÁÉÍÓÚÜÑ]{3,}\b",
    )
    tfidf = vec.fit_transform(docs)
    feature_names = vec.get_feature_names_out()

    topic_words  = {}
    topic_labels = {}
    for i, tid in enumerate(topic_ids):
        row   = tfidf[i].toarray().flatten()
        top_i = row.argsort()[::-1]
        words = []
        for j in top_i:
            w = feature_names[j]
            if w.lower() not in SPANISH_STOPWORDS and len(w) > 2:
                words.append((w, float(row[j])))
            if len(words) == TOP_N_WORDS:
                break
        topic_words[tid]  = words
        topic_labels[tid] = " | ".join(w for w, _ in words[:5])

    # Count sizes
    topic_sizes = defaultdict(int)
    for l in labels:
        if l != -1:
            topic_sizes[l] += 1

    return topic_words, topic_labels, topic_sizes


# ─────────────────────────────────────────────
# 6. TOPICS OVER TIME
# ─────────────────────────────────────────────
def topics_over_time(df, labels):
    print("[time] Aggregating topics over time (monthly) ...")
    df2 = df.copy()
    df2["topic"] = labels

    # Monthly counts per topic
    pivot = (df2.groupby(["year_month", "topic"])
               .size()
               .unstack(fill_value=0)
               .sort_index())

    # Normalise to fraction of all non-outlier tweets that month
    row_sums = pivot.sum(axis=1).replace(0, 1)
    pivot_pct = pivot.div(row_sums, axis=0) * 100
    return pivot, pivot_pct


# ─────────────────────────────────────────────
# 7. SAVE CSVs
# ─────────────────────────────────────────────
def save_csvs(df, labels, topic_words, topic_labels, topic_sizes, pivot, pivot_pct):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # topic_info.csv
    rows = []
    for tid in sorted(topic_labels):
        rows.append({
            "topic_id":    tid,
            "topic_name":  topic_labels[tid],
            "size":        topic_sizes[tid],
            "top_words":   ", ".join(w for w, _ in topic_words[tid]),
        })
    pd.DataFrame(rows).to_csv(os.path.join(OUTPUT_DIR, "topic_info.csv"), index=False)
    print(f"[csv] topic_info.csv ({len(rows)} topics)")

    # tweet_topics.csv
    df_out = df[["tweet_id","handle","account","date","year","month",
                 "text","likes","retweets","replies","views"]].copy()
    df_out["topic_id"]   = labels
    df_out["topic_name"] = [topic_labels.get(l, "") for l in labels]
    df_out.to_csv(os.path.join(OUTPUT_DIR, "tweet_topics.csv"), index=False)
    print(f"[csv] tweet_topics.csv ({len(df_out):,} rows)")

    # topics_over_time.csv (raw counts)
    pivot.to_csv(os.path.join(OUTPUT_DIR, "topics_over_time.csv"))
    print(f"[csv] topics_over_time.csv ({len(pivot)} months x {len(pivot.columns)} topics)")


# ─────────────────────────────────────────────
# 8. VISUALIZATIONS
# ─────────────────────────────────────────────
def viz_topics(topic_words, topic_labels, topic_sizes):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    # Top 20 topics by size
    top_ids = sorted(topic_sizes, key=topic_sizes.get, reverse=True)[:20]

    fig = make_subplots(
        rows=4, cols=5,
        subplot_titles=[f"T{tid}: {topic_labels[tid][:30]}" for tid in top_ids],
    )
    for idx, tid in enumerate(top_ids):
        r, c = divmod(idx, 5)
        words  = [w for w, _ in topic_words[tid][:8]][::-1]
        scores = [s for _, s in topic_words[tid][:8]][::-1]
        fig.add_trace(
            go.Bar(x=scores, y=words, orientation="h",
                   marker_color="steelblue", showlegend=False),
            row=r + 1, col=c + 1,
        )
    fig.update_layout(
        title="Top 20 Topics — Key Words (c-TF-IDF)",
        height=900,
        margin=dict(t=80),
    )
    path = os.path.join(OUTPUT_DIR, "viz_topics.html")
    fig.write_html(path)
    print(f"[viz] {path}")


def viz_over_time(pivot_pct, topic_labels, topic_sizes):
    import plotly.graph_objects as go

    top_ids = sorted(topic_sizes, key=topic_sizes.get, reverse=True)[:15]
    dates   = [pd.Timestamp(str(p)) for p in pivot_pct.index]

    fig = go.Figure()
    for tid in top_ids:
        if tid not in pivot_pct.columns:
            continue
        fig.add_trace(go.Scatter(
            x=dates,
            y=pivot_pct[tid],
            mode="lines",
            name=f"T{tid}: {topic_labels[tid][:40]}",
            line=dict(width=1.5),
        ))

    # Annotate key events
    for date_str, label in KEY_EVENTS:
        dt = pd.Timestamp(date_str)
        fig.add_vline(
            x=dt.timestamp() * 1000,  # plotly uses ms for datetime axis
            line_width=1.2,
            line_dash="dot",
            line_color="rgba(80,80,80,0.55)",
            annotation_text=label,
            annotation_position="top left",
            annotation_font_size=8,
        )

    fig.update_layout(
        title="El Salvador Government Tweets — Topics Over Time (2015-2025)",
        xaxis_title="Month",
        yaxis_title="% of tweets that month",
        height=600,
        legend=dict(font_size=9),
        hovermode="x unified",
    )
    path = os.path.join(OUTPUT_DIR, "viz_over_time.html")
    fig.write_html(path)
    print(f"[viz] {path}")


def viz_heatmap(df, labels, topic_labels):
    import plotly.express as px

    df2 = df.copy()
    df2["topic"] = labels
    df2["topic_name"] = [f"T{l}: {topic_labels[l][:30]}" for l in df2["topic"]]

    crosstab = pd.crosstab(df2["handle"], df2["topic_name"], normalize="index") * 100

    fig = px.imshow(
        crosstab,
        text_auto=".1f",
        aspect="auto",
        color_continuous_scale="Blues",
        title="Topic distribution per account (% of account tweets)",
        labels={"x": "Topic", "y": "Account", "color": "%"},
    )
    fig.update_layout(xaxis_tickangle=-40, height=420, margin=dict(l=130, b=220))
    path = os.path.join(OUTPUT_DIR, "viz_heatmap.html")
    fig.write_html(path)
    print(f"[viz] {path}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    print("=" * 65)
    print("El Salvador Tweet Topic Modeling")
    print("=" * 65)

    df     = load_tweets()
    texts  = df["text"].tolist()

    embeddings = get_embeddings(texts)
    reduced    = reduce_embeddings(embeddings)
    labels     = cluster(reduced)

    topic_words, topic_labels, topic_sizes = make_topic_labels(texts, labels)
    pivot, pivot_pct = topics_over_time(df, labels)

    save_csvs(df, labels, topic_words, topic_labels, topic_sizes, pivot, pivot_pct)

    viz_topics(topic_words, topic_labels, topic_sizes)
    viz_over_time(pivot_pct, topic_labels, topic_sizes)
    viz_heatmap(df, labels, topic_labels)

    print("\n" + "=" * 65)
    print("TOP 20 TOPICS BY SIZE")
    print("=" * 65)
    top_ids = sorted(topic_sizes, key=topic_sizes.get, reverse=True)[:20]
    for tid in top_ids:
        print(f"  T{tid:3d}  {topic_sizes[tid]:6,} tweets  {topic_labels[tid]}")

    print(f"\n  Total tweets assigned: {len(labels):,}")
    print(f"\nDone. Open output/topics/viz_over_time.html to explore trends.")


if __name__ == "__main__":
    main()
