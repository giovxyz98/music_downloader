import re
import unicodedata
from typing import List

import yt_dlp
from rapidfuzz import fuzz

from config import (
    logger,
    YOUTUBE_RESULTS,
    SCORE_ARTIST_IN_TITLE, SCORE_TITLE_IN_TITLE, SCORE_ARTIST_IN_CHANNEL,
    SCORE_TOPIC_CHANNEL, SCORE_OFFICIAL_KEYWORD, SCORE_BAD_KEYWORD_PENALTY,
    SCORE_DURATION_EXACT, SCORE_DURATION_CLOSE, SCORE_DURATION_FAR_PENALTY,
    SCORE_FUZZY_MULTIPLIER, SCORE_FIRST_RESULT_BONUS, SCORE_EXTRA_WORD_PENALTY,
    SCORE_MIN_DOWNLOAD,
)


class YouTubeSearcher:

    _BAD_KEYWORDS      = {"live", "karaoke", "instrumental", "remix", "cover",
                          "sped up", "slowed", "8d", "nightcore"}
    _OFFICIAL_KEYWORDS = {"official video", "official audio"}
    _NOISE_WORDS       = frozenset({
        "official", "ufficiale", "video", "visual", "audio",
        "hd", "4k", "lyrics", "testo", "seamusica", "ft", "feat",
        "featuring", "records", "record", "music", "tv", "videoclip",
    })

    @staticmethod
    def _normalize(s: str) -> str:
        s = unicodedata.normalize("NFKD", s)
        s = s.encode("ascii", "ignore").decode()
        s = s.lower()
        s = re.sub(r"[^\w\s]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    @staticmethod
    def _extra_words(v: str, tit_n: str, art_n: str) -> int:
        words = set(v.split())
        words -= YouTubeSearcher._NOISE_WORDS
        words = {w for w in words if not (w.isdigit() and len(w) == 4)}
        words -= set(tit_n.split())
        words -= set(art_n.split())
        words = {w for w in words if len(w) > 1}
        return len(words)

    @staticmethod
    def _score(entry: dict, art_n: str, tit_n: str, duration: int) -> int:
        """art_n e tit_n devono essere già normalizzati dal chiamante."""
        v   = YouTubeSearcher._normalize(entry.get("title", ""))
        ch  = YouTubeSearcher._normalize(entry.get("uploader", "") or entry.get("channel", ""))
        dur = entry.get("duration") or 0

        score = 0
        if art_n and art_n in v:  score += SCORE_ARTIST_IN_TITLE
        if tit_n and tit_n in v:  score += SCORE_TITLE_IN_TITLE
        if art_n and art_n in ch: score += SCORE_ARTIST_IN_CHANNEL
        if "topic" in ch:         score += SCORE_TOPIC_CHANNEL
        for k in YouTubeSearcher._OFFICIAL_KEYWORDS:
            if k in v: score += SCORE_OFFICIAL_KEYWORD
        for k in YouTubeSearcher._BAD_KEYWORDS:
            if k in v: score -= SCORE_BAD_KEYWORD_PENALTY
        if dur and duration:
            diff = abs(dur - duration)
            if   diff <  5: score += SCORE_DURATION_EXACT
            elif diff < 15: score += SCORE_DURATION_CLOSE
            elif diff > 60: score -= SCORE_DURATION_FAR_PENALTY
        if tit_n:
            score += int(fuzz.token_sort_ratio(tit_n, v) * SCORE_FUZZY_MULTIPLIER)
        score -= YouTubeSearcher._extra_words(v, tit_n, art_n) * SCORE_EXTRA_WORD_PENALTY
        return score

    @staticmethod
    def search(query: str, artist: str = "", title: str = "",
               duration: int = 0) -> List[str]:
        logger.debug(
            f"[YouTube] Ricerca: '{query}' "
            f"(artista='{artist}', titolo='{title}', durata={duration}s)"
        )
        art_n = YouTubeSearcher._normalize(artist)
        tit_n = YouTubeSearcher._normalize(title)
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "extract_flat": True}) as ydl:
                results = ydl.extract_info(f"ytsearch{YOUTUBE_RESULTS}:{query}", download=False)
            entries = [e for e in (results.get("entries") or []) if e]
            if not entries:
                logger.warning(f"[YouTube] Nessun risultato per: '{query}'")
                return []
            scored = sorted(
                [
                    (YouTubeSearcher._score(e, art_n, tit_n, duration)
                     + (SCORE_FIRST_RESULT_BONUS if i == 0 else 0), e)
                    for i, e in enumerate(entries)
                ],
                key=lambda x: x[0],
                reverse=True,
            )
            best_score = scored[0][0]
            if best_score < SCORE_MIN_DOWNLOAD:
                logger.warning(
                    f"[YouTube] Score troppo basso ({best_score}) per '{query}', download saltato"
                )
                return []
            for s, e in scored:
                views = e.get("view_count") or 0
                logger.debug(
                    f"[YouTube] Score={s:3d}  cercato='{title[:30]}'  "
                    f"views={views:>10,}  canale='{e.get('uploader', '?')[:25]}'  "
                    f"titolo='{e.get('title', '?')[:60]}'"
                )
            urls = [e["url"] for _, e in scored]
            logger.debug(f"[YouTube] {len(urls)} risultati, primo: {urls[0] if urls else 'nessuno'}")
            return urls
        except Exception as e:
            logger.error(f"[YouTube] Errore ricerca '{query}': {e}")
        return []
