"""Category presets for make_video.py --category / --auto.

Each preset has:
  hooks      default top-banner hooks (Hinglish, Latin script; use \n for line 2)
  hook_match optional {title word: hook index} so the hook fits the fetched source
  queries    YouTube search queries for --auto, tried in order
  must_any   a result title must contain one of these words (official material)
  cut_s      target seconds per cut; beats-per-cut is derived from the track BPM
  target_s   target video length (20-40s); clip count is derived from it
  avoid      extra title words that disqualify a result (e.g. OTT series)
  prefer     title/channel words that rank a result higher
  verified_only / channels_only  optional stricter source rules
  music      track files from assets/music.json, first = preferred, rest = fallbacks
  tags       hashtags for the post caption
"""
from __future__ import annotations

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

OFFICIAL_WORDS = ["official", "trailer", "teaser", "promo", "highlights", "glimpse", "song"]

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
        "avoid_extra": SOUTH_WORDS,
        "prefer": ["t-series", "yash raj", "dharma", "excel", "jio studios", "maddock", "zee studios"],
        "cut_s": 2.3,
        "target_s": 26,
        "music": ["ncs_montagemindia.mp3", "ncs_tequilainmycup.mp3", "ncs_lavida.mp3"],
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
            "telugu movie official trailer hindi 2026",
            "tamil movie official trailer 2026",
            "pan india movie official teaser hindi",
            "kannada malayalam movie official trailer 2026",
        ],
        "must_any": ["trailer", "teaser", "glimpse"],
        "avoid": SERIES_WORDS,
        "prefer": SOUTH_WORDS + ["pan india", "hombale", "mythri", "sun pictures", "lyca"],
        "cut_s": 2.2,
        "target_s": 26,
        "music": ["ncs_fellshortofhell.mp3", "ncs_godless.mp3", "km_Impact_Prelude.mp3"],
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
        "music": ["ncs_godless.mp3", "km_Impact_Prelude.mp3", "ncs_adrenaline.mp3"],
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
        "music": ["ncs_tequilainmycup.mp3", "ncs_lavida.mp3", "ncs_montagemindia.mp3"],
        "tags": "#bollywoodcelebrity #superstar #srk #bollywood #fyp #viralreels",
    },
    "cricket": {
        "label": "Cricket",
        "hooks": [
            "Ye shot dekh ke\nstadium pagal",
            "Cricket ka asli\nmaza yahi hai",
            "Last over ka\nthriller!",
        ],
        "queries": [
            "ICC official match highlights india",
            "star sports cricket highlights india",
            "BCCI official highlights india",
            "cricket match highlights official 2026",
        ],
        "must_any": ["highlights", "highlight", "recap"],
        "verified_only": True,
        "prefer": ["icc", "bcci", "star sports", "jiohotstar", "sony sports", "ipl"],
        "cut_s": 2.2,
        "target_s": 26,
        "music": ["ncs_adrenaline.mp3", "ncs_lavida.mp3", "ncs_fellshortofhell.mp3"],
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
        "music": ["km_Intrepid.mp3", "ncs_flowersinmyhead.mp3", "km_Impact_Prelude.mp3"],
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
        "music": ["ncs_teamo.mp3", "ncs_fireflies.mp3", "km_Heartbreaking.mp3"],
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
        "music": ["km_Heartbreaking.mp3", "ncs_teamo.mp3", "ncs_favela.mp3"],
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
        "music": ["km_Impact_Prelude.mp3", "ncs_godless.mp3", "ncs_adrenaline.mp3"],
        "tags": "#worldbest #blockbuster #trailer #movies #cinema #fyp",
    },
}

# Generic last-resort tracks if every preset track fails.
FALLBACK_MUSIC = ["ncs_lavida.mp3", "ncs_adrenaline.mp3", "km_Impact_Prelude.mp3"]


def get(name: str) -> dict:
    key = name.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {"bhakti": "devotional", "bhagwan": "devotional", "love": "hindi_love",
               "serial": "tv_serial", "celebrity": "indian_celebrity", "tollywood": "south",
               "world": "world_best"}
    key = aliases.get(key, key)
    if key not in CATEGORIES:
        raise KeyError(f"unknown category '{name}'. Choose from: {', '.join(CATEGORIES)}")
    return {"name": key, **CATEGORIES[key]}
