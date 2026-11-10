"""Speech detection, tempo estimation and the dialogue + music mix.

Speech detection fallback chain (self-healing):
  1. Silero VAD (ships with faster-whisper, ONNX, no torch)
  2. webrtcvad (aggressiveness 3)
  3. energy + mid/side heuristic (numpy only)
"""
from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np

SR = 48000


class AudioError(RuntimeError):
    pass


# ---------------------------------------------------------------- decoding
def decode(path: Path, sr: int = SR, channels: int = 2, start: float = 0.0, dur: float | None = None) -> np.ndarray:
    """Decode any audio/video file to float32 [n, channels]. Returns zeros-length array if no audio."""
    cmd = ["ffmpeg", "-v", "error", "-nostdin"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(path)]
    if dur:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-vn", "-ac", str(channels), "-ar", str(sr), "-f", "s16le", "-"]
    r = subprocess.run(cmd, capture_output=True, timeout=600)
    if r.returncode != 0:
        raise AudioError(f"decode failed for {Path(path).name}: {r.stderr.decode(errors='ignore')[-200:]}")
    a = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    return a.reshape(-1, channels) if a.size else np.zeros((0, channels), np.float32)


def write_wav(path: Path, audio: np.ndarray, sr: int = SR):
    a = np.clip(audio, -1, 1)
    pcm = (a * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(pcm.shape[1])
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def rms_db(x: np.ndarray) -> float:
    if x.size == 0:
        return -120.0
    return float(20 * np.log10(np.sqrt(np.mean(np.square(x, dtype=np.float64))) + 1e-9))


# ---------------------------------------------------------------- speech
def _merge(segs, gap=0.25, min_len=0.3):
    out = []
    for s, e in sorted(segs):
        if out and s - out[-1][1] < gap:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(round(s, 3), round(e, 3)) for s, e in out if e - s >= min_len]


def _vad_silero(mono16: np.ndarray):
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    ts = get_speech_timestamps(mono16, VadOptions(threshold=0.5, min_speech_duration_ms=300,
                                                  min_silence_duration_ms=250, speech_pad_ms=60))
    return [(t["start"] / 16000, t["end"] / 16000) for t in ts]


def _vad_webrtc(mono16: np.ndarray):
    import webrtcvad
    v = webrtcvad.Vad(3)
    pcm = (np.clip(mono16, -1, 1) * 32767).astype(np.int16).tobytes()
    step = 480 * 2  # 30 ms @16k, bytes
    flags = [v.is_speech(pcm[i:i + step], 16000) for i in range(0, len(pcm) - step, step)]
    segs, start = [], None
    for i, f in enumerate(flags + [False]):
        t = i * 0.03
        if f and start is None:
            start = t
        elif not f and start is not None:
            segs.append((start, t))
            start = None
    return segs


def _vad_energy(stereo: np.ndarray, sr: int):
    """Dialogue in trailers is mostly centre-panned: high mid/side ratio + loud enough."""
    hop = int(sr * 0.05)
    mid = stereo.mean(1)
    side = (stereo[:, 0] - stereo[:, 1]) / 2 if stereo.shape[1] > 1 else np.zeros_like(mid)
    n = len(mid) // hop
    m = np.sqrt(np.mean(mid[: n * hop].reshape(n, hop) ** 2, 1) + 1e-12)
    s = np.sqrt(np.mean(side[: n * hop].reshape(n, hop) ** 2, 1) + 1e-12)
    loud = 20 * np.log10(m) > np.percentile(20 * np.log10(m), 40)
    centred = 20 * np.log10(m / s) > 9
    flags = np.convolve((loud & centred).astype(float), np.ones(6) / 6, "same") > 0.6
    segs, start = [], None
    for i, f in enumerate(list(flags) + [False]):
        t = i * 0.05
        if f and start is None:
            start = t
        elif not f and start is not None:
            segs.append((start, t))
            start = None
    return segs


def detect_speech(source: Path, log=print) -> tuple[list[tuple[float, float]], str]:
    """Return merged speech segments (seconds) and the method that worked."""
    try:
        mono16 = decode(source, sr=16000, channels=1)[:, 0]
    except AudioError as e:
        log(f"  speech: no audio ({e})")
        return [], "none"
    if mono16.size < 16000 or float(np.abs(mono16).max()) < 1e-3:
        return [], "silent"
    for name, fn in (("silero", lambda: _vad_silero(mono16)),
                     ("webrtcvad", lambda: _vad_webrtc(mono16)),
                     ("energy", lambda: _vad_energy(decode(source, sr=16000, channels=2), 16000))):
        try:
            segs = _merge(fn())
            log(f"  speech: {len(segs)} segments via {name}")
            return segs, name
        except Exception as e:  # missing module / runtime error -> next method
            log(f"  speech: {name} unavailable ({e.__class__.__name__}: {str(e)[:80]})")
    return [], "none"


def clarity_db(stereo: np.ndarray, s: float, e: float, sr: int = SR) -> float:
    """Mid/side ratio during a speech segment: higher = dialogue sits clearly in front."""
    seg = stereo[int(s * sr):int(e * sr)]
    if seg.size == 0 or seg.shape[1] < 2:
        return 0.0
    mid = seg.mean(1)
    side = (seg[:, 0] - seg[:, 1]) / 2
    return rms_db(mid) - rms_db(side)


# ---------------------------------------------------------------- tempo / drop
def estimate_bpm(audio: np.ndarray, sr: int = SR, lo: float = 75, hi: float = 175) -> float:
    """Onset-autocorrelation tempo estimate on mono audio (good enough for cut pacing)."""
    mono = audio.mean(1) if audio.ndim > 1 else audio
    sr2 = 11025
    mono = np.interp(np.arange(0, len(mono), sr / sr2), np.arange(len(mono)), mono) if len(mono) else mono
    n_fft, hop = 1024, 256
    if len(mono) < n_fft * 50:
        raise AudioError("audio too short for tempo")
    frames = np.lib.stride_tricks.sliding_window_view(mono, n_fft)[::hop] * np.hanning(n_fft)
    spec = np.abs(np.fft.rfft(frames, axis=1))
    flux = np.maximum(0, np.diff(np.log1p(spec), axis=0)).sum(1)
    flux = flux - np.convolve(flux, np.ones(16) / 16, "same")
    flux = np.maximum(flux, 0)
    fps = sr2 / hop
    ac = np.correlate(flux, flux, "full")[len(flux) - 1:]
    lags = np.arange(len(ac))
    bpm = 60 * fps / np.maximum(lags, 1)
    mask = (bpm >= lo) & (bpm <= hi)
    weight = np.exp(-0.5 * (np.log2(bpm / 120) / 0.9) ** 2)  # mild prior around 120
    score = np.where(mask, ac * weight, -np.inf)
    lag = int(np.argmax(score))
    return float(round(60 * fps / lag, 1))


def best_section(audio: np.ndarray, length: float, sr: int = SR, skip: float = 12.0) -> float:
    """Start time of the loudest sustained section (chorus / drop) of a song."""
    mono = audio.mean(1)
    hop = int(sr * 0.5)
    n = len(mono) // hop
    if n * 0.5 < length + skip + 2:
        return 0.0
    r = np.sqrt(np.mean(mono[: n * hop].reshape(n, hop) ** 2, 1))
    win = int(length / 0.5)
    cs = np.convolve(r, np.ones(win) / win, "valid")
    first = int(skip / 0.5)
    last = len(cs) - int(4 / 0.5)
    if last <= first:
        return 0.0
    return float((first + int(np.argmax(cs[first:last]))) * 0.5)


# ---------------------------------------------------------------- mix
def _envelope(n: int, intervals, sr: int, on: float, off: float, ramp: float) -> np.ndarray:
    """Piecewise gain: `on` inside intervals, `off` outside, linear ramps of `ramp` seconds."""
    env = np.full(n, off, np.float32)
    r = max(1, int(ramp * sr))
    for s, e in intervals:
        a, b = max(0, int(s * sr)), min(n, int(e * sr))
        if b <= a:
            continue
        env[a:b] = on
        lo = max(0, a - r)
        env[lo:a] = np.maximum(env[lo:a], np.linspace(off, on, a - lo, dtype=np.float32)) if on > off else \
            np.minimum(env[lo:a], np.linspace(off, on, a - lo, dtype=np.float32))
        hi = min(n, b + r)
        env[b:hi] = np.maximum(env[b:hi], np.linspace(on, off, hi - b, dtype=np.float32)) if on > off else \
            np.minimum(env[b:hi], np.linspace(on, off, hi - b, dtype=np.float32))
    return env


def build_mix(src_audio: np.ndarray, edl: list[dict], music: np.ndarray, target: float,
              duck: float = 0.25, sr: int = SR) -> tuple[np.ndarray, list[tuple[float, float]], dict]:
    """Music bed + original dialogue from the cut clips, music ducked under speech.

    edl clips carry src_start/src_end/t0 and optional 'speech' = [(s, e)] in source time.
    Only speech inside dialogue clips is let through; everything else from the source
    (its own score, half sentences in action cuts) is muted.
    """
    n = int(round(target * sr))
    dialog = np.zeros((n, 2), np.float32)
    speech_out = []
    for c in edl:
        if not c.get("speech"):
            continue
        a, b = int(c["src_start"] * sr), int(c["src_end"] * sr)
        seg = src_audio[a:b]
        o = int(round(c["t0"] * sr))
        seg = seg[: max(0, n - o)]
        local = [(max(0.0, s - c["src_start"]), min(c["src_end"], e) - c["src_start"]) for s, e in c["speech"]]
        gate = _envelope(len(seg), [(s - 0.10, e + 0.12) for s, e in local], sr, 1.0, 0.0, 0.06)
        line = seg * gate[:, None]
        # per-clip loudness so a quiet line is as clear as a loud one (~ -15 dBFS, gain <= 8x)
        core = np.concatenate([line[int(s * sr):int(e * sr)] for s, e in local]) if local else line
        ldb = rms_db(core)
        if ldb > -70:
            line = line * min(8.0, 10 ** ((-15 - ldb) / 20))
        dialog[o:o + len(seg)] += line
        speech_out += [(c["t0"] + s, c["t0"] + e) for s, e in local]
    # loudness: dialogue speech ~ -15 dBFS, music bed ~ -17 dBFS before ducking
    if speech_out:
        idx = np.concatenate([np.arange(int(s * sr), min(n, int(e * sr))) for s, e in speech_out])
        d_db = rms_db(dialog[idx]) if idx.size else -120
        if d_db > -80:
            dialog *= min(6.0, 10 ** ((-15 - d_db) / 20))
    m = np.zeros((n, 2), np.float32)
    m[: min(n, len(music))] = music[:n]
    m_db = rms_db(m)
    if m_db > -80:
        m *= min(4.0, 10 ** ((-17 - m_db) / 20))
    duck_env = _envelope(n, [(s - 0.15, e + 0.20) for s, e in speech_out], sr, duck, 1.0, 0.18)
    fade = np.ones(n, np.float32)
    fi, fo = int(0.25 * sr), int(1.2 * sr)
    fade[:fi] = np.linspace(0, 1, fi)
    fade[-fo:] = np.minimum(fade[-fo:], np.linspace(1, 0, fo))
    mix = m * duck_env[:, None] + dialog
    mix *= fade[:, None]
    peak = float(np.abs(mix).max()) or 1.0
    if peak > 0.97:  # soft limit
        mix = np.tanh(mix / peak * 1.6) / np.tanh(1.6) * 0.97
    stats = {"speech_intervals": [(round(s, 2), round(e, 2)) for s, e in speech_out]}
    ducked = m * duck_env[:, None]
    per_line = []
    for s, e in speech_out:
        a, b = int(s * sr), min(n, int(e * sr))
        if b - a > sr * 0.2:
            per_line.append(round(rms_db(dialog[a:b]) - rms_db(ducked[a:b]), 1))
    stats["per_line_margin_db"] = per_line
    if speech_out:
        sp_idx = np.concatenate([np.arange(int(s * sr), min(n, int(e * sr))) for s, e in speech_out])
        stats["dialogue_db_in_speech"] = rms_db(dialog[sp_idx])
        stats["music_db_in_speech"] = rms_db((m * duck_env[:, None])[sp_idx])
        stats["music_db_outside"] = rms_db(np.delete(m, sp_idx, axis=0)) if sp_idx.size < n else -120
    return mix.astype(np.float32), speech_out, stats


def build_source_only_mix(src_audio: np.ndarray, edl: list[dict], target: float,
                          sr: int = SR) -> tuple[np.ndarray, list[tuple[float, float]], dict]:
    """Stitch the original source audio of each cut. No added music bed."""
    n = int(round(target * sr))
    out = np.zeros((n, 2), np.float32)
    speech_out = []
    if src_audio.ndim == 1:
        src_audio = np.stack([src_audio, src_audio], 1)
    if src_audio.size and src_audio.shape[1] == 1:
        src_audio = np.repeat(src_audio, 2, axis=1)
    for c in edl:
        a, b = int(c["src_start"] * sr), int(c["src_end"] * sr)
        seg = src_audio[a:b] if src_audio.size else np.zeros((0, 2), np.float32)
        o = int(round(c["t0"] * sr))
        seg = seg[: max(0, n - o)]
        if len(seg):
            out[o:o + len(seg)] = seg
        for s, e in c.get("speech") or []:
            speech_out.append((c["t0"] + max(0.0, s - c["src_start"]),
                               c["t0"] + min(c["src_end"], e) - c["src_start"]))
    fade = np.ones(n, np.float32)
    fi, fo = int(0.25 * sr), int(1.2 * sr)
    if fi < n:
        fade[:fi] = np.linspace(0, 1, fi)
    if fo < n:
        fade[-fo:] = np.minimum(fade[-fo:], np.linspace(1, 0, fo))
    out *= fade[:, None]
    peak = float(np.abs(out).max()) or 1.0
    if peak > 0.97:
        out = np.tanh(out / peak * 1.6) / np.tanh(1.6) * 0.97
    stats = {
        "speech_intervals": [(round(s, 2), round(e, 2)) for s, e in speech_out],
        "source_audio_only": True,
    }
    return out.astype(np.float32), speech_out, stats
