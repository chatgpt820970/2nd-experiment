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
  song_queries  yt-dlp searches for a popular / trending song (remix, mashup, bhajan remix...)
  song_prefer   channel/title words that rank a song higher (music labels)
  seeds      known official YouTube ids tried after the search results
  music      LOCAL fallback track files from assets/music.json if song download fails
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
    "live", "jukebox", "nonstop", "non stop", "full album", "hour", "hours", "reaction", "sexy",
    "hot", "nude", "bass boosted", "whatsapp",
]

MUSIC_LABELS = [
    "t-series", "sony music", "zee music", "saregama", "tips", "speed records", "desi music factory",
    "yrf", "times music", "aditya music", "lahari", "think music", "sun tv", "white hill",
    "geet mp3", "vyrl", "warner", "universal music", "atlantic", "interscope", "vevo",
]

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
        # "(Hindi)" / "in Hindi" in a title = dubbed South/Hollywood film, not Bollywood
        "avoid_extra": SOUTH_WORDS + ["(hindi)", "in hindi", "hindi trailer", "hindi dubbed", "ramayana"],
        "prefer": ["t-series", "yash raj", "dharma", "excel", "jio studios", "maddock", "zee studios"],
        "cut_s": 2.3,
        "target_s": 26,
        "song_queries": ["bollywood remix mashup 2025", "bollywood party song remix official", "latest bollywood dance song official video"],
        "song_prefer": MUSIC_LABELS,
        # known official uploads tried after search results (search results change daily)
        "seeds": ["fneuVQ7uO_w", "vCTt_PnWHPg", "hpwnlr-ZHB0", "nCa4BGy3MJ8"],
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
        "song_queries": ["south indian mass song hindi official", "telugu mass song official video", "anirudh mass song official", "tamil kuthu song official video"],
        "song_prefer": MUSIC_LABELS,
        # known official uploads tried after search results (search results change daily)
        "seeds": ["ho4ACWs1hwc", "EaODp3C7wkU"],
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
        "song_queries": ["trending english song 2025 official video", "epic english song official video", "imagine dragons official music video"],
        "song_prefer": MUSIC_LABELS,
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
        "song_queries": ["trending bollywood song 2025 official", "bollywood superhit song remix", "punjabi trending song remix official"],
        "song_prefer": MUSIC_LABELS,
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
        "song_queries": ["cricket anthem official song", "team india cricket song official", "world cup anthem official song", "punjabi hype song official"],
        "song_prefer": MUSIC_LABELS,
        # known official uploads tried after search results (search results change daily)
        "seeds": ["6L6XqWoS8tw", "BT0zd0kmTxM", "tsxemFX0a7k"],
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
        "song_queries": ["hanuman bhajan remix", "jai shri ram song dj remix", "mahadev song remix", "krishna bhajan remix"],
        "song_prefer": MUSIC_LABELS + ["bhakti", "hansraj", "lakhbir", "hanuman", "ram", "mahadev", "krishna"],
        # known official uploads tried after search results (search results change daily)
        "seeds": ["1zip1rNaNYs", "T0Uduwg2W2w"],
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
        "song_queries": ["romantic hindi song 2025 official video", "arijit singh romantic song official", "bollywood love mashup 2025"],
        "song_prefer": MUSIC_LABELS,
        # known official uploads tried after search results (search results change daily)
        "seeds": ["rRQ8oKCoYrQ", "HdD6rU98yvg"],
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
        "song_queries": ["hindi serial title song official", "emotional hindi song official video", "sad hindi song official video"],
        "song_prefer": MUSIC_LABELS,
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
        "song_queries": ["trending english song 2025 official video", "world famous song official video", "epic motivational song official"],
        "song_prefer": MUSIC_LABELS,
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
