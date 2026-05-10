#!/usr/bin/env bash
# deploy.sh — Sync latest viz files and deploy to Firebase Hosting
# Run from anywhere: bash website/deploy.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
VIZ_DIR="$SCRIPT_DIR/viz"

echo "==> Syncing latest visualizations into website/viz/ ..."
mkdir -p "$VIZ_DIR"

copy_if_exists() {
  local src="$1" dst="$2"
  if [ -f "$src" ]; then
    cp "$src" "$dst"
    echo "    ✓ $(basename "$dst")"
  else
    echo "    ✗ MISSING: $src"
  fi
}

copy_if_exists "$REPO_ROOT/output/event_framing/viz_wordclouds.html"          "$VIZ_DIR/event_framing_wordclouds.html"
copy_if_exists "$REPO_ROOT/output/event_framing/viz_butterfly.html"           "$VIZ_DIR/event_framing_butterfly.html"
copy_if_exists "$REPO_ROOT/output/event_framing/viz_scatter.html"             "$VIZ_DIR/event_framing_scatter.html"
copy_if_exists "$REPO_ROOT/output/bukele_critics/viz_strategy_target_heatmap.html" "$VIZ_DIR/bukele_critics_heatmap.html"
copy_if_exists "$REPO_ROOT/output/bukele_critics/viz_volume_over_time.html"   "$VIZ_DIR/bukele_volume.html"
copy_if_exists "$REPO_ROOT/output/bukele_critics/viz_strategies.html"         "$VIZ_DIR/bukele_strategies.html"
copy_if_exists "$REPO_ROOT/output/bukele_critics/viz_targets.html"            "$VIZ_DIR/bukele_targets.html"
copy_if_exists "$REPO_ROOT/output/bukele_critics/viz_examples.html"           "$VIZ_DIR/bukele_examples.html"
copy_if_exists "$REPO_ROOT/output/word_prevalence/viz_tweets_distinctive.html" "$VIZ_DIR/tweets_distinctive.html"
copy_if_exists "$REPO_ROOT/output/word_prevalence/viz_tweets_heatmap.html"    "$VIZ_DIR/tweets_heatmap.html"
copy_if_exists "$REPO_ROOT/output/word_prevalence/viz_media_distinctive.html" "$VIZ_DIR/media_distinctive.html"
copy_if_exists "$REPO_ROOT/output/word_prevalence/viz_press_heatmap.html"     "$VIZ_DIR/press_heatmap.html"
copy_if_exists "$REPO_ROOT/output/ngram_comparison/viz_tweet_bigrams.html"    "$VIZ_DIR/tweet_bigrams.html"
copy_if_exists "$REPO_ROOT/output/ngram_comparison/viz_media_bigrams.html"    "$VIZ_DIR/media_bigrams.html"
copy_if_exists "$REPO_ROOT/output/ngram_comparison/viz_distinctive_bigrams.html" "$VIZ_DIR/distinctive_bigrams.html"

echo ""
echo "==> Deploying to Firebase Hosting ..."
cd "$SCRIPT_DIR"
firebase deploy --only hosting

echo ""
echo "✅  Done! Your site is live."
