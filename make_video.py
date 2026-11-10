#!/usr/bin/env python3
"""Render a 9:16 Short from a 16:9 source clip.

No on-screen captions and no watermark. The full source frame is scaled
to 1080 wide (no crop), placed under a tight white hook banner, and the
banner+frame block is centered on a blurred 1080x1920 canvas. Beat-synced
cuts on a royalty-free (NCS / Kevin MacLeod) track, then QC at 1 fps.

v2: --category presets, --auto source fetching (yt-dlp), and a self-healing
fallback loop (next source, re-download at lower resolution, next music
track, repeated QC blacklisting, brighter background) with a run log.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import math
import re
import subprocess
import sys
import traceback
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import categories  # noqa: E402
import sourcing  # noqa: E402
from sourcing import SourceError  # noqa: E402

MUSIC_META = ROOT / "assets" / "music.json"
MUSIC_DIR = ROOT / "assets" / "music"
DEFAULT_FONT = ROOT / "fonts" / "ArchivoBlack-Regular.ttf"
FALLBACK_FONTS = [
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
]
DEVANAGARI_FONTS = [
    Path("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf"),
    *Path("/usr/share/fonts").rglob("NotoSansDevanagari*.ttf"),
]

MAX_SKIP_HEAD = 9.0
MAX_SKIP_TAIL = 16.0
DEFAULT_CUT_S = 2.33
DEFAULT_TARGET_S = 25.7
DEFAULT_BPM = 129.0
MIN_LEN, MAX_LEN = 20.0, 40.0
REVEAL_INDEX = 5
DEFAULT_HOOK = "Nobody was ready\nfor Fool Night"
DEFAULT_TRACK = "ncs_lavida.mp3"

CANVAS_W = 1080
CANVAS_H = 1920
BANNER_H = 240
MAX_PLATE_H = CANVAS_H - BANNER_H - 160
QC_ROUNDS = 3          # render + up to 2 blacklist re-renders per source/track
MIN_AUDIO_DB = -45.0   # mean volume below this = silent / broken music


class RenderError(RuntimeError):
    """A render step failed; another music track or resolution may fix it."""


# ---------------------------------------------------------------- logging
class Tee:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.f = path.open("a", encoding="utf-8")
        self.out = sys.__stdout__

    def write(self, s):
        self.out.write(s)
        self.f.write(s)
        self.f.flush()

    def flush(self):
        self.out.flush()
        self.f.flush()


def log(msg: str = ""):
    print(msg, flush=True)


def run(cmd, timeout: int = 1800, quiet: bool = True):
    log("  $ " + " ".join(str(c) for c in cmd[:12]) + (" ..." if len(cmd) > 12 else ""))
    try:
        r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RenderError(f"timeout after {timeout}s: {cmd[0]}")
    except FileNotFoundError:
        raise RenderError(f"program not found: {cmd[0]} (install ffmpeg)")
    if r.returncode != 0:
        tail = "\n".join((r.stderr or "").strip().splitlines()[-6:])
        raise RenderError(f"{cmd[0]} failed ({r.returncode}):\n{tail}")
    return r


# ---------------------------------------------------------------- probing
def ffprobe_json(path: Path, *args) -> dict:
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", *args, "-of", "json", str(path)], text=True, timeout=60
        )
        return json.loads(out or "{}")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        raise SourceError(f"ffprobe could not read {path.name}: {e}")


def probe_video(path: Path) -> dict:
    d = ffprobe_json(path, "-select_streams", "v:0",
                     "-show_entries", "stream=width,height:format=duration")
    st = (d.get("streams") or [{}])[0]
    try:
        w, h = int(st["width"]), int(st["height"])
        dur = float(d["format"]["duration"])
    except (KeyError, ValueError, TypeError):
        raise SourceError(f"{path.name}: no readable video stream")
    return {"w": w, "h": h, "dur": dur}


def probe_duration(path: Path) -> float:
    d = ffprobe_json(path, "-show_entries", "format=duration")
    try:
        return float(d["format"]["duration"])
    except (KeyError, ValueError, TypeError):
        raise RenderError(f"{path.name}: unreadable duration")


def detect_active(source: Path, dur: float, w: int, h: int) -> dict:
    """Find letterbox bars (black rows top/bottom). Returns active rows {y, h}.

    The plate still shows the FULL frame (bars included, nothing cropped);
    the active box is only used so the blurred background is not built from
    black bars and so dark-frame QC measures the real picture.
    """
    found = []
    for frac in (0.25, 0.45, 0.65):
        try:
            r = subprocess.run(
                ["ffmpeg", "-v", "info", "-ss", f"{dur * frac:.2f}", "-i", str(source), "-t", "6",
                 "-vf", "cropdetect=limit=24:round=2:reset=0", "-an", "-f", "null", "-"],
                capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            continue
        m = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", r.stderr or "")
        if m:
            cw, ch, cx, cy = map(int, m[-1])
            found.append((ch, cy))
    if not found:
        return {"y": 0, "h": h}
    ch, cy = max(found)  # largest active height seen = least aggressive
    if ch >= h * 0.97 or ch < h * 0.5:
        return {"y": 0, "h": h}
    return {"y": cy, "h": ch}


def even(x: float) -> int:
    return max(2, int(round(x / 2.0)) * 2)


def layout_for(src_w: int, src_h: int, active: dict | None = None) -> dict:
    """Full frame, no crop. 16:9 -> 1080x608. Taller sources are fit by height."""
    fg_w, fg_h = CANVAS_W, even(src_h * CANVAS_W / src_w)
    if fg_h > MAX_PLATE_H:
        fg_h = MAX_PLATE_H
        fg_w = min(CANVAS_W, even(src_w * MAX_PLATE_H / src_h))
    block_h = BANNER_H + fg_h
    block_y = (CANVAS_H - block_h) // 2
    active = active or {"y": 0, "h": src_h}
    k = fg_h / src_h
    return {
        "src_w": src_w, "src_h": src_h, "act_src_y": active["y"], "act_src_h": active["h"],
        "act_y": block_y + BANNER_H + int(round(active["y"] * k)),
        "act_h": int(round(active["h"] * k)),
        "fg_w": fg_w, "fg_h": fg_h, "banner_h": BANNER_H, "block_h": block_h,
        "block_y": block_y, "banner_y": block_y, "plate_y": block_y + BANNER_H,
        "plate_h": fg_h, "plate_x": (CANVAS_W - fg_w) // 2,
    }


# ---------------------------------------------------------------- music
def music_tracks() -> list[dict]:
    if not MUSIC_META.exists():
        return []
    return json.loads(MUSIC_META.read_text())["tracks"]


def load_music_meta(music: Path) -> dict | None:
    return next((t for t in music_tracks() if t["file"] == music.name), None)


def ensure_track(name_or_path: str | Path) -> Path:
    """Return a playable track path, downloading it from music.json if needed."""
    p = Path(name_or_path).expanduser()
    if p.exists() and p.stat().st_size > 100_000:
        return p.resolve()
    meta = next((t for t in music_tracks() if t["file"] == p.name), None)
    dest = MUSIC_DIR / p.name
    if dest.exists() and dest.stat().st_size > 100_000:
        return dest
    if not meta:
        raise RenderError(f"music not found and not in music.json: {name_or_path}")
    sys.path.insert(0, str(ROOT / "scripts"))
    import download_music  # noqa: E402
    try:
        return download_music.download_one(meta)
    except Exception as e:
        raise RenderError(f"music download failed for {p.name}: {e}")


def decode_wav(music: Path, wav_path: Path) -> Path:
    run(["ffmpeg", "-y", "-v", "error", "-i", music, "-ac", "1", "-ar", "22050", wav_path])
    return wav_path


def find_drop(wav: Path) -> float:
    with wave.open(str(wav), "rb") as w:
        sr = w.getframerate()
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    hop, win = int(sr * 0.05), int(sr * 0.25)
    if len(audio) < win * 20:
        raise RenderError(f"music too short / empty ({len(audio) / sr:.1f}s)")
    rms = np.array([np.sqrt(np.mean(audio[i:i + win] ** 2)) for i in range(0, len(audio) - win, hop)])
    if float(rms.max()) < 1e-3:
        raise RenderError("music is silent")
    sm = np.convolve(rms, np.ones(10) / 10, mode="same")
    look = int(0.5 / 0.05)
    delta = sm[look:] - sm[:-look]
    limit = min(len(delta), int(40 / 0.05))
    land = sm[look:look + limit]
    score = delta[:limit] * (0.4 + land / (land.max() + 1e-6))
    idx = int(np.argmax(score))
    drop_t = (idx + look) * 0.05
    log(f"Music drop @ {drop_t:.2f}s")
    return drop_t


# ---------------------------------------------------------------- frames / scoring
def extract_frames(source: Path, frames_dir: Path, head: float, usable: float, layout: dict) -> int:
    frames_dir.mkdir(parents=True, exist_ok=True)
    for p in frames_dir.glob("*.jpg"):
        p.unlink()
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{head}", "-i", source, "-t", f"{usable:.4f}",
         "-vf", f"crop=iw:{layout['act_src_h']}:0:{layout['act_src_y']},fps=2,scale=960:-2",
         "-q:v", "3", frames_dir / "%04d.jpg"])
    n = len(list(frames_dir.glob("*.jpg")))
    if n < 20:
        raise SourceError(f"only {n} frames could be decoded from source")
    log(f"Extracted {n} frames (2 fps, active picture) from {head:.1f}s")
    return n


def luma(im: np.ndarray) -> np.ndarray:
    return 0.299 * im[:, :, 0] + 0.587 * im[:, :, 1] + 0.114 * im[:, :, 2]


def score_frame(im: np.ndarray, prev: np.ndarray | None) -> dict:
    y = luma(im.astype(np.float32))
    dark = float((y < 25).mean())
    red = float(((im[:, :, 0] > 150) & (im[:, :, 1] < 50) & (im[:, :, 2] < 50)).mean())
    h, w = y.shape
    cy0, cy1, cx0, cx1 = int(h * 0.3), int(h * 0.7), int(w * 0.3), int(w * 0.7)
    edge = np.abs(np.diff(y, axis=1, prepend=y[:, :1])) + np.abs(np.diff(y, axis=0, prepend=y[:1, :]))
    center_edge = float(edge[cy0:cy1, cx0:cx1].mean())
    mask = np.ones(y.shape, dtype=bool)
    mask[cy0:cy1, cx0:cx1] = False
    outer_edge = float(edge[mask].mean())
    outer_std = float(y[mask].std())
    text_card = bool(center_edge > 18.0 and outer_edge < 8.0 and outer_std < 28.0)
    flat = bool(float(y.std()) < 6.0)  # solid colour card / fade
    reject = dark > 0.45 or red > 0.35 or text_card or flat
    motion = 0.0
    if prev is not None and prev.shape == im.shape:
        motion = float(np.mean(np.abs(y - luma(prev.astype(np.float32)))))
    spectacle = ((1.0 - min(dark, 1.0)) * 40 + min(motion, 40) * 1.2
                 + float(y.std()) * 0.4 + min(center_edge, 25) * 0.3)
    reasons = []
    if dark > 0.45:
        reasons.append(f"dark={dark:.2f}")
    if red > 0.35:
        reasons.append(f"red={red:.2f}")
    if text_card:
        reasons.append(f"textcard ce={center_edge:.1f} oe={outer_edge:.1f}")
    if flat:
        reasons.append("flat")
    return {"dark": dark, "red": red, "text_card": text_card, "motion": motion,
            "mean": float(y.mean()), "spectacle": -1.0 if reject else spectacle,
            "reject": reject, "reasons": reasons}


def score_all(frames_dir: Path, head: float) -> list[dict]:
    """One row per source second; a second is rejected if EITHER half-second sample is bad."""
    files = sorted(frames_dir.glob("*.jpg"))
    halves, prev = [], None
    for fp in files:
        im = np.array(Image.open(fp).convert("RGB"))
        halves.append(score_frame(im, prev))
        prev = im
    rows = []
    for i in range(0, len(halves) - 1, 2):
        a, b = halves[i], halves[i + 1]
        d = dict(a)
        d["reject"] = a["reject"] or b["reject"]
        d["reasons"] = a["reasons"] + b["reasons"]
        d["spectacle"] = -1.0 if d["reject"] else min(a["spectacle"], b["spectacle"])
        d["mean"] = (a["mean"] + b["mean"]) / 2
        d["t"] = head + i // 2
        rows.append(d)
    ok = sum(1 for r in rows if not r["reject"])
    log(f"Scored {len(rows)} seconds: {ok} usable, {len(rows) - ok} rejected")
    return rows


def window_ok(rows_by_t: dict, start: float, dur: float) -> tuple[bool, float]:
    specs, tt, end = [], math.floor(start), start + dur - 1e-6
    while tt < end:
        row = rows_by_t.get(tt)
        if row is None or row["reject"]:
            return False, -1.0
        specs.append(row["spectacle"])
        tt += 1
    return True, float(min(specs) + 0.35 * (sum(specs) / len(specs)))


def pick_edl(rows, head, usable_end, clip_dur, n_clips, blacklist=None) -> list[dict]:
    blacklist = blacklist or set()
    rows_by_t = {int(round(r["t"])): r for r in rows}
    cands, t = [], head
    while t + clip_dur <= usable_end - 0.05:
        ok, sc = window_ok(rows_by_t, t, clip_dur)
        secs = range(math.floor(t), math.ceil(t + clip_dur))
        if ok and not any(s in blacklist for s in secs):
            cands.append({"src_start": round(t, 3), "src_end": round(t + clip_dur, 3), "score": sc})
        t += 0.5
    cands.sort(key=lambda c: -c["score"])
    picked = []
    for gap in (7.0, 5.0, clip_dur + 0.05):  # prefer spread-out shots
        for c in cands:
            if len(picked) == n_clips:
                break
            if any(abs(c["src_start"] - p["src_start"]) < gap for p in picked):
                continue
            picked.append(c)
    if len(picked) < n_clips:
        raise SourceError(f"only {len(picked)} clean non-overlapping clips, need {n_clips}")
    reveal_i = min(REVEAL_INDEX, n_clips - 1)
    reveal = max(picked, key=lambda c: c["score"])
    rest = sorted([c for c in picked if c is not reveal], key=lambda c: c["src_start"])
    edl = rest[:reveal_i] + [reveal] + rest[reveal_i:]
    for i, c in enumerate(edl):
        c.update(i=i, t0=i * clip_dur, t1=(i + 1) * clip_dur, reveal=(i == reveal_i))
    return edl


# ---------------------------------------------------------------- banner / caption
def font_for(hook: str) -> tuple[Path, bool]:
    if re.search(r"[\u0900-\u097F]", hook):
        for p in DEVANAGARI_FONTS:
            if Path(p).exists():
                return Path(p), True
    for p in [DEFAULT_FONT, *FALLBACK_FONTS]:
        if p.exists():
            return p, False
    raise RenderError("no usable font found")


def load_font(path: Path, size: int, variable_bold: bool):
    f = ImageFont.truetype(str(path), size)
    if variable_bold:
        try:
            f.set_variation_by_name("Bold")
        except Exception:
            pass
    return f


def make_banner(hook: str, banner_png: Path):
    W, H = CANVAS_W, BANNER_H
    im = Image.new("RGB", (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(im)
    lines = [ln.strip() for ln in hook.replace("\\n", "\n").split("\n") if ln.strip()][:2] or ["Watch this"]
    font_path, vb = font_for(hook)
    size = 78

    def fits(f):
        bbs = [draw.textbbox((0, 0), ln, font=f) for ln in lines]
        return max(b[2] - b[0] for b in bbs) <= W - 80 and sum(b[3] - b[1] for b in bbs) + 8 * (len(lines) - 1) <= H - 40

    font = load_font(font_path, size, vb)
    while size > 36 and not fits(font):
        size -= 2
        font = load_font(font_path, size, vb)
    bbs = [draw.textbbox((0, 0), ln, font=font) for ln in lines]
    heights = [b[3] - b[1] for b in bbs]
    gap = 8 if len(lines) > 1 else 0
    y = (H - (sum(heights) + gap * (len(lines) - 1))) // 2
    for ln, bb, hh in zip(lines, bbs, heights):
        draw.text(((W - (bb[2] - bb[0])) // 2 - bb[0], y - bb[1]), ln, font=font, fill=(0, 0, 0))
        y += hh + gap
    banner_png.parent.mkdir(parents=True, exist_ok=True)
    im.save(banner_png)
    log(f"Banner written font={font_path.name} {size}px lines={len(lines)}")


def write_caption_txt(out_path: Path, music: Path, hook: str, preset: dict | None, src_info: dict) -> Path:
    meta = load_music_meta(music)
    credit = meta["credit"] if meta else f"Music: {music.name}"
    hook_line = hook.replace("\\n", " ").replace("\n", " ")
    tags = (preset or {}).get("tags", "#shorts #fyp #viralreels")
    src_line = ""
    if src_info.get("title"):
        src_line = f"Source: {src_info['title']}" + (f" ({src_info['url']})" if src_info.get("url") else "") + "\n"
    body = (f"{hook_line} 🔥\nComment mein batao 👇\n{tags}\n\n{src_line}\n{credit}\n")
    cap = out_path.with_name(out_path.stem + ".caption.txt")
    cap.parent.mkdir(parents=True, exist_ok=True)
    cap.write_text(body, encoding="utf-8")
    log(f"Post caption written {cap}")
    return cap


# ---------------------------------------------------------------- rendering
def render_raw(source: Path, edl, raw_path: Path, target: float):
    parts, labels = [], []
    for i, c in enumerate(edl):
        parts.append(f"[0:v]trim=start={c['src_start']}:end={c['src_end']},setpts=PTS-STARTPTS,"
                     f"fps=30,format=yuv420p[v{i}]")
        labels.append(f"[v{i}]")
    parts.append("".join(labels) + f"concat=n={len(edl)}:v=1:a=0[vout]")
    run(["ffmpeg", "-y", "-v", "error", "-i", source, "-filter_complex", ";".join(parts),
         "-map", "[vout]", "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
         "-pix_fmt", "yuv420p", "-r", "30", "-t", f"{target:.4f}", raw_path])


def render_final(raw_path, music, banner_png, music_start, target, out_path, layout, bg_brightness):
    fade_start = max(0.0, target - 1.2)
    L = layout
    vf = (
        f"[0:v]crop=iw:{L['act_src_h']}:0:{L['act_src_y']},"
        f"scale={CANVAS_W}:{CANVAS_H}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={CANVAS_W}:{CANVAS_H},boxblur=30:5,eq=brightness={bg_brightness:.3f},setsar=1[bg];"
        f"[0:v]scale={L['fg_w']}:{L['fg_h']}:flags=lanczos,setsar=1,format=yuv420p[fg];"
        f"[2:v]scale={CANVAS_W}:{BANNER_H},setsar=1,format=yuv420p[bn];"
        f"[bg][bn]overlay=x=0:y={L['banner_y']}:shortest=1[b1];"
        f"[b1][fg]overlay=x={L['plate_x']}:y={L['plate_y']},format=yuv420p[v];"
        f"[1:a]atrim=start={music_start:.4f},asetpts=PTS-STARTPTS,"
        f"afade=t=in:st=0:d=0.25,afade=t=out:st={fade_start:.3f}:d=1.2,"
        f"volume=0.95,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
        f"apad=whole_dur={target:.4f}[a]"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(out_path.stem + ".tmp.mp4")
    run(["ffmpeg", "-y", "-v", "error", "-i", raw_path, "-i", music, "-loop", "1", "-i", banner_png,
         "-filter_complex", vf, "-map", "[v]", "-map", "[a]",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-r", "30",
         "-c:a", "aac", "-b:a", "192k", "-t", f"{target:.4f}", "-movflags", "+faststart", tmp])
    tmp.replace(out_path)


def audio_mean_db(path: Path) -> float:
    r = subprocess.run(["ffmpeg", "-v", "info", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=300)
    m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", r.stderr or "")
    return float(m.group(1)) if m else -91.0


def qc(path: Path, work: Path, target: float, layout: dict) -> dict:
    v = ffprobe_json(path, "-select_streams", "v:0",
                     "-show_entries", "stream=width,height,pix_fmt,r_frame_rate:format=duration")
    a = ffprobe_json(path, "-select_streams", "a:0", "-show_entries", "stream=codec_name")
    st = (v.get("streams") or [{}])[0]
    dur = float((v.get("format") or {}).get("duration") or 0)
    num, _, den = (st.get("r_frame_rate") or "0/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 0.0
    has_audio = bool(a.get("streams"))
    adb = audio_mean_db(path) if has_audio else -91.0
    tech_ok = (st.get("width") == 1080 and st.get("height") == 1920 and st.get("pix_fmt") == "yuv420p"
               and abs(fps - 30) < 0.05 and has_audio and adb > MIN_AUDIO_DB and MIN_LEN <= dur <= MAX_LEN)
    qdir = work / "qc_frames"
    qdir.mkdir(parents=True, exist_ok=True)
    for p in qdir.glob("*"):
        p.unlink()
    run(["ffmpeg", "-y", "-v", "error", "-i", path, "-vf", "fps=2", "-q:v", "3", qdir / "%04d.jpg"])
    frames = sorted(qdir.glob("*.jpg"))
    fails, bg_means = [], []
    y0, y1 = layout["act_y"], layout["act_y"] + layout["act_h"]  # real picture inside the plate
    x0, x1 = layout["plate_x"], layout["plate_x"] + layout["fg_w"]
    for i, fp in enumerate(frames):
        if i / 2 > dur - 0.6:
            continue
        im = np.array(Image.open(fp).convert("RGB"))
        h, w, _ = im.shape
        if (w, h) != (1080, 1920):
            fails.append((i / 2, "resolution", f"{w}x{h}"))
            continue
        d = score_frame(im[y0:y1, x0:x1, :], None)
        if d["reject"]:
            fails.append((i / 2, "content", ", ".join(d["reasons"])))
        pe = layout["plate_y"] + layout["plate_h"]
        bg = np.concatenate([im[: max(layout["banner_y"] - 10, 1)], im[min(pe + 10, h - 1):]], axis=0)
        bg_means.append(float(luma(bg.astype(np.float32)).mean()))
    bg_mean = float(np.mean(bg_means)) if bg_means else 0.0
    bg_ok = bg_mean >= 22.0
    return {
        "tech_ok": tech_ok, "width": st.get("width"), "height": st.get("height"),
        "pix_fmt": st.get("pix_fmt"), "fps": fps, "duration": dur, "has_audio": has_audio,
        "audio_mean_db": adb, "frames_checked": len(frames), "fails": fails,
        "bg_mean_luma": bg_mean, "bg_ok": bg_ok,
        "pass": bool(tech_ok and not fails and bg_ok), "target": target,
    }


def print_qc(r: dict):
    log("=" * 60)
    log("QC PASS REPORT" if r["pass"] else "QC FAIL REPORT")
    log(f"  resolution : {r['width']}x{r['height']}  pix_fmt={r['pix_fmt']}  fps={r['fps']:.2f}")
    log(f"  duration   : {r['duration']:.3f}s (need {MIN_LEN:.0f}-{MAX_LEN:.0f})")
    log(f"  audio      : {'yes' if r['has_audio'] else 'NO'}  mean {r['audio_mean_db']:.1f} dB")
    log(f"  background : mean luma {r['bg_mean_luma']:.1f} ({'ok' if r['bg_ok'] else 'TOO DARK'})")
    log(f"  frames     : {r['frames_checked']} checked at 2 fps, {len(r['fails'])} failed")
    for t, kind, why in r["fails"][:10]:
        log(f"    t={t}s [{kind}] {why}")
    log(f"  result     : {'PASS' if r['pass'] else 'FAIL'}")
    log("=" * 60)


def plan_timing(bpm: float, cut_s: float, target_s: float) -> tuple[float, int, int]:
    beat = 60.0 / bpm
    beats = max(2, round(cut_s / beat))
    clip_dur = round(beats * beat * 30) / 30.0
    n = max(8, round(target_s / clip_dur))
    while n * clip_dur > MAX_LEN - 1:
        n -= 1
    while n * clip_dur < MIN_LEN + 1:
        n += 1
    return clip_dur, n, beats


def render_one(source: Path, music: Path, hook: str, out_path: Path, work: Path,
               cut_s: float, target_s: float, bpm_override: float | None, clips_override: int | None,
               bg_brightness: float | None = None) -> dict:
    """One source + one track, with up to QC_ROUNDS blacklist re-renders."""
    work.mkdir(parents=True, exist_ok=True)
    info = probe_video(source)
    layout = layout_for(info["w"], info["h"], detect_active(source, info["dur"], info["w"], info["h"]))
    head = float(math.floor(min(MAX_SKIP_HEAD, info["dur"] * 0.06)))
    tail = min(MAX_SKIP_TAIL, info["dur"] * 0.10)
    usable_end = info["dur"] - tail
    if usable_end - head < 30:
        raise SourceError(f"source too short after trim: {info['dur']:.1f}s")
    meta = load_music_meta(music) or {}
    bpm = bpm_override or float(meta.get("bpm") or DEFAULT_BPM)
    clip_dur, n_clips, beats = plan_timing(bpm, cut_s, target_s)
    if clips_override:
        n_clips = clips_override
    mdur = probe_duration(music)
    log(f"Source {source.name} {info['w']}x{info['h']} {info['dur']:.1f}s | music {music.name} "
        f"bpm={bpm} {beats} beats/cut clip={clip_dur:.3f}s x{n_clips}")
    log(f"Layout plate {layout['fg_w']}x{layout['fg_h']} @ ({layout['plate_x']},{layout['plate_y']}) "
        f"banner @ Y={layout['banner_y']} (no crop, no captions, no watermark); "
        f"active picture rows {layout['act_src_y']}+{layout['act_src_h']} of {info['h']}")

    banner_png = work / "banner.png"
    make_banner(hook, banner_png)
    frames_dir = work / "frames"
    extract_frames(source, frames_dir, head, usable_end - head, layout)
    rows = score_all(frames_dir, head)
    if bg_brightness is None:
        src_mean = float(np.mean([r["mean"] for r in rows])) if rows else 80.0
        bg_brightness = -0.08 if src_mean > 90 else (0.0 if src_mean > 60 else 0.08)
    drop = find_drop(decode_wav(music, work / "music.wav"))

    # Self-heal: shrink clip count if the source has too few clean windows.
    edl = None
    for n in range(n_clips, 0, -1):
        if n * clip_dur < MIN_LEN:
            break
        try:
            edl = pick_edl(rows, head, usable_end, clip_dur, n)
            n_clips = n
            break
        except SourceError as e:
            log(f"  {e}; trying fewer clips")
    if edl is None:
        raise SourceError("not enough clean footage for a 20s+ video")
    target = n_clips * clip_dur
    reveal_t = edl[min(REVEAL_INDEX, n_clips - 1)]["t0"]
    music_start = max(0.0, min(drop - reveal_t, mdur - target - 0.5))
    raw = work / "raw_concat.mp4"
    blacklist: set[int] = set()
    report = None
    for rnd in range(1, QC_ROUNDS + 1):
        log(f"Render round {rnd}: {n_clips} clips, {target:.2f}s, bg_brightness={bg_brightness:+.2f}")
        render_raw(source, edl, raw, target)
        render_final(raw, music, banner_png, music_start, target, out_path, layout, bg_brightness)
        report = qc(out_path, work, target, layout)
        print_qc(report)
        if report["pass"]:
            break
        if not report["tech_ok"]:
            raise RenderError(f"technical QC failed (audio {report['audio_mean_db']:.1f} dB, "
                              f"dur {report['duration']:.1f}s)")
        if not report["bg_ok"]:
            bg_brightness = min(bg_brightness + 0.10, 0.25)
        for t, kind, _ in report["fails"]:
            ci = min(int(t / clip_dur), len(edl) - 1)
            src_t = edl[ci]["src_start"] + (t - edl[ci]["t0"])
            blacklist.update({math.floor(src_t - 0.5), math.floor(src_t), math.floor(src_t + 0.5)})
        if report["fails"]:
            log(f"  blacklisting source seconds {sorted(blacklist)}")
            edl = pick_edl(rows, head, usable_end, clip_dur, n_clips, blacklist)
    if not report or not report["pass"]:
        raise SourceError(f"QC still failing after {QC_ROUNDS} rounds")
    report.update(edl=edl, music_start=music_start, drop=drop, bg_brightness=bg_brightness,
                  layout=layout, clip_dur=clip_dur, clips=n_clips, bpm=bpm)
    return report


# ---------------------------------------------------------------- orchestration
def choose_hook(args, preset: dict | None, out_stem: str, title: str = "") -> str:
    if args.hook:
        return args.hook
    if not preset:
        return DEFAULT_HOOK
    hooks = preset["hooks"]
    if args.hook_index is not None:
        return hooks[args.hook_index % len(hooks)]
    for word, idx in (preset.get("hook_match") or {}).items():
        if re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", title.lower()):
            return hooks[idx % len(hooks)]
    return hooks[int(hashlib.md5(out_stem.encode()).hexdigest(), 16) % len(hooks)]


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Render a clean 9:16 Short (no captions, no watermark).")
    p.add_argument("--source", type=Path, help="Source video path (optional with --auto)")
    p.add_argument("--category", help=f"Preset: {', '.join(categories.CATEGORIES)}")
    p.add_argument("--auto", action="store_true", help="Fetch an official source for --category with yt-dlp")
    p.add_argument("--hook", default=None, help="Top banner hook, use \\n for a second line")
    p.add_argument("--hook-index", type=int, default=None, help="Pick preset hook N (default: by output name)")
    p.add_argument("--music", default=None, help="Track file/path; default = category's track list")
    p.add_argument("--out", type=Path, help="Output mp4 path (required unless --list-sources)")
    p.add_argument("--bpm", type=float, default=None, help="Override music BPM")
    p.add_argument("--clips", type=int, default=None, help="Override number of cuts")
    p.add_argument("--work", type=Path, default=None, help="Scratch directory (default work/<out name>)")
    p.add_argument("--log", type=Path, default=None, help="Run log (default <out>.log)")
    p.add_argument("--max-sources", type=int, default=4, help="--auto: how many search results to try")
    p.add_argument("--exclude-id", action="append", default=[], help="--auto: skip this YouTube id")
    p.add_argument("--list-sources", action="store_true", help="--auto: only print ranked candidates, no render")
    a = p.parse_args(argv)
    if a.category:
        try:
            categories.get(a.category)
        except KeyError as e:
            p.error(str(e).strip('"'))
    if not a.source and not a.auto:
        p.error("give --source, or --auto with --category")
    if a.auto and not a.category:
        p.error("--auto needs --category")
    if not a.out and not a.list_sources:
        p.error("--out is required")
    return a


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.list_sources:
        preset = categories.get(args.category)
        for c in sourcing.candidates(preset, exclude=set(args.exclude_id), limit=args.max_sources, log=lambda m: None):
            print(f"{c['id']}  {c.get('duration')}s  {c.get('channel')}  {c.get('title')}")
        return 0
    out_path = args.out.expanduser()
    out_path = (Path.cwd() / out_path).resolve() if not out_path.is_absolute() else out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)  # bug fix: missing out/ crashed
    log_path = args.log or out_path.with_name(out_path.stem + ".log")
    sys.stdout = Tee(log_path)
    log(f"\n===== run {_dt.datetime.now().isoformat(timespec='seconds')} -> {out_path.name} =====")
    work = (args.work or (ROOT / "work" / out_path.stem)).expanduser().resolve()
    work.mkdir(parents=True, exist_ok=True)

    preset = categories.get(args.category) if args.category else None
    cut_s = preset["cut_s"] if preset else DEFAULT_CUT_S
    target_s = preset["target_s"] if preset else DEFAULT_TARGET_S

    track_list = [args.music] if args.music else []
    track_list += (preset["music"] if preset else [DEFAULT_TRACK]) + categories.FALLBACK_MUSIC
    track_list = list(dict.fromkeys(track_list))

    # Source candidates: (info, getter(height) -> Path)
    if args.source and not args.auto:
        src = args.source.expanduser().resolve()
        if not src.exists():
            log(f"ERROR: source not found: {src}")
            return 2
        sources = [({"title": src.stem, "url": "", "id": src.stem}, None, src)]
    else:
        log(f"Searching official sources for category '{preset['name']}'…")
        cands = sourcing.candidates(preset, exclude=set(args.exclude_id), limit=args.max_sources, log=log)
        if not cands:
            log("ERROR: no acceptable search results (network/yt-dlp?)")
            return 3
        for c in cands:
            log(f"  candidate {c['id']} {c.get('duration')}s {c.get('channel')}: {c.get('title')}")
        sources = [(c, c, None) for c in cands]

    attempts = []
    src_dir = ROOT / "work" / "sources"
    for info, entry, local in sources:
        heights = [None] if local else [1080, 720, 480]
        for height in heights:
            label = f"{info.get('id')}@{height or 'local'}"
            try:
                path = local or sourcing.download(entry, src_dir, height, log=log)
                vi = probe_video(path)
                if entry is not None and vi["w"] / vi["h"] < 1.6:
                    raise SourceError(f"not 16:9 ({vi['w']}x{vi['h']})")
            except SourceError as e:
                log(f"  source {label} unusable: {e}")
                attempts.append(f"{label}: {e}")
                continue
            render_failed = False
            hook = choose_hook(args, preset, out_path.stem, info.get("title") or "")
            for track in track_list:
                tag = f"{label} + {Path(track).name}"
                try:
                    music = ensure_track(track)
                    log(f"\n--- attempt: {tag} ---")
                    report = render_one(path, music, hook, out_path, work, cut_s, target_s,
                                        args.bpm, args.clips)
                except SourceError as e:
                    log(f"  SOURCE problem ({tag}): {e} -> next source")
                    attempts.append(f"{tag}: {e}")
                    break
                except (RenderError, OSError, ValueError) as e:
                    log(f"  RENDER problem ({tag}): {e} -> next track")
                    attempts.append(f"{tag}: {e}")
                    render_failed = True
                    continue
                except Exception as e:  # unexpected bug: log it, keep healing
                    log(f"  UNEXPECTED ({tag}): {e}\n{traceback.format_exc()}")
                    attempts.append(f"{tag}: unexpected {e}")
                    render_failed = True
                    continue
                src_info = {"title": info.get("title"), "id": info.get("id"),
                            "channel": info.get("channel"),
                            "url": f"https://www.youtube.com/watch?v={info['id']}" if entry else ""}
                write_caption_txt(out_path, music, hook, preset, src_info)
                meta = load_music_meta(music) or {}
                summary = {"output": str(out_path), "category": preset["name"] if preset else None,
                           "hook": hook, "source": src_info, "music": music.name,
                           "music_credit": meta.get("credit", music.name),
                           "duration": report["duration"], "qc_pass": report["pass"],
                           "attempts_before_success": attempts}
                out_path.with_name(out_path.stem + ".json").write_text(
                    json.dumps(summary, indent=2, ensure_ascii=False))
                (work / "qc_report.json").write_text(json.dumps(report, indent=2, default=str))
                log(f"OUTPUT {out_path} dur={report['duration']:.2f}s QC=PASS "
                    f"after {len(attempts)} failed attempt(s)")
                return 0
            else:
                if not render_failed:
                    break
                continue  # every track failed to render: re-download lower resolution
            break  # SourceError: go to next source
    log("\nERROR: all fallbacks exhausted. Attempts:")
    for a in attempts:
        log(f"  - {a}")
    log(f"See log: {log_path}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
