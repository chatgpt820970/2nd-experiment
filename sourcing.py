"""Find and download an official 16:9 source clip for a category (yt-dlp)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from categories import BLOCK_WORDS, MUSIC_BLOCK_WORDS, OFFICIAL_WORDS, STREAMING_CHANNELS

MIN_DUR = 60      # need enough footage for ~10 non-overlapping beat cuts
MAX_DUR = 600     # "under ~10 min"


class SourceError(RuntimeError):
    pass


def _word_re(words):
    return re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(w) for w in words) + r")(?![a-z0-9])", re.I)


_BLOCK = _word_re(BLOCK_WORDS)
_MUSIC_BLOCK = _word_re(MUSIC_BLOCK_WORDS)
_STREAMING = _word_re(STREAMING_CHANNELS)

# yt-dlp variants tried in order when YouTube bot-blocks a client (common on CI runners).
CLIENT_VARIANTS = [
    [],
    ["--extractor-args", "youtube:player_client=web_safari,web"],
    ["--extractor-args", "youtube:player_client=tv,web_embedded"],
    ["--extractor-args", "youtube:player_client=mweb"],
    ["--extractor-args", "youtube:player_client=ios"],
    ["--js-runtimes", "node", "--extractor-args", "youtube:player_client=web_safari"],
]
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


def is_streaming(e: dict) -> bool:
    """Streaming-platform channel or title (Netflix, Prime Video, JioHotstar...): their
    uploads carry a platform logo, so they are skipped."""
    return bool(_STREAMING.search(e.get("channel") or "") or _STREAMING.search(e.get("title") or ""))


def search(query: str, n: int = 15, log=print) -> list[dict]:
    cmd = ytdlp_cmd() + ["--flat-playlist", "-J", "--no-warnings", f"ytsearch{n}:{query}"]
    for attempt in range(1, 4):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            data = json.loads(r.stdout or "{}")
            if not isinstance(data, dict):
                log(f"  search '{query}' returned invalid payload (try {attempt})")
                continue
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
    if is_streaming(e):
        return False, "streaming-platform upload (platform logo)"
    text = f"{title} | {e.get('channel') or ''}"
    if avoid and _word_re(avoid).search(text):
        return False, f"avoid word '{_word_re(avoid).search(text).group(0)}'"
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


def candidates(preset: dict, exclude: set[str] | None = None, limit: int = 8, log=print,
               offset: int = 0) -> list[dict]:
    """Ranked, filtered results. Self-heals: a strict pass (verified channel +
    official title words), then a relaxed pass (those dropped unless the preset
    sets verified_only; block words and duration limits always apply)."""
    good = _candidates(preset, exclude, limit + offset, log, strict=True)
    if len(good) <= offset:
        log("  not enough strict matches, retrying search with relaxed title rule…")
        good = _candidates(preset, exclude, limit + offset, log, strict=False)
    return good[offset:offset + limit]


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
    return good


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
    base = ytdlp_cmd() + [
        "-f", fmt, "--merge-output-format", "mp4", "--no-playlist",
        "--no-progress", "--no-warnings", "--retries", "5", "--fragment-retries", "10",
        "-o", str(out), url,
    ]
    log(f"  download {max_height}p: {entry.get('title')} [{url}]")
    return _run_variants(base, out, vid, dest_dir, f"{vid}_{max_height}p", log)


def _run_variants(base: list[str], out: Path, vid: str, dest_dir: Path, stem: str, log, min_bytes=500_000):
    """Run a yt-dlp download, retrying with other player clients and a back-off sleep."""
    last = "?"
    for i, extra in enumerate(CLIENT_VARIANTS):
        cmd = base[:1] + extra + (["--sleep-requests", "1"] if i else []) + base[1:]
        if base[0] == sys.executable:  # "python -m yt_dlp" form
            cmd = base[:3] + extra + base[3:]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        except subprocess.TimeoutExpired:
            last = "timeout"
            continue
        if r.returncode == 0 and out.exists() and out.stat().st_size > min_bytes:
            if i:
                log(f"    ok with client variant {i}: {' '.join(extra)}")
            return out
        last = ((r.stderr or "").strip().splitlines() or ["?"])[-1][:160]
        for p in dest_dir.glob(f"{stem}*"):
            p.unlink(missing_ok=True)
        log(f"    yt-dlp variant {i} failed: {last}")
        time.sleep(2 + 3 * i)
    raise SourceError(f"download failed with all client variants ({last}): {vid}")


# ---------------------------------------------------------------- music (songs)
def song_candidates(preset: dict, exclude: set[str] | None = None, limit: int = 4, log=print) -> list[dict]:
    """Popular / trending songs for the category: official or high-view audio, 1.5-10 min."""
    exclude = exclude or set()
    seen, good = set(), []
    prefer = preset.get("song_prefer") or []
    for qi, q in enumerate(preset.get("song_queries") or []):
        log(f"  song search: {q}")
        for e in search(q, n=12, log=log):
            vid = e["id"]
            if vid in seen or vid in exclude:
                continue
            seen.add(vid)
            title = e.get("title") or ""
            dur = e.get("duration") or 0
            if not (90 <= dur <= 600) or _MUSIC_BLOCK.search(title):
                continue
            views = e.get("view_count") or 0
            if views < 200_000 and not e.get("channel_is_verified"):
                continue
            e["_score"] = (min(views / 1e6, 400) ** 0.5 + (3 if e.get("channel_is_verified") else 0)
                           + (3 if prefer and _word_re(prefer).search(f"{title} {e.get('channel') or ''}") else 0)
                           - 1.0 * qi)
            good.append(e)
        if len(good) >= limit * 2:
            break
    good.sort(key=lambda e: -e["_score"])
    return good[:limit]


def download_audio(entry: dict, dest_dir: Path, log=print) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    vid = entry["id"]
    out = dest_dir / f"{vid}.m4a"
    if out.exists() and out.stat().st_size > 300_000:
        return out
    url = f"https://www.youtube.com/watch?v={vid}"
    base = ytdlp_cmd() + ["-f", "ba[ext=m4a]/ba", "--no-playlist", "--no-progress", "--no-warnings",
                          "--retries", "5", "-o", str(out), url]
    log(f"  song download: {entry.get('title')} [{url}]")
    return _run_variants(base, out, vid, dest_dir, vid, log, min_bytes=300_000)


def entry_from_id(vid_or_url: str, log=print) -> dict | None:
    """Metadata for one YouTube id/URL (used for --source-url and preset seed ids)."""
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", vid_or_url)
    vid = m.group(1) if m else vid_or_url.strip()
    url = f"https://www.youtube.com/watch?v={vid}"
    for extra in CLIENT_VARIANTS[:3]:
        cmd = ytdlp_cmd()[:1] + extra + ytdlp_cmd()[1:] + ["-J", "--skip-download", "--no-warnings", url]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            d = json.loads(r.stdout or "{}")
        except (subprocess.TimeoutExpired, json.JSONDecodeError):
            continue
        if isinstance(d, dict) and d.get("id"):
            return {"id": d["id"], "title": d.get("title"), "channel": d.get("channel"),
                    "duration": d.get("duration"), "channel_is_verified": d.get("channel_is_verified"),
                    "view_count": d.get("view_count"), "url": url}
    log(f"  could not read metadata for {vid}")
    return None
