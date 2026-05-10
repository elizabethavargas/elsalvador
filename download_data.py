"""
download_data.py — Download the El Salvador corpus data files from Google Cloud Storage.

Usage:
    python download_data.py

Files are saved to output/ and output/data/ to match the paths expected
by all analysis scripts.
"""

import os
import sys
import requests

# ── Fill in these URLs after uploading to Google Cloud Storage ────────────────
# Make each file public (Storage > select file > Permissions > Add principal:
# allUsers, role: Storage Object Viewer), then copy the public URL.
DATA_FILES = {
    "output/articles_master.csv":           "PASTE_GCS_URL_HERE",
    "output/articles_text_clean.csv":       "PASTE_GCS_URL_HERE",
    "output/el_salvador_political_dataset.csv": "PASTE_GCS_URL_HERE",
    "output/data/tweets.csv":               "PASTE_GCS_URL_HERE",
}
# ─────────────────────────────────────────────────────────────────────────────


def download(url, dest):
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    print(f"Downloading {os.path.basename(dest)} ...", end=" ", flush=True)
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
                done += len(chunk)
                if total:
                    pct = done * 100 // total
                    print(f"\r  {os.path.basename(dest)}: {pct}%   ", end="", flush=True)
    print(f"\r  {os.path.basename(dest)}: done ({done // 1_000_000} MB)")


def main():
    missing = [k for k, v in DATA_FILES.items() if v == "PASTE_GCS_URL_HERE"]
    if missing:
        print("ERROR: Fill in the Google Cloud Storage URLs in download_data.py first.")
        print("Missing URLs for:", *missing, sep="\n  ")
        sys.exit(1)

    for dest, url in DATA_FILES.items():
        if os.path.exists(dest):
            print(f"  {dest} already exists, skipping.")
            continue
        download(url, dest)

    print("\nAll data files downloaded. You can now run the analysis scripts.")


if __name__ == "__main__":
    main()
