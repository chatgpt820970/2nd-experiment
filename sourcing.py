"""Find and download an official 16:9 source clip for a category (yt-dlp)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from categories import BLOCK_WORDS, OFFICIAL_WORDS

MIN_DUR = 60      # need enough footage for ~10 non-overlapping beat cuts
MAX_DUR = 600     # "under ~10 min"


class SourceError(RuntimeError):
    pass


def _word_re(words):
    return re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(w) for w in words) + r")(?![a-z0-9])", re.I)


_BLOCK = _word_re(BLOCK_WORDS)
_OFFICIAL = _word_re(OFFICIAL_WORDS)


def ytdlp_cmd() -> list[str]:
    """Return a yt-dlp command, installing it with pip if missing."""
    exe = shutil.which("yt-dlp")
    if exe:
        return [exe]
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        print("yt-dlp missing, installing with pip…")
        subprocess.run([sys.executable, "-m", "pip", "install", "--user", "-q", "-U", "yt-dlp"], check=False)
        exe = shutil.which("yt-dlp")
        if exe:
            return [exe]
    return [sys.executable, "-m", "yt_dlp"]


def search(query: str, n: int = 15, log=print) -> list[dict]:
    cmd = ytdlp_cmd() + ["--flat-playlist", "-J", "--no-warnings", f"ytsearch{n}:{query}"]
    for attempt in range(1, 4):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            data = json.loads(r.stdout or "{}")
            entries = [e for e in data.get("entries") or [] if e and e.get("id")]
            if entries:
                return entries
            log(f"  search '{query}' returned nothing (try {attempt})")
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            log(f"  search failed for '{query}' (try {attempt}): {e}")
        time.sleep(3 * attempt)
    return []


def acceptable(e: dict, must_any: list[str], avoid: list[str] | None = None) -> tuple[bool, str]:
    title = e.get("title") or ""
    dur = e.get("duration") or 0
    if not (MIN_DUR <= dur <= MAX_DUR):
        return False, f"duration {dur}s"
    if _BLOCK.search(title):
        return False, f"blocked word '{_BLOCK.search(title).group(0)}'"
    if avoid and _word_re(avoid).search(title):
        return False, f"avoid word '{_word_re(avoid).search(title).group(0)}'"
    if must_any and not _word_re(must_any).search(title):
        return False, "not an official trailer/teaser/highlights title"
    return True, "ok"


def rank(e: dict, prefer: list[str] | None = None) -> float:
    s = -0.6 * e.get("_q", 0)  # earlier queries are the better match
    if prefer:
        text = f"{e.get('title') or ''} {e.get('channel') or ''}"
        s += 2.0 * len(set(m.lower() for m in _word_re(prefer).findall(text)))
    if e.get("channel_is_verified"):
        s += 3
    s += 1.0 * len(_OFFICIAL.findall(e.get("title") or ""))
    s += min((e.get("view_count") or 0) / 1e6, 5) * 0.3
    return s


def candidates(preset: dict, exclude: set[str] | None = None, limit: int = 8, log=print) -> list[dict]:
    """Ranked, filtered results. Self-heals: a strict pass (verified channel +
    official title words), then a relaxed pass (those dropped unless the preset
    sets verified_only; block words and duration limits always apply)."""
    good = _candidates(preset, exclude, limit, log, strict=True)
    if not good:
        log("  no strict match, retrying search with relaxed title rule…")
        good = _candidates(preset, exclude, limit, log, strict=False)
    return good


def _candidates(preset, exclude, limit, log, strict: bool) -> list[dict]:
    exclude = exclude or set()
    seen, good = set(), []
    avoid = list(preset.get("avoid") or []) + list(preset.get("avoid_extra") or [])
    for qi, q in enumerate(preset["queries"]):
        log(f"  search: {q}")
        for e in search(q, log=log):
            vid = e["id"]
            if vid in seen or vid in exclude:
                continue
            seen.add(vid)
            e["_q"] = qi
            ok, why = acceptable(e, preset.get("must_any", []) if strict else [], avoid)
            need_verified = strict or preset.get("verified_only")
            if ok and need_verified and not e.get("channel_is_verified"):
                ok, why = False, "channel not verified"
            chans = preset.get("channels_only")
            if ok and strict and chans and not any(
                    c.lower() in (e.get("channel") or "").lower() for c in chans):
                ok, why = False, "not an official channel for this category"
            if ok:
                good.append(e)
            else:
                log(f"    skip {vid} ({why}): {(e.get('title') or '')[:70]}")
        if len(good) >= limit:
            break
    good.sort(key=lambda e: -rank(e, preset.get("prefer")))
    return good[:limit]


def download(entry: dict, dest_dir: Path, max_height: int = 1080, log=print) -> Path:
    """Download one result at <= max_height. Prefers H.264 mp4. Raises SourceError."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    vid = entry["id"]
    url = entry.get("url") or f"https://www.youtube.com/watch?v={vid}"
    if not url.startswith("http"):
        url = f"https://www.youtube.com/watch?v={vid}"
    out = dest_dir / f"{vid}_{max_height}p.mp4"
    if out.exists() and out.stat().st_size > 500_000:
        return out
    fmt = (
        f"bv*[height<={max_height}][vcodec^=avc1]+ba[ext=m4a]/"
        f"bv*[height<={max_height}]+ba/b[height<={max_height}]"
    )
    cmd = ytdlp_cmd() + [
        "-f", fmt, "--merge-output-format", "mp4", "--no-playlist",
        "--no-progress", "--no-warnings", "--retries", "5", "--fragment-retries", "10",
        "-o", str(out), url,
    ]
    log(f"  download {max_height}p: {entry.get('title')} [{url}]")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        raise SourceError(f"download timed out: {url}")
    if r.returncode != 0 or not out.exists() or out.stat().st_size < 500_000:
        tail = (r.stderr or "").strip().splitlines()[-1:] or ["?"]
        for p in dest_dir.glob(f"{vid}_{max_height}p*"):
            p.unlink(missing_ok=True)
        raise SourceError(f"download failed ({tail[0][:160]}): {url}")
    return out
