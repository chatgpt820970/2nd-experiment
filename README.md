# 2nd-experiment

Standalone vertical Shorts renderer. Takes a 16:9 source clip, cuts it on the beat, and lays it onto a 9:16 canvas with a blurred ambient background and a white hook banner.

This is a clean cut of the Fool Night viral demo: **no on-screen captions and no watermark**. The hook stays on the top banner only.

## Setup

Needs `ffmpeg`, `ffprobe`, and Python 3.10+ with:

```bash
pip install -r requirements.txt
```

Download the official NCS track (gitignored, not committed):

```bash
python3 scripts/download_music.py
```

That fetches [Cryjaxx, MVRPHiN & Lucy Malfroy - LA VIDA!](https://ncs.io/LAVIDA) from NCS into `assets/music/ncs_lavida.mp3`.

## How to run

```bash
python3 make_video.py \
  --source /path/to/foolnight.mp4 \
  --hook "Nobody was ready\nfor Fool Night" \
  --music assets/music/ncs_lavida.mp3 \
  --out out/foolnight_clean.mp4
```

If `--music` is omitted, the script downloads the default NCS track automatically. If `--hook` is omitted, it uses the Fool Night default above.

Optional flags: `--bpm 129`, `--clips 11`.

A post-text file with the caption and **required music credit** is written next to the output as `<out>.caption.txt`. Nothing from that file is burned into the video.

## Layout spec (1080x1920, 30 fps)

| Layer | Placement | Notes |
| --- | --- | --- |
| Canvas | `1080x1920` (9:16), 30 fps, `libx264`, `crf=18`, `pix_fmt=yuv420p` | AAC 192k audio |
| Blurred background | full frame | `scale=1080:1920`, `boxblur=30:5`, `eq=brightness=-0.08` — visible fill, not near-black |
| Sharp plate | `1080x608` for a 16:9 source, vertically centered with the banner | **no crop** — the full source frame is scaled to 1080 wide, aspect kept |
| Hook banner | white `1080x240`, flush on top of the plate | banner + frame are one block, centered on the canvas; bold black text, max 2 lines, Archivo Black |
| On-screen captions | **removed** | no `.ass` subtitles, no word-by-word burn-in |
| Watermark | **removed** | no `@handle` at the bottom |

Pacing: skip the first `9.0s` and last `16.0s` of the source. Cut every 5 beats (~2.33s at 129 BPM, always under 2.8s). OpenCV-style QC rejects dark bumpers, solid-red cards, and static text cards. If a frame fails, that source second is blacklisted and the video is re-rendered once.

## Music credit rule

NCS tracks are free for YouTube / Twitch UGC, including monetised videos, **only if the credit is in the post description**. Do not skip it. For the default track, paste:

```
Song: Cryjaxx, MVRPHiN & Lucy Malfroy - LA VIDA!
Music provided by NoCopyrightSounds
Free Download/Stream: http://ncs.io/LAVIDA
Watch: http://ncs.lnk.to/LAVIDAAT/youtube
```

See `assets/music.json` for the official source page, download URL, and license link. Do not commit `.mp3` or `.mp4` files.

## Font

`fonts/ArchivoBlack-Regular.ttf` is [Archivo Black](https://fonts.google.com/specimen/Archivo+Black), licensed under the SIL Open Font License.
