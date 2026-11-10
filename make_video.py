#!/usr/bin/env python3
"""Render a 9:16 Short from a source clip.

No on-screen captions and no watermark. The full source frame is scaled
to 1080 wide (no crop), placed under a tight white hook banner, and the
banner+frame block is centered on a blurred 1080x1920 canvas. Keeps
beat-synced cuts, NCS music, and QC.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
DEFAULT_MUSIC_META = ROOT / "assets" / "music.json"
DEFAULT_FONT = ROOT / "fonts" / "ArchivoBlack-Regular.ttf"
FALLBACK_FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")

SKIP_HEAD = 9.0
SKIP_TAIL = 16.0
CLIP_BEATS = 5
DEFAULT_BPM = 129.0
DEFAULT_CLIPS = 11
REVEAL_INDEX = 5
DEFAULT_HOOK = "Nobody was ready\nfor Fool Night"

CANVAS_W = 1080
CANVAS_H = 1920
BANNER_H = 240
BG_BRIGHTNESS = -0.08


def run(cmd, **kw):
    print("  $", " ".join(str(c) for c in cmd[:12]), "..." if len(cmd) > 12 else "")
    r = subprocess.run(cmd, **kw)
    if r.returncode != 0:
        raise SystemExit(f"command failed ({r.returncode}): {cmd[0]}")
    return r


def probe_duration(path: Path) -> float:
    out = subprocess.check_output(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        text=True,
    )
    return float(out.strip())


def probe_size(path: Path) -> tuple[int, int]:
    out = subprocess.check_output(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0",
            str(path),
        ],
        text=True,
    )
    w, h = out.strip().split(",")[:2]
    return int(w), int(h)


def scaled_fg_height(src_w: int, src_h: int, out_w: int = CANVAS_W) -> int:
    """Height after scale=OUT_W:-2 (keep aspect, even number, no crop)."""
    return int(round((src_h * out_w / src_w) / 2.0) * 2)


def layout_for(src_w: int, src_h: int) -> dict:
    fg_h = scaled_fg_height(src_w, src_h)
    block_h = BANNER_H + fg_h
    block_y = (CANVAS_H - block_h) // 2
    return {
        "fg_w": CANVAS_W,
        "fg_h": fg_h,
        "banner_h": BANNER_H,
        "block_h": block_h,
        "block_y": block_y,
        "banner_y": block_y,
        "plate_y": block_y + BANNER_H,
        "plate_h": fg_h,
    }


def load_music_meta(music: Path) -> dict | None:
    if not DEFAULT_MUSIC_META.exists():
        return None
    tracks = json.loads(DEFAULT_MUSIC_META.read_text())["tracks"]
    return next((t for t in tracks if t["file"] == music.name), None)


def ensure_music(music: Path | None) -> Path:
    if music and music.exists():
        return music
    dest = ROOT / "assets" / "music" / "ncs_lavida.mp3"
    if dest.exists() and dest.stat().st_size > 100_000:
        return dest
    print("Music file missing — downloading official NCS track…")
    run([sys.executable, str(ROOT / "scripts" / "download_music.py")], check=True)
    if not dest.exists():
        raise SystemExit("Music download did not produce assets/music/ncs_lavida.mp3")
    return dest


def extract_frames(source: Path, frames_dir: Path, src_dur: float) -> int:
    if frames_dir.exists():
        for p in frames_dir.glob("*.jpg"):
            p.unlink()
    else:
        frames_dir.mkdir(parents=True, exist_ok=True)
    usable = src_dur - SKIP_HEAD - SKIP_TAIL
    if usable < 8:
        raise SystemExit(f"Source is too short after head/tail trim: {src_dur:.3f}s")
    run(
        [
            "ffmpeg", "-y",
            "-ss", f"{SKIP_HEAD}",
            "-i", str(source),
            "-t", f"{usable:.4f}",
            "-vf", "fps=1",
            "-q:v", "3",
            str(frames_dir / "%04d.jpg"),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    n = len(list(frames_dir.glob("*.jpg")))
    print(f"Extracted {n} 1fps frames from {SKIP_HEAD:.1f}s to {src_dur - SKIP_TAIL:.1f}s")
    return n


def decode_wav(music: Path, wav_path: Path) -> Path:
    run(
        [
            "ffmpeg", "-y", "-i", str(music),
            "-ac", "1", "-ar", "22050",
            str(wav_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return wav_path


def load_frame(frames_dir: Path, i: int) -> np.ndarray:
    return np.array(Image.open(frames_dir / f"{i:04d}.jpg").convert("RGB"))


def score_frame(im: np.ndarray, prev: np.ndarray | None) -> dict:
    y = 0.299 * im[:, :, 0] + 0.587 * im[:, :, 1] + 0.114 * im[:, :, 2]
    dark = float((y < 25).mean())
    red = float(((im[:, :, 0] > 150) & (im[:, :, 1] < 50) & (im[:, :, 2] < 50)).mean())
    h, w = y.shape
    cy0, cy1 = int(h * 0.3), int(h * 0.7)
    cx0, cx1 = int(w * 0.3), int(w * 0.7)
    gx = np.abs(np.diff(y, axis=1, prepend=y[:, :1]))
    gy = np.abs(np.diff(y, axis=0, prepend=y[:1, :]))
    edge = gx + gy
    center_edge = float(edge[cy0:cy1, cx0:cx1].mean())
    mask = np.ones(y.shape, dtype=bool)
    mask[cy0:cy1, cx0:cx1] = False
    outer_edge = float(edge[mask].mean())
    outer_std = float(y[mask].std())
    text_card = bool(center_edge > 18.0 and outer_edge < 8.0 and outer_std < 28.0)
    reject = dark > 0.45 or red > 0.35 or text_card
    motion = 0.0
    if prev is not None:
        motion = float(
            np.mean(
                np.abs(
                    y
                    - (
                        0.299 * prev[:, :, 0]
                        + 0.587 * prev[:, :, 1]
                        + 0.114 * prev[:, :, 2]
                    )
                )
            )
        )
    spectacle = (
        (1.0 - min(dark, 1.0)) * 40
        + min(motion, 40) * 1.2
        + float(y.std()) * 0.4
        + min(center_edge, 25) * 0.3
    )
    if reject:
        spectacle = -1.0
    reasons = []
    if dark > 0.45:
        reasons.append(f"dark={dark:.2f}")
    if red > 0.35:
        reasons.append(f"red={red:.2f}")
    if text_card:
        reasons.append(f"textcard ce={center_edge:.1f} oe={outer_edge:.1f} os={outer_std:.1f}")
    return {
        "dark": dark,
        "red": red,
        "text_card": text_card,
        "center_edge": center_edge,
        "outer_edge": outer_edge,
        "outer_std": outer_std,
        "motion": motion,
        "mean": float(y.mean()),
        "spectacle": spectacle,
        "reject": reject,
        "reasons": reasons,
    }


def score_all(frames_dir: Path) -> list[dict]:
    n = len(list(frames_dir.glob("*.jpg")))
    rows = []
    prev = None
    for i in range(1, n + 1):
        im = load_frame(frames_dir, i)
        t = SKIP_HEAD + (i - 1)
        d = score_frame(im, prev)
        d["i"] = i
        d["t"] = t
        rows.append(d)
        prev = im
    ok = sum(1 for r in rows if not r["reject"])
    print(f"Scored {n} seconds: {ok} usable, {n - ok} rejected")
    rej = [r for r in rows if r["reject"]]
    print("  reject examples: " + ", ".join(f"{r['t']:.0f}s({','.join(r['reasons'])})" for r in rej[:12]))
    top = sorted([r for r in rows if not r["reject"]], key=lambda r: -r["spectacle"])[:8]
    print("  top shots: " + ", ".join(f"{r['t']:.0f}s/{r['spectacle']:.0f}" for r in top))
    return rows


def window_ok(rows_by_t: dict, start: float, dur: float) -> tuple[bool, float]:
    specs = []
    end = start + dur - 1e-6
    tt = math.floor(start)
    while tt < end:
        row = rows_by_t.get(tt)
        if row is None or row["reject"]:
            return False, -1.0
        specs.append(row["spectacle"])
        tt += 1
    return True, float(min(specs) + 0.35 * (sum(specs) / len(specs)))


def pick_edl(
    rows: list[dict],
    usable_end: float,
    clip_dur: float,
    n_clips: int,
    blacklist: set[float] | None = None,
) -> list[dict]:
    blacklist = blacklist or set()
    rows_by_t = {int(r["t"]): r for r in rows}
    cands = []
    t = SKIP_HEAD
    while t + clip_dur <= usable_end - 0.05:
        ok, sc = window_ok(rows_by_t, t, clip_dur)
        if ok and all(
            (t + off) not in blacklist and math.floor(t + off) not in blacklist
            for off in (0, 1, 2)
        ):
            cands.append(
                {"src_start": round(t, 3), "src_end": round(t + clip_dur, 3), "score": sc}
            )
        t += 0.5
    if len(cands) < n_clips:
        raise SystemExit(f"Only {len(cands)} candidate windows, need {n_clips}")
    cands.sort(key=lambda c: -c["score"])
    picked = []
    for c in cands:
        if any(abs(c["src_start"] - p["src_start"]) < 5.0 for p in picked):
            continue
        picked.append(c)
        if len(picked) == n_clips:
            break
    if len(picked) < n_clips:
        for c in cands:
            if any(abs(c["src_start"] - p["src_start"]) < clip_dur + 0.05 for p in picked):
                continue
            picked.append(c)
            if len(picked) == n_clips:
                break
    if len(picked) < n_clips:
        raise SystemExit(f"Could only pick {len(picked)} non-overlapping clips")
    reveal = max(picked, key=lambda c: c["score"])
    rest = sorted([c for c in picked if c is not reveal], key=lambda c: c["src_start"])
    before_n = REVEAL_INDEX
    after_n = n_clips - REVEAL_INDEX - 1
    before = rest[:before_n]
    after = rest[before_n : before_n + after_n]
    edl = before + [reveal] + after
    if len(edl) != n_clips:
        edl = sorted(picked, key=lambda c: c["src_start"])
        bi = max(range(len(edl)), key=lambda i: edl[i]["score"])
        edl[REVEAL_INDEX], edl[bi] = edl[bi], edl[REVEAL_INDEX]
    for i, c in enumerate(edl):
        c["i"] = i
        c["t0"] = i * clip_dur
        c["t1"] = (i + 1) * clip_dur
        c["reveal"] = i == REVEAL_INDEX
    return edl


def find_drop(wav: Path) -> float:
    with wave.open(str(wav), "rb") as w:
        sr = w.getframerate()
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    hop = int(sr * 0.05)
    win = int(sr * 0.25)
    rms = np.array(
        [np.sqrt(np.mean(audio[i : i + win] ** 2)) for i in range(0, len(audio) - win, hop)]
    )
    sm = np.convolve(rms, np.ones(10) / 10, mode="same")
    look = int(0.5 / 0.05)
    delta = sm[look:] - sm[:-look]
    limit = min(len(delta), int(40 / 0.05))
    land = sm[look : look + limit]
    score = delta[:limit] * (0.4 + land / (land.max() + 1e-6))
    idx = int(np.argmax(score))
    drop_t = (idx + look) * 0.05
    print(f"Music drop @ {drop_t:.2f}s (peak rms around there: {sm[min(idx + look, len(sm) - 1)]:.3f})")
    for sec in range(0, 40, 2):
        j = int(sec / 0.05)
        if j < len(sm):
            bar = "#" * int(sm[j] * 40)
            if abs(sec - drop_t) < 1:
                bar += "  <DROP"
            print(f"    {sec:02d}s {sm[j]:.3f} {bar}")
    return drop_t


def make_banner(hook: str, banner_png: Path, font_path: Path):
    W, H = 1080, 240
    im = Image.new("RGB", (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(im)
    lines = [ln for ln in hook.replace("\\n", "\n").split("\n") if ln.strip()] or [hook]
    size = 78
    font = ImageFont.truetype(str(font_path), size)

    def fits(f):
        widths = [draw.textbbox((0, 0), ln, font=f)[2] for ln in lines]
        return max(widths) <= W - 80

    while size > 40 and not fits(font):
        size -= 2
        font = ImageFont.truetype(str(font_path), size)
    bbs = [draw.textbbox((0, 0), ln, font=font) for ln in lines]
    heights = [b[3] - b[1] for b in bbs]
    gap = 8 if len(lines) > 1 else 0
    total_h = sum(heights) + gap * (len(lines) - 1)
    y = (H - total_h) // 2
    for ln, bb, hh in zip(lines, bbs, heights):
        tw = bb[2] - bb[0]
        x = (W - tw) // 2 - bb[0]
        draw.text((x, y - bb[1]), ln, font=font, fill=(0, 0, 0))
        y += hh + gap
    im.save(banner_png)
    print(f"Banner written {banner_png} font={size}px")


def write_caption_txt(out_path: Path, music: Path, hook: str) -> str:
    meta = load_music_meta(music)
    credit = meta["credit"] if meta else f"Music: {music.name}"
    hook_line = hook.replace("\\n", " ").replace("\n", " ")
    body = (
        f"{hook_line} — this scene hits different.\n"
        "Would you survive this world? Drop your thoughts below 👇\n"
        "#animeedits #foolnight #darkanime #animerecommendations #fyp #viralreels\n"
        "\n"
        f"{credit}\n"
    )
    cap = out_path.with_suffix(out_path.suffix + ".caption.txt")
    if out_path.suffix.lower() == ".mp4":
        cap = Path(str(out_path) + ".caption.txt")
    # simpler: out/foolnight_clean.mp4.caption.txt is ugly; use .caption.txt next to stem
    cap = out_path.with_name(out_path.stem + ".caption.txt")
    cap.write_text(body)
    print(f"Post caption written {cap}")
    print(body)
    return body


def build_concat_filter(edl):
    parts = []
    labels = []
    for i, c in enumerate(edl):
        parts.append(
            f"[0:v]trim=start={c['src_start']}:end={c['src_end']},setpts=PTS-STARTPTS,"
            f"fps=30,format=yuv420p[v{i}]"
        )
        labels.append(f"[v{i}]")
    parts.append("".join(labels) + f"concat=n={len(edl)}:v=1:a=0[vout]")
    return ";".join(parts)


def render_raw(source: Path, edl, raw_path: Path, target: float):
    fc = build_concat_filter(edl)
    cmd = [
        "ffmpeg", "-y", "-i", str(source),
        "-filter_complex", fc,
        "-map", "[vout]", "-an",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", "30",
        "-t", f"{target:.4f}",
        str(raw_path),
    ]
    run(cmd, check=True)


def render_final(
    raw_path: Path,
    music: Path,
    banner_png: Path,
    music_start: float,
    target: float,
    out_path: Path,
):
    fade_start = max(0.0, target - 1.2)
    # Full source frame, no crop: scale to 1080 wide, keep aspect (16:9 -> 1080x608).
    # White banner is vstacked directly on top of that frame (no gap), then the
    # combined block is centered vertically on the brighter blurred canvas.
    vf = (
        f"[0:v]scale={CANVAS_W}:{CANVAS_H}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={CANVAS_W}:{CANVAS_H},boxblur=30:5,eq=brightness={BG_BRIGHTNESS},setsar=1[bg];"
        f"[0:v]scale={CANVAS_W}:-2:flags=lanczos,setsar=1,format=yuv420p[fg];"
        f"[2:v]scale={CANVAS_W}:{BANNER_H},setsar=1,format=yuv420p[bn];"
        f"[bn][fg]vstack=inputs=2[block];"
        f"[bg][block]overlay=x=0:y=(H-h)/2[v];"
        f"[1:a]atrim=start={music_start:.4f},asetpts=PTS-STARTPTS,"
        f"afade=t=in:st=0:d=0.25,afade=t=out:st={fade_start:.3f}:d=1.2,"
        f"volume=0.95,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
        f"apad=whole_dur={target:.4f}[a]"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(raw_path),
        "-i", str(music),
        "-loop", "1", "-i", str(banner_png),
        "-filter_complex", vf,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", "30",
        "-c:a", "aac", "-b:a", "192k",
        "-t", f"{target:.4f}",
        "-movflags", "+faststart",
        str(out_path),
    ]
    run(cmd, check=True)


def qc(path: Path, work: Path, target: float, layout: dict) -> dict:
    probe = subprocess.check_output(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,codec_name,pix_fmt,r_frame_rate,avg_frame_rate",
            "-show_entries", "format=duration",
            "-of", "json",
            str(path),
        ]
    )
    aprobe = subprocess.check_output(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=codec_name,sample_rate,channels",
            "-of", "json",
            str(path),
        ]
    )
    vinfo = json.loads(probe)
    ainfo = json.loads(aprobe)
    st = vinfo["streams"][0]
    dur = float(vinfo["format"]["duration"])
    has_audio = bool(ainfo.get("streams"))
    rate = st.get("r_frame_rate") or st.get("avg_frame_rate")
    num, den = [int(x) for x in rate.split("/")]
    fps = num / den if den else 0
    tech_ok = (
        int(st["width"]) == 1080
        and int(st["height"]) == 1920
        and st.get("pix_fmt") == "yuv420p"
        and abs(fps - 30) < 0.05
        and has_audio
        and 20 <= dur <= 35
    )
    qdir = work / "qc_frames"
    if qdir.exists():
        for p in qdir.glob("*"):
            p.unlink()
    else:
        qdir.mkdir()
    run(
        [
            "ffmpeg", "-y", "-i", str(path),
            "-vf", "fps=1",
            "-q:v", "3",
            str(qdir / "%04d.jpg"),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    frames = sorted(qdir.glob("*.jpg"))
    fails = []
    for i, fp in enumerate(frames):
        im = np.array(Image.open(fp).convert("RGB"))
        h, w, _ = im.shape
        if (w, h) != (1080, 1920):
            fails.append((i, "resolution", f"{w}x{h}"))
            continue
        # Inspect only the sharp full-frame plate, not the blurred bars.
        y0 = layout["plate_y"]
        y1 = y0 + layout["plate_h"]
        plate = im[y0:y1, :, :]
        d = score_frame(plate, None)
        if d["reject"]:
            fails.append((i, "content", ", ".join(d["reasons"]) or "reject"))
    report = {
        "tech_ok": tech_ok,
        "width": int(st["width"]),
        "height": int(st["height"]),
        "pix_fmt": st.get("pix_fmt"),
        "fps": fps,
        "duration": dur,
        "has_audio": has_audio,
        "frames_checked": len(frames),
        "fails": fails,
        "pass": tech_ok and not fails,
        "target": target,
    }
    return report


def print_qc(report: dict):
    status = "QC PASS REPORT" if report["pass"] else "QC FAIL REPORT"
    print("=" * 60)
    print(status)
    print("=" * 60)
    print(f"  resolution : {report['width']}x{report['height']}  (need 1080x1920)")
    print(f"  pix_fmt    : {report['pix_fmt']}  (need yuv420p)")
    print(f"  fps        : {report['fps']:.3f}  (need 30)")
    print(f"  duration   : {report['duration']:.3f}s  (need 20-35)")
    print(f"  audio      : {'yes' if report['has_audio'] else 'NO'}")
    print(f"  frames     : {report['frames_checked']} checked at 1 fps")
    if report["fails"]:
        print("  FAIL frames:")
        for t, kind, why in report["fails"]:
            print(f"    t={t}s [{kind}] {why}")
    else:
        print("  content    : 0 violations (dark / red / text-card)")
    print(f"  result     : {'PASS' if report['pass'] else 'FAIL'}")
    print("=" * 60)


def parse_args():
    p = argparse.ArgumentParser(description="Render a clean 9:16 Short (no captions, no watermark).")
    p.add_argument("--source", required=True, type=Path, help="Source video path")
    p.add_argument("--hook", default=DEFAULT_HOOK, help="Top banner hook, use \\n for a second line")
    p.add_argument("--music", type=Path, default=None, help="Background music file (NCS). Downloaded if omitted.")
    p.add_argument("--out", required=True, type=Path, help="Output mp4 path")
    p.add_argument("--bpm", type=float, default=None, help="Music BPM (default: from music.json or 129)")
    p.add_argument("--clips", type=int, default=DEFAULT_CLIPS, help="Number of beat-synced clips")
    p.add_argument("--work", type=Path, default=ROOT / "work", help="Scratch directory")
    return p.parse_args()


def main():
    args = parse_args()
    source = args.source.expanduser().resolve()
    if not source.exists():
        raise SystemExit(f"Source not found: {source}")
    out_path = args.out.expanduser()
    if not out_path.is_absolute():
        out_path = (Path.cwd() / out_path).resolve()
    work = args.work
    if not work.is_absolute():
        work = (ROOT / work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    frames_dir = work / "frames"

    music = ensure_music(args.music.expanduser().resolve() if args.music else None)
    meta = load_music_meta(music)
    bpm = args.bpm if args.bpm is not None else (float(meta["bpm"]) if meta and meta.get("bpm") else DEFAULT_BPM)
    beat = 60.0 / bpm
    clip_dur = round(CLIP_BEATS * beat * 30) / 30.0
    n_clips = args.clips
    target = n_clips * clip_dur
    src_w, src_h = probe_size(source)
    layout = layout_for(src_w, src_h)
    print(f"Source={source}")
    print(f"Music={music}  bpm={bpm}  clip={clip_dur:.3f}s  clips={n_clips}  target={target:.3f}s")
    print(
        f"Layout: {CANVAS_W}x{CANVAS_H}, full frame {layout['fg_w']}x{layout['fg_h']} "
        f"(no crop) @ Y={layout['plate_y']}, banner {CANVAS_W}x{BANNER_H} @ Y={layout['banner_y']} "
        f"(flush, block centered). bg brightness={BG_BRIGHTNESS}. No captions, no watermark."
    )

    src_dur = probe_duration(source)
    usable_end = src_dur - SKIP_TAIL
    print(f"Source duration={src_dur:.3f}s  usable={SKIP_HEAD:.1f}–{usable_end:.3f}s")

    font_path = DEFAULT_FONT if DEFAULT_FONT.exists() else FALLBACK_FONT
    banner_png = work / "banner.png"
    make_banner(args.hook, banner_png, font_path)

    extract_frames(source, frames_dir, src_dur)
    rows = score_all(frames_dir)
    wav = decode_wav(music, work / "music.wav")
    drop = find_drop(wav)
    edl = pick_edl(rows, usable_end, clip_dur, n_clips)
    print("EDL:")
    for c in edl:
        flag = " REVEAL" if c["reveal"] else ""
        print(
            f"  clip{c['i']:02d}  video {c['t0']:.3f}-{c['t1']:.3f}  "
            f"src {c['src_start']:.3f}-{c['src_end']:.3f}  score={c['score']:.1f}{flag}"
        )
    reveal_t = edl[REVEAL_INDEX]["t0"]
    music_start = drop - reveal_t
    if music_start < 0:
        music_start = 0.0
    print(
        f"Music start offset={music_start:.3f}s  "
        f"(drop {drop:.2f}s aligns near reveal {reveal_t:.2f}s -> video drop @ {drop - music_start:.2f}s)"
    )
    write_caption_txt(out_path, music, args.hook)

    raw = work / "raw_concat.mp4"
    print("Pass 1: cutting source clips…")
    render_raw(source, edl, raw, target)
    print("Pass 2: layout + music (no captions, no watermark)…")
    render_final(raw, music, banner_png, music_start, target, out_path)
    report = qc(out_path, work, target, layout)
    print_qc(report)
    if not report["pass"] and report["fails"]:
        print("Re-rendering once after blacklisting failed source seconds…")
        bl = set()
        for t, kind, why in report["fails"]:
            ci = min(int(t / clip_dur), len(edl) - 1)
            src = edl[ci]["src_start"] + (t - edl[ci]["t0"])
            bl.add(round(math.floor(src), 3))
            bl.add(math.floor(src))
            print(f"  blacklist src ~{src:.2f}s from output t={t}s")
        edl = pick_edl(rows, usable_end, clip_dur, n_clips, blacklist=bl)
        print("New EDL:")
        for c in edl:
            flag = " REVEAL" if c["reveal"] else ""
            print(f"  clip{c['i']:02d}  src {c['src_start']:.3f}-{c['src_end']:.3f}  score={c['score']:.1f}{flag}")
        render_raw(source, edl, raw, target)
        render_final(raw, music, banner_png, music_start, target, out_path)
        report = qc(out_path, work, target, layout)
        print_qc(report)
    (work / "qc_report.json").write_text(
        json.dumps(
            {**report, "edl": edl, "music_start": music_start, "drop": drop},
            indent=2,
            default=str,
        )
    )
    print(f"OUTPUT {out_path}  size={out_path.stat().st_size}  dur={report['duration']:.3f}s  pass={report['pass']}")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
