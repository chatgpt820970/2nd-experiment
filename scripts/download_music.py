#!/usr/bin/env python3
"""Download the royalty-free tracks listed in assets/music.json.

Audio files are gitignored. Run this once before rendering, or let
make_video.py fetch a single missing track automatically.

    python3 scripts/download_music.py                 # all tracks
    python3 scripts/download_music.py ncs_teamo.mp3   # only these files
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / "assets" / "music.json"
DEST_DIR = ROOT / "assets" / "music"
MIN_BYTES = 100_000


def tracks() -> list[dict]:
    return json.loads(META.read_text())["tracks"]


def download_one(t: dict, retries: int = 3) -> Path:
    """Download one track atomically (tmp file + rename), with retries."""
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    dest = DEST_DIR / t["file"]
    if dest.exists() and dest.stat().st_size > MIN_BYTES:
        return dest
    url = t["download_url"]
    tmp = dest.with_suffix(dest.suffix + ".part")
    last = None
    for attempt in range(1, retries + 1):
        try:
            print(f"Downloading {t['artist']} - {t['title']} (try {attempt})")
            print(f"  official source: {t['source_page']}")
            req = urllib.request.Request(url, headers={"User-Agent": "2nd-experiment/2.0"})
            with urllib.request.urlopen(req, timeout=90) as resp, tmp.open("wb") as f:
                while chunk := resp.read(1 << 16):
                    f.write(chunk)
            if tmp.stat().st_size < MIN_BYTES:
                raise IOError(f"file too small ({tmp.stat().st_size} bytes)")
            tmp.replace(dest)
            print(f"  saved {dest} ({dest.stat().st_size} bytes)")
            print("Credit required in every post description:")
            print(t["credit"])
            return dest
        except Exception as e:  # network / http / disk
            last = e
            print(f"  failed: {e}", file=sys.stderr)
            tmp.unlink(missing_ok=True)
            time.sleep(2 * attempt)
    raise RuntimeError(f"could not download {t['file']}: {last}")


def download_all(only: list[str] | None = None) -> list[Path]:
    saved, failed = [], []
    for t in tracks():
        if only and t["file"] not in only:
            continue
        try:
            saved.append(download_one(t))
        except Exception as e:
            failed.append(str(e))
    for f in failed:
        print(f"FAILED: {f}", file=sys.stderr)
    if failed and not saved:
        raise RuntimeError("no track could be downloaded")
    return saved


if __name__ == "__main__":
    try:
        download_all(sys.argv[1:] or None)
    except Exception as e:
        print(f"Download failed: {e}", file=sys.stderr)
        sys.exit(1)
