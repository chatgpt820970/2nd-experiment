"""Template-free static-overlay (logo / channel bug / scorebug) detector.

Detection only: nothing is blurred, cropped or painted over. Seconds (and
20s chunks) with an overlay are marked so cuts can be picked from logo-free
windows. A source is only rejected when too little clean footage remains.

Idea: real footage changes from shot to shot, an overlay does not. We mark
pixels with a strong horizontal gradient (|dI/dx|) in each frame; pixels that
are "edge" in most frames across many different shots are a static overlay.
Only |dI/dx| is used, so the flat horizontal border of letterbox bars does not
count, but a logo sitting inside the bars does.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

W = 480                 # analysis width
EDGE = 30.0             # |dI/dx| threshold (0-255 luma)
CORNER_W, CORNER_H = 0.20, 0.24
PERSIST_FREQ, PERSIST_PX = 0.45, 40     # whole-source test
WIN, STEP = 16, 4                       # 8 s windows, 2 s step (2 fps)
WIN_FREQ, WIN_PX, WIN_CENTER_MAX = 0.85, 30, 6


def _gray_frames(path: Path, fps: float = 2.0, start: float = 0.0, dur: float | None = None,
                 crop: tuple[int, int, int, int] | None = None) -> np.ndarray:
    vf = []
    if crop:
        x, y, w, h = crop
        vf.append(f"crop={w}:{h}:{x}:{y}")
    vf += [f"fps={fps}", f"scale={W}:-2", "format=gray"]
    cmd = ["ffmpeg", "-v", "error", "-nostdin"]
    if start:
        cmd += ["-ss", f"{start:.2f}"]
    cmd += ["-i", str(path)]
    if dur:
        cmd += ["-t", f"{dur:.2f}"]
    cmd += ["-vf", ",".join(vf), "-f", "rawvideo", "-"]
    r = subprocess.run(cmd, capture_output=True, timeout=900)
    raw = np.frombuffer(r.stdout, dtype=np.uint8)
    probe = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-frames:v", "1",
                            "-vf", ",".join(vf[:-3] + [f"scale={W}:-2", "format=gray"]),
                            "-f", "rawvideo", "-"], capture_output=True, timeout=120)
    h = len(probe.stdout) // W
    if h <= 0 or raw.size < h * W:
        return np.zeros((0, 1, W), np.uint8)
    return raw[: (raw.size // (h * W)) * h * W].reshape(-1, h, W)


def _edges(frames: np.ndarray) -> np.ndarray:
    f = frames.astype(np.int16)
    gx = np.abs(np.diff(f, axis=2, prepend=f[:, :, :1]))
    return gx > EDGE


def _regions(h: int, w: int):
    cw, ch = int(w * CORNER_W), int(h * CORNER_H)
    return {
        "top-left": (slice(0, ch), slice(0, cw)),
        "top-right": (slice(0, ch), slice(w - cw, w)),
        "bottom-left": (slice(h - ch, h), slice(0, cw)),
        "bottom-right": (slice(h - ch, h), slice(w - cw, w)),
    }, (slice(int(h * .3), int(h * .7)), slice(int(w * .3), int(w * .7)))


def corner_counts(freq: np.ndarray, thr: float) -> tuple[dict, int]:
    regions, center = _regions(*freq.shape)
    return ({k: int((freq[r] >= thr).sum()) for k, r in regions.items()},
            int((freq[center] >= thr).sum()))


def analyse_source(path: Path, dur: float, head: float, usable_end: float, log=print) -> dict:
    """Returns {'persistent': str|None, 'bad_seconds': set[int], 'counts': {...}}."""
    frames = _gray_frames(path, start=head, dur=max(1.0, usable_end - head))
    if len(frames) < WIN:
        return {"persistent": None, "bad_seconds": set(), "counts": {}}
    e = _edges(frames)
    counts, center = corner_counts(e.mean(0), PERSIST_FREQ)
    worst = max(counts, key=counts.get)
    persistent = worst if counts[worst] >= PERSIST_PX and center < PERSIST_PX else None
    bad, flagged, total = set(), 0, 0
    for i in range(0, len(e) - WIN + 1, STEP):
        total += 1
        c, cen = corner_counts(e[i:i + WIN].mean(0), WIN_FREQ)
        if max(c.values()) >= WIN_PX and cen <= WIN_CENTER_MAX:
            flagged += 1
            for k in range(i, i + WIN):
                bad.add(int(head + k / 2.0))
    if persistent is None and total and flagged / total >= 0.5:
        persistent = "most windows"
    # Chunk-level persistence: a logo only in the intro/outro must not kill the
    # whole source — mark those 20s chunks as bad and keep clean windows.
    chunk = 40  # 20 s at 2 fps
    for i in range(0, len(e), chunk):
        sl = e[i:i + chunk]
        if len(sl) < WIN:
            break
        c, cen = corner_counts(sl.mean(0), PERSIST_FREQ)
        if max(c.values()) >= PERSIST_PX and cen < PERSIST_PX:
            for k in range(i, min(i + chunk, len(e))):
                bad.add(int(head + k / 2.0))
    log(f"  logo check: corners {counts} center {center} | {flagged}/{total} windows flagged"
        + (f" | overlay ({persistent})" if persistent else "")
        + f" | {len(bad)} logo second(s) skipped")
    return {"persistent": persistent, "bad_seconds": bad, "counts": counts}


def check_output(path: Path, plate: tuple[int, int, int, int], log=print) -> dict:
    """Static-overlay test on the sharp plate of a rendered video (many shots)."""
    frames = _gray_frames(path, fps=2.0, crop=plate)
    if len(frames) < 10:
        return {"logo": False, "counts": {}}
    freq = _edges(frames).mean(0)
    counts, center = corner_counts(freq, 0.6)
    logo = max(counts.values()) >= 25 and center < 25
    log(f"  output logo check: corners {counts} center {center} -> {'LOGO' if logo else 'clean'}")
    return {"logo": bool(logo), "counts": counts}



def clean_span(head: float, usable_end: float, bad_seconds, min_span: float = 30.0):
    """Largest contiguous logo-free span of at least min_span seconds, or None."""
    import math
    start, end = int(math.floor(head)), int(math.ceil(usable_end))
    bad = set(bad_seconds or ())
    best = None  # (length, s, e)
    s = start
    while s < end:
        if s in bad:
            s += 1
            continue
        e = s
        while e < end and e not in bad:
            e += 1
        length = e - s
        if length >= min_span and (best is None or length > best[0]):
            best = (length, float(max(head, s)), float(min(usable_end, e)))
        s = e + 1
    if not best:
        return None
    return best[1], best[2]


def clean_second_count(head: float, usable_end: float, bad_seconds) -> int:
    bad = set(bad_seconds or ())
    return sum(1 for t in range(int(head), int(usable_end)) if t not in bad)


# ---------------------------------------------------------------- on-screen text (credits / brand cards)
_OCR = None


def _ocr():
    global _OCR
    if _OCR is None:
        from rapidocr_onnxruntime import RapidOCR  # optional dependency
        _OCR = RapidOCR()
    return _OCR


def text_boxes(image, min_h_frac: float = 0.03, allow_subtitles: bool = True) -> list[str]:
    """Large overlaid text in a frame (credit names, title / brand cards).

    Burned-in dialogue subtitles (bottom band, centred) are allowed. Returns the
    text found, empty list = clean. Raises ImportError if the OCR model is missing.
    """
    import numpy as _np
    from PIL import Image as _Image
    im = _np.array(image.convert("RGB")) if isinstance(image, _Image.Image) else image
    h, w = im.shape[:2]
    res, _ = _ocr()(im, use_det=True, use_cls=False, use_rec=True)
    found = []
    for box, txt, conf in res or []:
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        bh = max(ys) - min(ys)
        if bh < min_h_frac * h or float(conf) < 0.5 or len(str(txt).strip()) < 3:
            continue
        cx = (min(xs) + max(xs)) / 2
        if allow_subtitles and min(ys) > 0.72 * h and abs(cx - w / 2) < 0.2 * w:
            continue  # dialogue subtitle line
        found.append(str(txt).strip())
    return found


def text_seconds(frame_files, head: float, log=print) -> dict:
    """{source second: text} for 2 fps frames starting at `head`."""
    from PIL import Image as _Image
    out = {}
    for i, fp in enumerate(frame_files):
        txt = text_boxes(_Image.open(fp))
        if txt:
            out.setdefault(int(head + i / 2.0), " / ".join(txt)[:60])
    log(f"  text check: {len(out)} second(s) with credit/title text skipped")
    return out
