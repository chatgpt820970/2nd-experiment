# 2nd-experiment

Standalone vertical Shorts renderer. Takes a 16:9 source clip, cuts it on the beat, and lays it onto a 9:16 canvas with a blurred ambient background and a white hook banner.

**No on-screen captions and no watermark.** The hook stays on the top banner only.

v2 adds **category presets**, **automatic source fetching** (`--auto`, via yt-dlp) and a **self-healing fallback loop** with a run log.

## Setup

Needs `ffmpeg`, `ffprobe`, and Python 3.10+:

```bash
pip install -r requirements.txt        # numpy, Pillow, yt-dlp
python3 scripts/download_music.py      # all tracks in assets/music.json (gitignored)
```

If a track is missing at render time, `make_video.py` downloads just that track. If `yt-dlp` is missing, `--auto` installs it with pip.

## Quick start

```bash
# Fully automatic: find an official trailer/highlights clip, render, QC
python3 make_video.py --category bollywood --auto --out out/bollywood.mp4

# Your own source file, category preset for hook + music + pacing
python3 make_video.py --source clip.mp4 --category cricket --out out/cricket.mp4

# Everything manual (original v1 behaviour)
python3 make_video.py --source foolnight.mp4 --hook "Nobody was ready\nfor Fool Night" \
  --music assets/music/ncs_lavida.mp3 --out out/foolnight_clean.mp4

# See which sources --auto would pick, without rendering
python3 make_video.py --category south --auto --list-sources
```

Output folders are created automatically. Each render writes, next to the mp4:

- `<name>.caption.txt` — post text with hashtags, source title/link and the **required music credit**
- `<name>.json` — summary: category, hook, source title + URL, music + credit, duration, QC result, failed attempts
- `<name>.log` — the full run log (appended on each run)

## Flags

| Flag | Meaning |
| --- | --- |
| `--out PATH` | Output mp4 (required unless `--list-sources`) |
| `--source PATH` | Local source video. Optional with `--auto` |
| `--category NAME` | Preset (table below). Aliases: `bhakti`/`bhagwan` → devotional, `love` → hindi_love, `serial` → tv_serial, `celebrity` → indian_celebrity |
| `--auto` | Search YouTube for the category and download an official 16:9 clip (≤1080p, 60s–10min) |
| `--hook TEXT` | Banner text, `\n` for line 2 (max 2 lines). Default: a preset hook |
| `--hook-index N` | Use preset hook N. Default: hook matching the source title (e.g. Ramayana → "Jai Shri Ram"), else picked by output name |
| `--music FILE` | Track file name from `assets/music.json` or a path. Default: the preset's track list |
| `--bpm N` / `--clips N` | Override BPM / number of cuts |
| `--max-sources N` | `--auto`: how many search results to try (default 4) |
| `--exclude-id ID` | `--auto`: skip a YouTube id (repeatable), e.g. to avoid reusing a source |
| `--list-sources` | `--auto`: print ranked candidates and exit |
| `--work DIR` / `--log FILE` | Scratch dir (default `work/<out name>`) / run log (default `<out>.log`) |

## Categories

| Category | Label | Example hook | Main track | Pacing |
| --- | --- | --- | --- | --- |
| `bollywood` | Bollywood | Ye trailer dekh ke / rongte khade ho gaye | GxL - MONTAGEM INDIA (NCS, 129 BPM) | ~2.3s cuts, ~26s |
| `south` | South Indian cinema | South wale level / hi alag hai | THIRST - fellshortofhell (NCS, 152 BPM) | ~2.2s cuts, ~26s |
| `hollywood` | Hollywood | Hollywood ne phir / se kar dikhaya | Ailow - Godless (NCS, 152 BPM) | ~2.3s cuts, ~26s |
| `indian_celebrity` | Indian celebrities | Superstar ka swag / hi alag hai | Conni - Tequila In My Cup (NCS, 129 BPM) | ~2.3s cuts, ~26s |
| `cricket` | Cricket | Ye shot dekh ke / stadium pagal | Slowboy, Zeli - Adrenaline (NCS, 129 BPM) | ~2.2s cuts, ~26s |
| `devotional` | Devotional / Bhakti | Jai Shri Ram / Rongte khade ho gaye | Kevin MacLeod - Intrepid (incompetech, 89 BPM) | ~2.7s cuts, ~27s |
| `hindi_love` | Hindi love story | Pyaar ho toh / aisa ho | c80 - teamo (NCS, 117 BPM) | ~2.6s cuts, ~26s |
| `tv_serial` | Hindi TV serial | Serial mein aaya / sabse bada twist | Kevin MacLeod - Heartbreaking (incompetech, 78 BPM) | ~2.4s cuts, ~24s |
| `world_best` | World's best | Duniya ki sabse / badi movie? | Kevin MacLeod - Impact Prelude (incompetech, 161 BPM) | ~2.2s cuts, ~26s |

Each preset (in `categories.py`) defines several Hinglish hooks, search queries, title rules (must look like an official trailer / teaser / promo / highlights), preferred official channels, cut length and target length, and a primary track plus fallbacks. Beats-per-cut is derived from the track BPM so cuts stay on the beat (about 2.2–2.8s each). Videos come out 20–40s.

### Source rules for `--auto`

- Official material only: title must contain trailer / teaser / glimpse / promo / highlights; first pass requires a verified channel (`tv_serial` also requires an official TV channel). If nothing passes, a relaxed second pass runs.
- 16:9 (aspect ≥ 1.6), 60s to 10 min, downloaded at ≤1080p (H.264 preferred).
- Always skipped: reactions, reviews, fan-made, edits, lyric/audio uploads, full movies, Shorts, and any title with sexual or suggestive words (see `BLOCK_WORDS`). Movie categories also skip OTT series/episodes.
- Downloads are cached in `work/sources/` (gitignored).

## Self-healing fallback loop

`make_video.py` keeps trying until a video passes QC, and only fails after every option is used up:

1. **Search**: each query is retried 3×. If no result passes strict rules, a relaxed pass runs.
2. **Source**: next search result if a download fails, the clip is not 16:9, too short, or has too little clean footage. A failed download is retried at **720p**, then **480p**.
3. **Music**: next track in the preset list, then generic fallbacks, if a track is missing, fails to download (3 tries, atomic write), is silent, or breaks the render.
4. **QC**: up to 3 render rounds per source/track. Failed output seconds (and their neighbours) are blacklisted and new cuts are picked. A background that is too dark gets brighter each round. If the source has too few clean windows, fewer cuts are used (still ≥20s).
5. **Unexpected errors** are logged with a traceback and the loop moves on.

Every step goes to the run log. If all fail, the script exits non-zero with a list of every attempt and why it failed.

Exit codes: `0` success, `1` all fallbacks exhausted, `2` source file not found, `3` no search results.

## Layout spec (1080x1920, 30 fps)

| Layer | Placement | Notes |
| --- | --- | --- |
| Canvas | `1080x1920` (9:16), 30 fps, `libx264`, `crf=18`, `yuv420p` | AAC 192k audio |
| Blurred background | full frame | built from the active picture (letterbox bars ignored), `boxblur=30:5`, brightness auto (-0.08 / 0 / +0.08 by source brightness) |
| Sharp plate | `1080x608` for a 16:9 source, vertically centered with the banner | **no crop**: the full source frame (including any letterbox bars) is scaled to 1080 wide. Taller sources are fit by height |
| Hook banner | white `1080x240`, flush on top of the plate | Archivo Black, bold black text, max 2 lines, auto-shrinks to fit. Devanagari hooks use Noto Sans Devanagari if installed |
| On-screen captions | **none** | |
| Watermark | **none** | |

Pacing: skip the first ~6% (max 9s) and last ~10% (max 16s) of the source. Shots are spread out (≥7s apart where possible), and the strongest shot lands on the music drop.

QC: the source is scored at 2 fps on the active picture area. A second is rejected if either sample is dark, a solid red card, a static text card, or a flat colour card. The final video is checked at 2 fps for resolution, pix_fmt, 30 fps, 20–40s, audible audio (mean volume above -45 dB), a background that isn't too dark, and the same content rules on the plate.

## Music credit rule

NCS tracks are free for YouTube / Twitch UGC, including monetised videos, **only if the credit is in the post description**. Kevin MacLeod tracks are CC BY 4.0 and also **need the credit**. The right credit is written into `<name>.caption.txt` and `<name>.json`. Do not skip it.

| File | Track | Source | BPM | License |
| --- | --- | --- | --- | --- |
| `ncs_lavida.mp3` | Cryjaxx, MVRPHiN & Lucy Malfroy - LA VIDA! | NCS | 129 | NCS Usage Policy: free for YouTube/Twitch UGC incl. monetised, credit required in description |
| `ncs_montagemindia.mp3` | GxL - MONTAGEM INDIA | NCS | 129 | NCS Usage Policy: free for YouTube/Twitch UGC incl. monetised, credit required in description |
| `ncs_fellshortofhell.mp3` | THIRST - fellshortofhell | NCS | 152 | NCS Usage Policy: free for YouTube/Twitch UGC incl. monetised, credit required in description |
| `ncs_godless.mp3` | Ailow - Godless | NCS | 152 | NCS Usage Policy: free for YouTube/Twitch UGC incl. monetised, credit required in description |
| `ncs_adrenaline.mp3` | Slowboy, Zeli - Adrenaline | NCS | 129 | NCS Usage Policy: free for YouTube/Twitch UGC incl. monetised, credit required in description |
| `ncs_teamo.mp3` | c80 - teamo | NCS | 117 | NCS Usage Policy: free for YouTube/Twitch UGC incl. monetised, credit required in description |
| `ncs_fireflies.mp3` | Krezus & surreal_dvd - Fireflies | NCS | 172 | NCS Usage Policy: free for YouTube/Twitch UGC incl. monetised, credit required in description |
| `ncs_flowersinmyhead.mp3` | DIECXLD, Prod. 94 - flowers in my head | NCS | 86 | NCS Usage Policy: free for YouTube/Twitch UGC incl. monetised, credit required in description |
| `ncs_tequilainmycup.mp3` | Conni - Tequila In My Cup | NCS | 129 | NCS Usage Policy: free for YouTube/Twitch UGC incl. monetised, credit required in description |
| `ncs_favela.mp3` | MXZI, Deno - FAVELA | NCS | 86 | NCS Usage Policy: free for YouTube/Twitch UGC incl. monetised, credit required in description |
| `km_Impact_Prelude.mp3` | Kevin MacLeod - Impact Prelude | incompetech | 161 | CC BY 4.0 |
| `km_Heartbreaking.mp3` | Kevin MacLeod - Heartbreaking | incompetech | 78 | CC BY 4.0 |
| `km_Intrepid.mp3` | Kevin MacLeod - Intrepid | incompetech | 89 | CC BY 4.0 |

## Files

- `make_video.py` — renderer, QC and fallback loop
- `categories.py` — category presets, block words
- `sourcing.py` — yt-dlp search, filtering, ranking, download
- `scripts/download_music.py` — fetch tracks from `assets/music.json`
- `assets/music.json` — track metadata and credits
- `fonts/ArchivoBlack-Regular.ttf` — [Archivo Black](https://fonts.google.com/specimen/Archivo+Black), SIL Open Font License

Do not commit `.mp3`, `.mp4`, `out/` or `work/`.

Sources downloaded with `--auto` are third-party trailers and highlights. Check the platform's rules and the rights holder's terms before you post.
