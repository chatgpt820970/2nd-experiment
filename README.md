# 2nd-experiment

Standalone vertical Shorts renderer. Takes a 16:9 source clip, cuts it on the beat, and lays it onto a 9:16 canvas with a blurred ambient background and a white hook banner.

**No on-screen captions and no watermark.** The hook stays on the top banner only.

v2 added **category presets**, **automatic source fetching** (`--auto`, via yt-dlp) and a **self-healing fallback loop** with a run log.

v3 adds popular songs, original dialogue mixed under a ducked music bed, logo-free source picking (nothing is inpainted, blurred or cropped), and GitHub Actions rendering (`.github/workflows/render.yml`).

v5:

- **Trending remix/mashup, never NCS**: songs are fetched from SoundCloud, JioSaavn, Audiomack, archive.org and Dailymotion (hosts that still download on GitHub runner IPs). YouTube is only tried if it is not blocked. NCS, Kevin MacLeod and generic library music are blacklisted. If no song can be fetched, the original source audio is used. Captions never mention NCS.
- **South fallbacks**: more Telugu / Tamil / Kannada / Malayalam Dailymotion and archive.org queries, a higher fallback candidate limit, and logo detection that prefers clean time windows inside a source before rejecting it.

## Setup

Needs `ffmpeg`, `ffprobe`, and Python 3.10+:

```bash
pip install -r requirements.txt        # numpy, Pillow, yt-dlp, faster-whisper (VAD), webrtcvad-wheels, rapidocr-onnxruntime
```

yt-dlp needs a JavaScript runtime for YouTube (Deno by default; Node also works). If `yt-dlp` is missing, `--auto` installs it with pip. Songs are fetched at render time; there are no local NCS / library fallback tracks.

## Quick start

```bash
# Fully automatic: official trailer + trending song + dialogue, render, QC
python3 make_video.py --category bollywood --auto --out out/bollywood.mp4

# Pin a source (YouTube URL or id), song still auto
python3 make_video.py --category bollywood --source-url fneuVQ7uO_w --out out/drishyam.mp4

# Batch: 2nd-ranked source and song, so repeat runs don't reuse the same pair
python3 make_video.py --category south --auto --source-offset 1 --song-offset 1 --out out/south_2.mp4

# Your own source file, category preset for hook + music + pacing
python3 make_video.py --source clip.mp4 --category cricket --out out/cricket.mp4

# Own source file, original audio (no song search)
python3 make_video.py --source clip.mp4 --category cricket --no-song-search --out out/cricket.mp4

# See which sources --auto would pick, without rendering
python3 make_video.py --category south --auto --list-sources
```

Output folders are created automatically. Each render writes, next to the mp4:

- `<name>.caption.txt` — post text with hashtags, source title/link and the song title + artist
- `<name>.json` — summary: category, hook, source title + URL, song (title, artist, URL), dialogue stats, duration, QC result, failed attempts
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
| `--music FILE` | Song file or path. Default: a searched remix/mashup, then original source audio |
| `--source-url URL` | YouTube URL or id to use as source (repeatable, tried first). Implies `--auto` |
| `--source-offset N` | `--auto`: skip the first N ranked sources (batch runs) |
| `--no-song-search` | Do not search for a song; use the original source audio |
| `--song-offset N` | Skip the first N ranked songs (batch runs) |
| `--duck X` | Music gain while characters speak (default `0.25`) |
| `--bpm N` / `--clips N` | Override BPM / number of cuts |
| `--max-sources N` | `--auto`: how many search results to try (default 4; the workflow uses 12) |
| `--exclude-id ID` | `--auto`: skip a YouTube id (repeatable), e.g. to avoid reusing a source |
| `--list-sources` | `--auto`: print ranked candidates and exit |
| `--work DIR` / `--log FILE` | Scratch dir (default `work/<out name>`) / run log (default `<out>.log`) |

## Categories

| Category | Label | Example hook | Song search (first query) | Pacing |
| --- | --- | --- | --- | --- |
| `bollywood` | Bollywood | Ye trailer dekh ke / rongte khade ho gaye | hindi / punjabi remix mashup | ~2.3s cuts, ~26s |
| `south` | South Indian cinema | South wale level / hi alag hai | telugu / tamil remix mashup | ~2.2s cuts, ~26s |
| `hollywood` | Hollywood | Hollywood ne phir / se kar dikhaya | trending english song | ~2.3s cuts, ~26s |
| `indian_celebrity` | Indian celebrities | Superstar ka swag / hi alag hai | trending bollywood song | ~2.3s cuts, ~26s |
| `cricket` | Cricket | Ye shot dekh ke / stadium pagal | cricket anthem official song | ~2.2s cuts, ~26s |
| `devotional` | Devotional / Bhakti | Jai Shri Ram / Rongte khade ho gaye | hanuman bhajan remix | ~2.7s cuts, ~27s |
| `hindi_love` | Hindi love story | Pyaar ho toh / aisa ho | romantic hindi song | ~2.6s cuts, ~26s |
| `tv_serial` | Hindi TV serial | Serial mein aaya / sabse bada twist | hindi serial title song | ~2.4s cuts, ~24s |
| `world_best` | World's best | Duniya ki sabse / badi movie? | trending english song | ~2.2s cuts, ~26s |

Each preset (in `categories.py`) defines several Hinglish hooks, search queries, optional `alt_queries` for non-YouTube hosts, title rules (must look like an official trailer / teaser / promo / highlights), preferred official channels, cut length and target length, `song_queries` / `song_prefer` for the song search, and a few known-good `seeds` (YouTube ids used when search returns nothing usable and YouTube is not blocked). Beats-per-cut is derived from the song BPM (estimated from onsets) so cuts stay on the beat (about 2.2–2.8s each). Videos come out 20–40s.

### Source rules for `--auto`

- Official material only: title must contain trailer / teaser / glimpse / promo / highlights; first pass requires a verified channel (`tv_serial` also requires an official TV channel). If nothing passes, a relaxed second pass runs.
- 16:9 (aspect ≥ 1.6), 60s to 10 min, downloaded at ≤1080p (H.264 preferred).
- Always skipped: reactions, reviews, fan-made, edits, lyric/audio uploads, full movies, Shorts, and any title with sexual or suggestive words (see `BLOCK_WORDS`). Movie categories also skip OTT series/episodes.
- Streaming-platform channels (Netflix, Prime Video, JioHotstar, ZEE5, SonyLIV, ...) are skipped by title and channel name.
- `cricket` uses cricket film trailers first: match highlights always carry a broadcaster score bug and get rejected by the logo detector.
- If search finds nothing usable, the category's `seeds` are tried.
- Downloads are cached in `work/sources/`, songs in `work/songs/` (gitignored).

## Songs (v5)

- `song_queries` are searched first on SoundCloud (`scsearch`), JioSaavn (public API), Audiomack, Dailymotion and archive.org audio — hosts that still download on datacenter IPs. YouTube is only searched if it is not already blocked.
- Kept: 1.5–10 min tracks, no live / slowed / reverb / 8D / karaoke / shorts / nonstop versions. NCS, Kevin MacLeod and generic library music are blacklisted. Remix / mashup / bhajan titles and non-YouTube hosts rank higher.
- The song starts at its loudest sustained section (chorus / drop) and fades in and out. Tempo comes from onset autocorrelation (or a metadata BPM if present).
- Title + artist go into `caption.txt` and the json. Up to 5 searched songs are tried. If none can be fetched, the original source audio is used. Captions never mention NCS.

## Dialogue mix (v3)

- Speech detection: Silero VAD (ONNX, via faster-whisper), then webrtcvad, then an energy + mid/side fallback.
- Up to 3 cuts (≤45% of the video) are picked around whole lines: the cut starts and ends in speech gaps, and lines with clear centre-channel voice score higher.
- Source audio plays only during those lines, normalised to -15 dBFS. Music sits at -17 dBFS and ducks to `--duck` (0.25) with short ramps while they talk, then a soft limiter.
- QC: every line must be ≥4 dB (average ≥6 dB) above the music under it, otherwise the ducking goes deeper and it re-renders. If a source has no usable dialogue, the next source is tried and the music-only render is kept only as a last resort.

## Logo / text detection (v3)

No pixels are changed; bad footage is avoided:

- **Corner logo detector**: pixels that are sharp edges in the same place across many shots (corner regions) are a static overlay. Logo-heavy seconds and 20s chunks are blacklisted, and the largest logo-free window is preferred. A source is only rejected when too little clean footage remains (never by blurring, cropping or painting over a logo).
- **OCR** (RapidOCR): seconds with credit / title / brand text on the picture are skipped (bottom-centre subtitles are allowed).
- The final video is checked again for a corner logo and plate text. A failure rejects that source.

## Self-healing fallback loop

`make_video.py` keeps trying until a video passes QC, and only fails after every option is used up:

1. **Search**: each query is retried 3×. If no result passes strict rules, a relaxed pass runs.
2. **Source**: next search result if a download fails, the clip is not 16:9, too short, or has too little clean footage. A failed download is retried at **720p**, then **480p**.
3. **Music**: next fetched remix/mashup if a song is missing, fails to download, is silent, or breaks the render. If none work, the original source audio is used. Library / NCS tracks are never tried.
4. **Dialogue**: no clean line in a source → next source (music-only render kept as last resort). Too quiet → deeper ducking and re-render.
5. **Logo**: too little logo-free footage in the source, or a logo in the output → next source (clean windows are tried first).
6. **QC**: up to 3 render rounds per source/track. Failed output seconds (and their neighbours) are blacklisted and new cuts are picked. A background that is too dark gets brighter each round. If the source has too few clean windows, fewer cuts are used (still ≥20s).
7. **yt-dlp blocks**: every search / download retries with other player clients (`web_safari`, `tv`, `mweb`, `ios`, Node runtime) with sleeps between requests.
8. **Unexpected errors** are logged with a traceback and the loop moves on.

Every step goes to the run log. If all fail, the script exits non-zero with a list of every attempt and why it failed.

Exit codes: `0` success, `1` all fallbacks exhausted, `2` source file not found, `3` no search results.

## Layout spec (1080x1920, 30 fps)

| Layer | Placement | Notes |
| --- | --- | --- |
| Canvas | `1080x1920` (9:16), 30 fps, `libx264`, `crf=18`, `yuv420p` | AAC 192k audio (song + ducked dialogue) |
| Blurred background | full frame | built from the active picture (letterbox bars ignored), `boxblur=30:5`, brightness auto (-0.08 / 0 / +0.08 by source brightness) |
| Sharp plate | `1080x608` for a 16:9 source, vertically centered with the banner | **no crop**: the full source frame (including any letterbox bars) is scaled to 1080 wide. Taller sources are fit by height |
| Hook banner | white `1080x240`, flush on top of the plate | Archivo Black, bold black text, max 2 lines, auto-shrinks to fit. Devanagari hooks use Noto Sans Devanagari if installed |
| On-screen captions | **none** | |
| Watermark | **none** | |

Pacing: skip the first ~6% (max 9s) and last ~14% (max 22s) of the source (trailers end with title art and release-date cards). Shots are spread out (≥7s apart where possible), and the strongest shot lands on the music drop.

QC: the source is scored at 2 fps on the active picture area. A second is rejected if either sample is dark, a solid red card, a static text card, or a flat colour card. The final video is checked at 2 fps for resolution, pix_fmt, 30 fps, 20–40s, audible audio (mean volume above -45 dB), a background that isn't too dark, and the same content rules on the plate, no corner logo, no plate text, and dialogue loudness vs music.

## GitHub Actions

`.github/workflows/render.yml` renders on GitHub-hosted runners. No secrets.

1. Repo → **Actions** → **Render Shorts** → **Run workflow**.
2. Inputs: `category` (one, a comma list, or `all`), `count` (videos per category, default 1), `hook` (optional).
3. Each category × count runs as its own matrix job (`--source-offset` / `--song-offset` = index, so batch videos differ).
4. Download the `short-<category>-<n>` artifact (mp4, caption.txt, json, log), kept 7 days.

The job installs ffmpeg, Noto fonts (Hindi), Deno and the newest yt-dlp. If YouTube blocks the runner, the code fails fast, switches to Dailymotion / archive.org (and song hosts like JioSaavn / SoundCloud), and a workflow `retry` job can re-dispatch failed categories on a fresh runner (up to 2 automatic reruns). A daily `schedule` is in the file, commented out. Successful mp4s are published as a public GitHub Release (`render-<run_id>`).

## Files

- `make_video.py` — renderer, QC and fallback loop
- `categories.py` — category presets, song queries, seeds, block words, streaming channels
- `sourcing.py` — yt-dlp search, filtering, ranking, download, song search, player-client fallbacks
- `audio_mix.py` — decode, VAD, BPM / chorus detection, ducked dialogue mix
- `logo.py` — corner logo detector, OCR text detection
- `.github/workflows/render.yml` — GitHub Actions render
- `scripts/download_music.py` — optional helper; `assets/music.json` ships with no tracks (NCS / library music is skipped)
- `assets/music.json` — empty local-track list (songs are fetched at render time)
- `fonts/ArchivoBlack-Regular.ttf` — [Archivo Black](https://fonts.google.com/specimen/Archivo+Black), SIL Open Font License

Do not commit `.mp3`, `.mp4`, `.m4a`, `out/` or `work/`.
