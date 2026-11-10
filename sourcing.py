"""Find and download an official 16:9 source clip for a category (yt-dlp)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from categories import BLOCK_WORDS, MUSIC_BLOCK_WORDS, OFFICIAL_WORDS, STREAMING_CHANNELS

MIN_DUR = 60      # need enough footage for ~10 non-overlapping beat cuts
MAX_DUR = 600     # "under ~10 min"

# Fail-fast limits so a GitHub job never sits on a blocked IP until the 75-min cap.
SEARCH_TIMEOUT = 45
META_TIMEOUT = 25
DL_TIMEOUT = 50
WAYBACK_TIMEOUT = 40
MAX_CLIENT_TRIES = 3
YT_BLOCK_HITS_TO_SKIP = 2


class SourceError(RuntimeError):
    pass


def _word_re(words):
    return re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(w) for w in words) + r")(?![a-z0-9])", re.I)


_BLOCK = _word_re(BLOCK_WORDS)
_MUSIC_BLOCK = _word_re(MUSIC_BLOCK_WORDS)
_STREAMING = _word_re(STREAMING_CHANNELS)
_OFFICIAL = _word_re(OFFICIAL_WORDS)
_BOT_RE = re.compile(
    r"sign in to confirm|confirm you.?re not a bot|login_required|"
    r"HTTP Error 403|http error 403|bot.?check",
    re.I,
)

# One yt-dlp process can try several clients. Order comes from what still
# sometimes works on datacenter IPs in late 2026 without cookies (android_vr /
# web_embedded / tv do not always need a PO token; android/mweb may, and the
# bgutil plugin supplies one when the provider is running).
CLIENT_VARIANTS = [
    ["--extractor-args", "youtube:player_client=android_vr,web_embedded,tv,default"],
    ["--extractor-args", "youtube:player_client=android,mweb,tv_simply"],
    ["--extractor-args", "youtube:player_client=ios,web_safari"],
]

_youtube_block_hits = 0
_js_args_cache: list[str] | None = None


def youtube_is_blocked() -> bool:
    return _youtube_block_hits >= YT_BLOCK_HITS_TO_SKIP


def is_hard_block(err: BaseException | str) -> bool:
    return bool(_BOT_RE.search(str(err))) or "youtube_blocked" in str(err)


def _mark_youtube_block(log=print) -> None:
    global _youtube_block_hits
    _youtube_block_hits += 1
    if youtube_is_blocked():
        log("  YouTube looks blocked on this IP; skipping further YouTube downloads, trying fallbacks")


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


def _js_runtime_args() -> list[str]:
    global _js_args_cache
    if _js_args_cache is None:
        args: list[str] = []
        if shutil.which("deno"):
            args += ["--js-runtimes", "deno"]
        elif shutil.which("node"):
            args += ["--js-runtimes", "node"]
        _js_args_cache = args
    return list(_js_args_cache)


def _ytdlp_prefix(extra: list[str] | None = None) -> list[str]:
    """yt-dlp + JS runtime + common fail-fast flags, then optional extra args."""
    cmd = ytdlp_cmd() + _js_runtime_args() + [
        "--ignore-config", "--no-progress", "--no-warnings",
        "--socket-timeout", "15", "--retries", "2", "--fragment-retries", "2",
    ]
    if extra:
        cmd += extra
    return cmd


def is_streaming(e: dict) -> bool:
    """Streaming-platform channel or title (Netflix, Prime Video, JioHotstar...): their
    uploads carry a platform logo, so they are skipped."""
    return bool(_STREAMING.search(e.get("channel") or "") or _STREAMING.search(e.get("title") or ""))


def is_youtube(e: dict) -> bool:
    url = (e.get("url") or e.get("webpage_url") or "").lower()
    if any(s in url for s in ("dailymotion.com", "archive.org", "vimeo.com", "soundcloud.com", "dai.ly")):
        return False
    if "youtube.com" in url or "youtu.be" in url:
        return True
    vid = e.get("id") or ""
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{11}", vid))


def _safe_id(vid: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", vid)[:80]


def _entries_from_payload(data) -> list[dict]:
    if isinstance(data, list):
        raw = data
    elif isinstance(data, dict):
        if data.get("_type") == "playlist" or "entries" in data:
            raw = data.get("entries") or []
        else:
            raw = [data] if data.get("id") or data.get("webpage_url") else []
    else:
        return []
    out = []
    for e in raw:
        if not isinstance(e, dict):
            continue
        vid = e.get("id") or e.get("identifier")
        if not vid:
            url = e.get("webpage_url") or e.get("url") or ""
            m = re.search(r"(?:v=|youtu\.be/|video/)([A-Za-z0-9_-]+)", url)
            vid = m.group(1) if m else ""
        if not vid:
            continue
        url = e.get("webpage_url") or e.get("url") or ""
        out.append({
            "id": str(vid),
            "title": e.get("title"),
            "channel": e.get("channel") or e.get("uploader") or e.get("extractor"),
            "duration": e.get("duration"),
            "channel_is_verified": e.get("channel_is_verified"),
            "view_count": e.get("view_count") or e.get("downloads") or 0,
            "url": url,
            "extractor": e.get("extractor") or e.get("ie_key"),
        })
    return out


def search(query: str, n: int = 15, log=print, prefix: str | None = None) -> list[dict]:
    """Search. `prefix` is a yt-dlp search URL/spec; default is YouTube ytsearchN:."""
    if prefix is None:
        target = f"ytsearch{n}:{query}"
    else:
        target = prefix
    cmd = _ytdlp_prefix() + ["--flat-playlist", "--playlist-end", str(n), "-J", "--no-warnings", target]
    for attempt in range(1, 3):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=SEARCH_TIMEOUT)
            data = json.loads(r.stdout or "{}")
            if not isinstance(data, dict) and not isinstance(data, list):
                log(f"  search '{query}' returned invalid payload (try {attempt})")
                continue
            entries = _entries_from_payload(data)
            if entries:
                return entries
            log(f"  search '{query}' returned nothing (try {attempt})")
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            log(f"  search failed for '{query}' (try {attempt}): {e}")
        time.sleep(1 * attempt)
    return []


def acceptable(e: dict, must_any: list[str], avoid: list[str] | None = None,
               allow_unknown_duration: bool = False) -> tuple[bool, str]:
    title = e.get("title") or ""
    dur = e.get("duration") or 0
    if not dur and allow_unknown_duration:
        pass
    elif not (MIN_DUR <= dur <= MAX_DUR):
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
    if not is_youtube(e):
        s -= 0.4  # prefer official YouTube when both exist
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
    picked = good[offset:offset + limit]
    # Non-YouTube fallbacks (Dailymotion, archive.org) sit at the end so a
    # working YouTube download is still preferred.
    have = set(exclude or set()) | {e["id"] for e in picked}
    picked += alt_candidates(preset, exclude=have, limit=6, log=log)
    return picked


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


def _dailymotion_search(query: str, n: int = 10, log=print) -> list[dict]:
    """Dailymotion public search API (yt-dlp's HTML search extractor often returns 0)."""
    params = {
        "search": query,
        "fields": "id,title,duration,url,owner.screenname,views_total",
        "limit": str(n),
        "sort": "relevance",
    }
    api = "https://api.dailymotion.com/videos?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(api, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace") or "{}")
    except Exception as e:
        log(f"    dailymotion search failed: {e}")
        return []
    out = []
    for d in data.get("list") or []:
        if not isinstance(d, dict) or not d.get("id"):
            continue
        vid = str(d["id"])
        out.append({
            "id": vid,
            "title": d.get("title") or vid,
            "channel": d.get("owner.screenname") or "dailymotion",
            "duration": d.get("duration"),
            "channel_is_verified": False,
            "view_count": d.get("views_total") or 0,
            "url": d.get("url") or f"https://www.dailymotion.com/video/{vid}",
            "extractor": "dailymotion",
        })
    return out


def _archive_search(query: str, n: int = 8, log=print) -> list[dict]:
    """Internet Archive advanced search (yt-dlp has no archive.org search extractor)."""
    params = [
        ("q", f"({query}) AND mediatype:(movies)"),
        ("fl[]", "identifier"),
        ("fl[]", "title"),
        ("fl[]", "runtime"),
        ("fl[]", "downloads"),
        ("output", "json"),
        ("rows", str(n)),
        ("sort[]", "downloads desc"),
    ]
    url = "https://archive.org/advancedsearch.php?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace") or "{}")
    except Exception as e:
        log(f"    archive.org search failed: {e}")
        return []
    docs = (data.get("response") or {}).get("docs") or []
    out = []
    for d in docs:
        if not isinstance(d, dict) or not d.get("identifier"):
            continue
        ident = str(d["identifier"])
        dur = _parse_runtime(d.get("runtime"))
        out.append({
            "id": ident,
            "title": d.get("title") or ident,
            "channel": "archive.org",
            "duration": dur,
            "channel_is_verified": False,
            "view_count": d.get("downloads") or 0,
            "url": f"https://archive.org/details/{urllib.parse.quote(ident)}",
            "extractor": "archive.org",
        })
    return out


def _parse_runtime(val) -> float | None:
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        # archive.org sometimes stores minutes, sometimes seconds; prefer seconds if large
        v = float(val)
        return v if v > 20 else v * 60
    s = str(val).strip()
    m = re.match(r"^(?:(\d+):)?(\d+):(\d+)$", s)
    if m:
        h, mi, sec = (int(m.group(1) or 0), int(m.group(2)), int(m.group(3)))
        return h * 3600 + mi * 60 + sec
    try:
        return float(s)
    except ValueError:
        return None


def alt_candidates(preset: dict, exclude: set[str] | None = None, limit: int = 6, log=print) -> list[dict]:
    """Dailymotion + archive.org results, using the same category queries."""
    exclude = exclude or set()
    seen, good = set(), []
    avoid = list(preset.get("avoid") or []) + list(preset.get("avoid_extra") or [])
    queries = (preset.get("queries") or [])[:2]
    for qi, q in enumerate(queries):
        log(f"  alt search (dailymotion): {q}")
        for e in _dailymotion_search(q, n=10, log=log):
            e["_q"] = qi
            _consider_alt(e, preset, avoid, exclude, seen, good, log)
        log(f"  alt search (archive.org): {q}")
        for e in _archive_search(q, n=8, log=log):
            e["_q"] = qi
            _consider_alt(e, preset, avoid, exclude, seen, good, log)
        if len(good) >= limit:
            break
    good.sort(key=lambda e: -rank(e, preset.get("prefer")))
    return good[:limit]


def _consider_alt(e, preset, avoid, exclude, seen, good, log) -> None:
    vid = e["id"]
    if vid in seen or vid in exclude:
        return
    seen.add(vid)
    ok, why = acceptable(e, preset.get("must_any") or [], avoid, allow_unknown_duration=True)
    if ok:
        good.append(e)
    else:
        log(f"    skip {vid} ({why}): {(e.get('title') or '')[:70]}")


def download(entry: dict, dest_dir: Path, max_height: int = 1080, log=print) -> Path:
    """Download one result at <= max_height. Prefers H.264 mp4. Raises SourceError."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    vid = entry["id"]
    url = entry.get("url") or entry.get("webpage_url") or ""
    if not url.startswith("http"):
        url = f"https://www.youtube.com/watch?v={vid}" if is_youtube(entry) else url
        entry = {**entry, "url": url}
    out = dest_dir / f"{_safe_id(vid)}_{max_height}p.mp4"
    if out.exists() and out.stat().st_size > 500_000:
        return out
    fmt = (
        f"bv*[height<={max_height}][vcodec^=avc1]+ba[ext=m4a]/"
        f"bv*[height<={max_height}]+ba/b[height<={max_height}]/b"
    )
    if is_youtube(entry) and youtube_is_blocked():
        return _try_wayback(entry, dest_dir, out, fmt, log)
    log(f"  download {max_height}p: {entry.get('title')} [{url}]")
    try:
        return _run_variants(url, out, dest_dir, out.stem, fmt, log, youtube=is_youtube(entry))
    except SourceError as e:
        if is_youtube(entry) and is_hard_block(e):
            try:
                return _try_wayback(entry, dest_dir, out, fmt, log)
            except SourceError:
                pass
        raise


def _try_wayback(entry: dict, dest_dir: Path, out: Path, fmt: str, log) -> Path:
    vid = entry["id"]
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
        raise SourceError(f"youtube_blocked: {vid}")
    url = f"ytarchive:{vid}"
    log(f"  wayback fallback: {url}")
    cmd = _ytdlp_prefix(["--no-playlist", "-f", fmt, "--merge-output-format", "mp4", "-o", str(out), url])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=WAYBACK_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise SourceError(f"youtube_blocked (wayback timeout): {vid}")
    if r.returncode == 0 and out.exists() and out.stat().st_size > 500_000:
        log("    ok via web.archive.org")
        return out
    last = ((r.stderr or "").strip().splitlines() or ["?"])[-1][:160]
    for p in dest_dir.glob(f"{out.stem}*"):
        p.unlink(missing_ok=True)
    raise SourceError(f"youtube_blocked (wayback failed: {last}): {vid}")


def _run_variants(url: str, out: Path, dest_dir: Path, stem: str, fmt: str, log,
                  min_bytes=500_000, youtube: bool = True) -> Path:
    """Run a yt-dlp download, retrying with other player clients. Fail fast on bot-checks."""
    last = "?"
    variants = CLIENT_VARIANTS[:MAX_CLIENT_TRIES] if youtube else [[]]
    bot_hits = 0
    for i, extra in enumerate(variants):
        cmd = _ytdlp_prefix(extra + ["--no-playlist", "-f", fmt, "--merge-output-format", "mp4",
                                     "--retries", "2", "-o", str(out), url])
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=DL_TIMEOUT)
        except subprocess.TimeoutExpired:
            last = "timeout"
            log(f"    yt-dlp variant {i} failed: timeout")
            continue
        if r.returncode == 0 and out.exists() and out.stat().st_size > min_bytes:
            if i:
                log(f"    ok with client variant {i}: {' '.join(extra)}")
            return out
        last = ((r.stderr or r.stdout or "").strip().splitlines() or ["?"])[-1][:160]
        for p in dest_dir.glob(f"{stem}*"):
            p.unlink(missing_ok=True)
        log(f"    yt-dlp variant {i} failed: {last}")
        if is_hard_block(last):
            bot_hits += 1
            if bot_hits >= 2:
                # IP-level bot wall: more clients on the same runner almost never help.
                _mark_youtube_block(log)
                raise SourceError(f"youtube_blocked ({last})")
        time.sleep(1)
    if is_hard_block(last):
        _mark_youtube_block(log)
        raise SourceError(f"youtube_blocked ({last})")
    raise SourceError(f"download failed with all client variants ({last})")


# ---------------------------------------------------------------- music (songs)
def song_candidates(preset: dict, exclude: set[str] | None = None, limit: int = 4, log=print) -> list[dict]:
    """Popular / trending songs for the category: official or high-view audio, 1.5-10 min."""
    exclude = exclude or set()
    seen, good = set(), []
    prefer = preset.get("song_prefer") or []
    queries = list(preset.get("song_queries") or [])
    for qi, q in enumerate(queries):
        log(f"  song search: {q}")
        for e in search(q, n=12, log=log):
            _consider_song(e, qi, prefer, exclude, seen, good)
        if len(good) >= limit * 2:
            break
    # SoundCloud + Dailymotion if YouTube returned little (or will fail to download).
    if len(good) < limit:
        for qi, q in enumerate(queries[:2]):
            log(f"  song search (soundcloud): {q}")
            for e in search(q, n=8, log=log, prefix=f"scsearch8:{q}"):
                _consider_song(e, qi + 10, prefer, exclude, seen, good, loose=True)
            log(f"  song search (dailymotion): {q}")
            for e in _dailymotion_search(q, n=8, log=log):
                _consider_song(e, qi + 10, prefer, exclude, seen, good, loose=True)
    good.sort(key=lambda e: -e["_score"])
    return good[:limit]


def _consider_song(e, qi, prefer, exclude, seen, good, loose: bool = False) -> None:
    vid = e["id"]
    if vid in seen or vid in exclude:
        return
    seen.add(vid)
    title = e.get("title") or ""
    dur = e.get("duration") or 0
    if dur and not (90 <= dur <= 600):
        return
    if not dur and not loose:
        return
    if _MUSIC_BLOCK.search(title):
        return
    views = e.get("view_count") or 0
    if not loose and views < 200_000 and not e.get("channel_is_verified"):
        return
    e["_score"] = (min(views / 1e6, 400) ** 0.5 + (3 if e.get("channel_is_verified") else 0)
                   + (3 if prefer and _word_re(prefer).search(f"{title} {e.get('channel') or ''}") else 0)
                   - 1.0 * qi)
    good.append(e)


def download_audio(entry: dict, dest_dir: Path, log=print) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    vid = entry["id"]
    out = dest_dir / f"{_safe_id(vid)}.m4a"
    if out.exists() and out.stat().st_size > 300_000:
        return out
    url = entry.get("url") or ""
    if not url.startswith("http"):
        url = f"https://www.youtube.com/watch?v={vid}" if is_youtube(entry) else url
    if is_youtube(entry) and youtube_is_blocked():
        # Don't burn time on a blocked IP; caller falls back to local tracks.
        raise SourceError(f"youtube_blocked: {vid}")
    log(f"  song download: {entry.get('title')} [{url}]")
    fmt = "ba[ext=m4a]/ba/b"
    try:
        return _run_variants(url, out, dest_dir, out.stem, fmt, log,
                             min_bytes=300_000, youtube=is_youtube(entry))
    except SourceError:
        if is_youtube(entry):
            raise
        raise


def entry_from_id(vid_or_url: str, log=print) -> dict | None:
    """Metadata for one YouTube id/URL (used for --source-url and preset seed ids).

    If yt-dlp -J returns null / a blocked player response, a stub entry is still
    returned so the later download can try player-client fallbacks or wayback.
    """
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", vid_or_url)
    vid = m.group(1) if m else vid_or_url.strip()
    url = vid_or_url if vid_or_url.startswith("http") else f"https://www.youtube.com/watch?v={vid}"
    stub = {"id": vid, "title": vid, "channel": None, "duration": None,
            "channel_is_verified": False, "view_count": 0, "url": url, "_stub": True}
    if youtube_is_blocked():
        log(f"  could not read metadata for {vid}; using stub")
        return stub
    cmd = _ytdlp_prefix(CLIENT_VARIANTS[0] + ["--no-playlist", "-J", "--skip-download", "--no-warnings", url])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=META_TIMEOUT)
        d = json.loads(r.stdout or "{}")
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        d = None
    if isinstance(d, dict) and d.get("id"):
        return {"id": d["id"], "title": d.get("title"), "channel": d.get("channel"),
                "duration": d.get("duration"), "channel_is_verified": d.get("channel_is_verified"),
                "view_count": d.get("view_count"), "url": url}
    log(f"  could not read metadata for {vid}; using stub")
    return stub
