#!/usr/bin/env python3
"""Download official NCS tracks listed in assets/music.json.

Audio files are gitignored. Run this once before rendering, or let
make_video.py call it automatically when --music is missing.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / "assets" / "music.json"
DEST_DIR = ROOT / "assets" / "music"


def download_all() -> list[Path]:
    tracks = json.loads(META.read_text())["tracks"]
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    for t in tracks:
        dest = DEST_DIR / t["file"]
        if dest.exists() and dest.stat().st_size > 100_000:
            print(f"Already present: {dest} ({dest.stat().st_size} bytes)")
            saved.append(dest)
            continue
        url = t["download_url"]
        print(f"Downloading {t['artist']} - {t['title']}")
        print(f"  official source: {t['source_page']}")
        print(f"  {url}")
        req = urllib.request.Request(url, headers={"User-Agent": "2nd-experiment/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp, dest.open("wb") as f:
            f.write(resp.read())
        print(f"  saved {dest} ({dest.stat().st_size} bytes)")
        print("Credit required in every post description:")
        print(t["credit"])
        saved.append(dest)
    return saved


if __name__ == "__main__":
    try:
        download_all()
    except Exception as e:
        print(f"Download failed: {e}", file=sys.stderr)
        sys.exit(1)
