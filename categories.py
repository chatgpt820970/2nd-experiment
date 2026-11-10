"""Category presets for make_video.py --category / --auto.

Each preset has:
  hooks      default top-banner hooks (Hinglish, Latin script; use \n for line 2)
  hook_match optional {title word: hook index} so the hook fits the fetched source
  queries    YouTube search queries for --auto, tried in order
  alt_queries extra Dailymotion / archive.org queries (used when YouTube is blocked)
  alt_limit  how many non-YouTube fallback clips to keep
  must_any   a result title must contain one of these words (official material)
  cut_s      target seconds per cut; beats-per-cut is derived from the track BPM
  target_s   target video length (20-40s); clip count is derived from it
  avoid      extra title words that disqualify a result (e.g. OTT series)
  prefer     title/channel words that rank a result higher
  verified_only / channels_only  optional stricter source rules
  song_queries  searches for a trending remix / mashup / bhajan remix
  song_prefer   channel/title words that rank a song higher (music labels)
  seeds      known official YouTube ids tried after the search results
  tags       hashtags for the post caption
"""
from __future__ import annotations

import re

# Words that disqualify a search result for every category: non-official
# material, static lyric/audio uploads, and anything sexual/suggestive.
BLOCK_WORDS = [
    "reaction", "review", "explained", "fan made", "fanmade", "fan-made", "concept",
    "spoof", "parody", "edit", "status", "#shorts", "shorts", "full movie", "jukebox",
    "lyric", "lyrical", "audio", "8d", "slowed", "reverb", "remix", "ai generated",
    "hot", "sexy", "bold", "kiss", "bikini", "intimate", "uncut", "uncensored", "18+",
    "adult", "nude", "naked", "item song", "bed scene", "romance scene", "web series",
    "ullu", "cleavage", "seductive", "steamy",
]

# Movie categories also skip OTT series/episodes so the clip is a film.
SERIES_WORDS = ["series", "season", "episode", "streaming", "originals", "web show"]
SOUTH_WORDS = ["telugu", "tamil", "kannada", "malayalam", "sony music south", "tollywood", "kollywood"]

# Streaming platforms put their logo on every upload -> never use them as a source.
STREAMING_CHANNELS = [
    "netflix", "prime video", "primevideo", "amazon prime", "amazon mx", "jiohotstar", "hotstar",
    "disney+", "disney plus", "zee5", "zee 5", "sony liv", "sonyliv", "aha", "aha video", "sun nxt",
    "sunnxt", "mx player", "jiocinema", "jio cinema", "altbalaji", "alt balaji", "voot", "hoichoi",
    "apple tv", "hbo max", "peacock", "hulu", "paramount+", "lionsgate play", "eros now", "watchonjiohotstar",
]

# Song search: skip edits that sound bad or are not a single track.
MUSIC_BLOCK_WORDS = [
    "slowed", "reverb", "8d", "lofi", "lo-fi", "karaoke", "ringtone", "status", "shorts", "#shorts",
    "live", "jukebox", "nonstop", "non stop", "non-stop", "full album", "hour", "hours", "reaction", "sexy",
    "hot", "nude", "bass boosted", "whatsapp",
]

# Never use these as the music bed (NCS, Kevin MacLeod, generic library music).
LIBRARY_MUSIC_WORDS = [
    "ncs", "nocopyrightsounds", "no copyright sounds", "no copyrights sounds",
    "kevin macleod", "incompetech", "copyright free", "royalty free",
    "audio library", "youtube audio library", "epidemic sound", "mixkit",
    "pixabay", "bensound", "ncs release",
]

MUSIC_LABELS = [
    "t-series", "sony music", "zee music", "saregama", "tips", "speed records", "desi music factory",
    "yrf", "times music", "aditya music", "lahari", "think music", "sun tv", "white hill",
    "geet mp3", "vyrl", "warner", "universal music", "atlantic", "interscope", "vevo",
]

OFFICIAL_WORDS = ["official", "trailer", "teaser", "promo", "highlights", "glimpse", "song"]

_LIBRARY_FILE_RE = re.compile(r"(^|[_\s./-])ncs([_\s./-]|$)|macleod|incompetech|nocopyrightsounds", re.I)
_LIBRARY_WORD_RE = re.compile(
    r"(?<![a-z0-9])(" + "|".join(re.escape(w) for w in LIBRARY_MUSIC_WORDS) + r")(?![a-z0-9])",
    re.I,
)


def is_library_music(text: str) -> bool:
    """True if a title, artist, filename or credit is NCS / Kevin MacLeod / library music."""
    if not text:
        return False
    return bool(_LIBRARY_FILE_RE.search(text) or _LIBRARY_WORD_RE.search(text))


CATEGORIES: dict[str, dict] = {
    "bollywood": {
        "label": "Bollywood",
        "hooks": [
            "Ye trailer dekh ke\nrongte khade ho gaye",
            "Bollywood is back\nand how!",
            "Theatre mein seetiyan\npakki hain",
        ],
        "queries": [
            "bollywood official trailer 2026",
            "hindi movie official teaser 2026",
            "bollywood action movie official trailer",
        ],
        "must_any": ["trailer", "teaser"],
        "avoid": SERIES_WORDS,
        # "(Hindi)" / "in Hindi" in a title = dubbed South/Hollywood film, not Bollywood
        "avoid_extra": SOUTH_WORDS + ["(hindi)", "in hindi", "hindi trailer", "hindi dubbed", "ramayana"],
        "prefer": ["t-series", "yash raj", "dharma", "excel", "jio studios", "maddock", "zee studios"],
        "cut_s": 2.3,
        "target_s": 26,
        "song_queries": [
            "hindi remix mashup 2025",
            "punjabi remix mashup 2025",
            "bollywood party remix mashup",
            "latest punjabi dance remix",
        ],
        "song_prefer": MUSIC_LABELS + ["hindi", "punjabi", "bollywood", "desi"],
        "seeds": ["fneuVQ7uO_w", "vCTt_PnWHPg", "hpwnlr-ZHB0", "nCa4BGy3MJ8"],
        "tags": "#bollywood #trailer #hindimovie #newmovie #fyp #viralreels",
    },
    "south": {
        "label": "South Indian cinema",
        "hooks": [
            "South wale level\nhi alag hai",
            "Is mass entry ke\naage sab fail",
            "Pan India\nblockbuster loading",
        ],
        "queries": [
            "telugu movie official trailer 2026",
            "tamil movie official trailer 2026",
            "kannada movie official trailer 2026",
            "malayalam movie official trailer 2026",
            "telugu official teaser 2026",
            "tamil official teaser 2026",
            "pan india movie official trailer",
            "tollywood official trailer",
            "kollywood official trailer",
            "telugu movie official trailer hindi 2026",
        ],
        "alt_queries": [
            "telugu official trailer",
            "tamil official trailer",
            "kannada official trailer",
            "malayalam official trailer",
            "telugu movie official teaser",
            "tamil movie official teaser",
            "kannada movie official teaser",
            "malayalam movie official teaser",
            "tollywood official trailer",
            "kollywood official trailer",
            "south indian official trailer",
            "telugu official glimpse",
            "tamil official glimpse",
            "pan india official trailer",
        ],
        "alt_limit": 16,
        "must_any": ["trailer", "teaser", "glimpse"],
        "avoid": SERIES_WORDS,
        "prefer": SOUTH_WORDS + ["pan india", "hombale", "mythri", "sun pictures", "lyca"],
        "cut_s": 2.2,
        "target_s": 26,
        "song_queries": [
            "telugu remix mashup 2025",
            "tamil kuthu remix mashup",
            "telugu mass remix 2025",
            "tamil remix mashup 2025",
        ],
        "song_prefer": MUSIC_LABELS + ["telugu", "tamil", "kuthu", "kollywood", "tollywood"],
        "seeds": ["ho4ACWs1hwc", "EaODp3C7wkU"],
        "tags": "#southmovie #pushpa #tollywood #kollywood #massentry #fyp",
    },
    "hollywood": {
        "label": "Hollywood",
        "hooks": [
            "Hollywood ne phir\nse kar dikhaya",
            "Ye VFX dekh ke\ndimaag hil gaya",
            "Biggest movie of\nthe year?",
        ],
        "queries": [
            "official trailer 2026 hollywood",
            "official trailer 2026 IMAX",
            "new movie official teaser trailer 2026",
        ],
        "must_any": ["trailer", "teaser"],
        "avoid": SERIES_WORDS,
        "cut_s": 2.3,
        "target_s": 26,
        "song_queries": [
            "english song remix mashup 2025",
            "trending english remix official",
            "epic english song remix mashup",
        ],
        "song_prefer": MUSIC_LABELS,
        "tags": "#hollywood #trailer #newmovie #movies #fyp #viralreels",
    },
    "indian_celebrity": {
        "label": "Indian celebrities",
        "hooks": [
            "Superstar ka swag\nhi alag hai",
            "Is star ki entry\npe sab fida",
            "Real superstar\nkaun? Batao",
        ],
        "queries": [
            "shah rukh khan movie official trailer",
            "salman khan movie official trailer",
            "deepika padukone movie official trailer",
            "alia bhatt movie official trailer",
            "prabhas movie official trailer hindi",
        ],
        "must_any": ["trailer", "teaser"],
        "avoid": SERIES_WORDS,
        "prefer": ["shah rukh", "salman", "deepika", "alia", "prabhas", "ranbir", "amitabh"],
        "cut_s": 2.3,
        "target_s": 26,
        "song_queries": [
            "hindi remix mashup 2025",
            "punjabi remix mashup 2025",
            "bollywood superhit remix mashup",
        ],
        "song_prefer": MUSIC_LABELS,
        "tags": "#bollywoodcelebrity #superstar #srk #bollywood #fyp #viralreels",
    },
    "cricket": {
        "label": "Cricket",
        "hooks": [
            "Ye shot dekh ke\nstadium pagal",
            "Cricket ka asli\nmaza yahi hai",
            "Last over ka\nthriller!",
        ],
        # Broadcast highlights always carry a score bug / channel logo (rejected by the
        # logo check), so cricket films come first; highlights stay as a fallback.
        "queries": [
            "83 movie official trailer",
            "ms dhoni the untold story official trailer",
            "cricket movie official trailer hindi",
            "ICC official match highlights india",
            "star sports cricket highlights india",
        ],
        "must_any": ["highlights", "highlight", "recap", "trailer"],
        "verified_only": True,
        "prefer": ["icc", "bcci", "star sports", "jiohotstar", "sony sports", "ipl"],
        "cut_s": 2.2,
        "target_s": 26,
        "song_queries": [
            "punjabi remix mashup 2025",
            "hindi hype remix mashup",
            "punjabi dance remix 2025",
            "bollywood party remix mashup",
        ],
        "song_prefer": MUSIC_LABELS + ["punjabi", "hindi", "bollywood", "desi", "india"],
        "seeds": ["6L6XqWoS8tw", "BT0zd0kmTxM", "tsxemFX0a7k"],
        "tags": "#cricket #teamindia #highlights #ipl #icc #fyp",
    },
    "devotional": {
        "label": "Devotional / Bhakti",
        "hooks": [
            "Jai Shri Ram\nRongte khade ho gaye",
            "Har Har Mahadev\nBhakti ka josh",
            "Bhagwan ki leela\naparampaar",
            "Jai Shri Krishna\nRadhe Radhe",
            "Jai Bajrangbali\nJai Hanuman",
        ],
        # source title word -> hook index, so the hook names the right god
        "hook_match": {"ramayana": 0, "ram": 0, "rama": 0, "shiva": 1, "mahadev": 1,
                       "shiv": 1, "krishna": 3, "hanuman": 4, "bajrangbali": 4},
        "queries": [
            "ramayana official teaser",
            "hanuman movie official trailer hindi",
            "mahadev movie official trailer",
            "krishna movie official trailer hindi",
            "devotional movie official trailer hindi",
        ],
        "must_any": ["trailer", "teaser", "glimpse"],
        "avoid": SERIES_WORDS,
        "prefer": ["ramayana", "hanuman", "shiva", "mahadev", "krishna", "ram"],
        "cut_s": 2.7,
        "target_s": 27,
        "song_queries": [
            "hanuman bhajan remix",
            "jai shri ram dj remix",
            "mahadev bhajan remix",
            "krishna bhajan remix",
        ],
        "song_prefer": MUSIC_LABELS + ["bhakti", "hansraj", "lakhbir", "hanuman", "ram", "mahadev", "krishna"],
        "seeds": ["1zip1rNaNYs", "T0Uduwg2W2w"],
        "tags": "#jaishriram #harharmahadev #bhakti #devotional #sanatan #fyp",
    },
    "hindi_love": {
        "label": "Hindi love story",
        "hooks": [
            "Pyaar ho toh\naisa ho",
            "Ye love story\ndil chhoo gayi",
            "Sacha pyaar\nabhi bhi zinda hai",
        ],
        "queries": [
            "hindi love story movie official trailer",
            "romantic hindi movie official trailer 2026",
            "love story bollywood official teaser",
        ],
        "must_any": ["trailer", "teaser"],
        "avoid": SERIES_WORDS,
        "avoid_extra": SOUTH_WORDS,
        "cut_s": 2.6,
        "target_s": 26,
        "song_queries": [
            "romantic hindi remix mashup 2025",
            "bollywood love mashup 2025",
            "arijit singh romantic remix mashup",
        ],
        "song_prefer": MUSIC_LABELS,
        "seeds": ["rRQ8oKCoYrQ", "HdD6rU98yvg"],
        "tags": "#lovestory #pyaar #romantic #bollywood #couplegoals #fyp",
    },
    "tv_serial": {
        "label": "Hindi TV serial",
        "hooks": [
            "Serial mein aaya\nsabse bada twist",
            "Ye drama dekh ke\nmummy bhi shocked",
            "Aaj ka episode\nmiss mat karna",
        ],
        "verified_only": True,
        "channels_only": ["StarPlus", "Star Plus", "Sony Entertainment Television", "Sony SAB",
                          "Colors TV", "Zee TV", "Star Bharat", "Dangal", "JioHotstar"],
        "prefer": ["starplus", "star plus", "sony", "colors", "zee tv", "sab"],
        "queries": [
            "starplus serial official promo",
            "star plus serial official promo",
            "sony tv serial official promo",
            "colors tv serial official promo",
            "zee tv serial official promo",
        ],
        "must_any": ["promo", "trailer", "teaser"],
        "cut_s": 2.4,
        "target_s": 24,
        "song_queries": [
            "emotional hindi remix mashup",
            "sad hindi song remix mashup",
            "romantic hindi remix mashup",
        ],
        "song_prefer": MUSIC_LABELS,
        "tags": "#tvserial #starplus #serialtwist #drama #hinditv #fyp",
    },
    "world_best": {
        "label": "World's best",
        "hooks": [
            "Duniya ki sabse\nbadi movie?",
            "World level ka\ncinema yahi hai",
            "Ise dekhe bina\nmat jaana",
        ],
        "queries": [
            "most awaited movie 2026 official trailer",
            "blockbuster official trailer 2026 IMAX",
            "world biggest movie official final trailer",
        ],
        "must_any": ["trailer", "teaser"],
        "avoid": SERIES_WORDS,
        "prefer": ["universal", "paramount", "warner", "sony pictures", "marvel", "disney",
                   "netflix", "imax", "yrf", "t-series"],
        "cut_s": 2.2,
        "target_s": 26,
        "song_queries": [
            "english song remix mashup 2025",
            "world famous song remix mashup",
            "epic motivational remix mashup",
        ],
        "song_prefer": MUSIC_LABELS,
        "tags": "#worldbest #blockbuster #trailer #movies #cinema #fyp",
    },
}

# No library / NCS / Kevin MacLeod fallback. If song fetch fails, use original source audio.
FALLBACK_MUSIC: list[str] = []


def get(name: str) -> dict:
    key = name.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {"bhakti": "devotional", "bhagwan": "devotional", "love": "hindi_love",
               "serial": "tv_serial", "celebrity": "indian_celebrity", "tollywood": "south",
               "world": "world_best"}
    key = aliases.get(key, key)
    if key not in CATEGORIES:
        raise KeyError(f"unknown category '{name}'. Choose from: {', '.join(CATEGORIES)}")
    return {"name": key, **CATEGORIES[key]}
