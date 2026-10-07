import re
import unicodedata
from typing import List

import yt_dlp
from rapidfuzz import fuzz

from .config import (
    logger, YtDlpLogAdapter,
    YOUTUBE_RESULTS,
    SCORE_ARTIST_IN_TITLE, SCORE_TITLE_IN_TITLE, SCORE_ARTIST_IN_CHANNEL,
    SCORE_TOPIC_CHANNEL, SCORE_OFFICIAL_KEYWORD, SCORE_BAD_KEYWORD_PENALTY,
    SCORE_DURATION_EXACT, SCORE_DURATION_CLOSE, SCORE_DURATION_FAR_PENALTY,
    SCORE_FUZZY_MULTIPLIER, SCORE_FIRST_RESULT_BONUS, SCORE_EXTRA_WORD_PENALTY,
    SCORE_ORIGINAL_ARTIST_MISSING_PENALTY, SCORE_MIN_DOWNLOAD,
    SCORE_LIMIT_MARGIN, LIMIT_MAX_DURATION_DIFF,
    SCORE_VIEWS_GAP_RATIO, SCORE_VIEWS_GAP_PENALTY,
)


SUSPECT_DURATION_DIFF = 30   # oltre questa differenza (s) di durata il risultato scelto finisce segnalato nel report


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
    def _matches_artist(entry: dict, art_n: str) -> bool:
        if not art_n:
            return False
        v  = YouTubeSearcher._normalize(entry.get("title", ""))
        ch = YouTubeSearcher._normalize(entry.get("uploader", "") or entry.get("channel", ""))
        return art_n in v or art_n in ch

    @staticmethod
    def _max_same_artist_views(entries: list, art_n: str, tit_n: str = "") -> int:
        """Views massime tra i candidati che citano l'artista cercato nel titolo
        o nel canale E contengono il titolo cercato. Usato come riferimento per
        _score: un candidato con views molto più basse di questo massimo è
        probabilmente un canale omonimo/impostore (problemi_scoring.txt #5) che
        duplica la stessa canzone, non semplicemente meno popolare — per questo
        il confronto è ristretto a stesso artista e stessa canzone: un video
        virale di un ARTISTA DIVERSO, o di un'ALTRA canzone dello stesso artista,
        non deve abbassare il punteggio del candidato giusto ma poco visto."""
        matching = [e.get("view_count") or 0 for e in entries
                    if YouTubeSearcher._matches_artist(e, art_n)
                    and (not tit_n or tit_n in YouTubeSearcher._normalize(e.get("title", "")))]
        return max(matching) if matching else 0

    @staticmethod
    def _topic_is_artist(ch: str, art_n: str) -> bool:
        """Il bonus Topic vale solo se il nome prima di "- Topic" e' l'artista
        cercato (stesso nome o molto simile): il Topic di un altro artista che
        compare in un feat. non e' l'upload giusto (problemi_scoring.txt #1, #7).
        Senza artista cercato non c'e' nulla da confrontare: il bonus resta."""
        if not art_n:
            return True
        name = ch.replace("topic", "").strip()
        return art_n in name or fuzz.ratio(art_n, name) >= 80

    @staticmethod
    def _score(entry: dict, art_n: str, tit_n: str, duration: int,
               orig_art_n: str = "", tag: str = "", idx: int = 0,
               max_same_artist_views: int = 0) -> int:
        """art_n e tit_n devono essere già normalizzati dal chiamante.
        orig_art_n è l'artista originalmente cercato (album artist); se diverso
        da art_n e assente nel video, viene applicata una penalità.
        max_same_artist_views è il massimo di views tra i candidati che citano
        lo stesso artista in questa stessa ricerca (vedi _max_same_artist_views).
        tag/idx sono usati solo per etichettare i log di debug del breakdown."""
        v   = YouTubeSearcher._normalize(entry.get("title", ""))
        ch  = YouTubeSearcher._normalize(entry.get("uploader", "") or entry.get("channel", ""))
        dur = entry.get("duration") or 0

        p = f"[Score]{tag} cand#{idx + 1}"
        logger.debug(
            f"{p} grezzo: id={entry.get('id', '?')} titolo={entry.get('title', '?')!r} "
            f"canale={(entry.get('uploader') or entry.get('channel') or '?')!r} "
            f"channel_id={entry.get('channel_id', '?')!r} uploader_id={entry.get('uploader_id', '?')!r} "
            f"views={entry.get('view_count') or 0} durata_video={dur}s url={entry.get('url', '?')}"
        )
        logger.debug(f"{p} normalizzato: titolo_norm={v!r} canale_norm={ch!r}")

        score = 0
        if art_n and art_n in v:
            score += SCORE_ARTIST_IN_TITLE
            logger.debug(f"{p} artista {art_n!r} presente nel titolo → +{SCORE_ARTIST_IN_TITLE} (tot={score})")
        if tit_n and tit_n in v:
            score += SCORE_TITLE_IN_TITLE
            logger.debug(f"{p} titolo cercato {tit_n!r} presente nel titolo video → +{SCORE_TITLE_IN_TITLE} (tot={score})")
        if art_n and art_n in ch:
            score += SCORE_ARTIST_IN_CHANNEL
            logger.debug(f"{p} artista {art_n!r} presente nel canale → +{SCORE_ARTIST_IN_CHANNEL} (tot={score})")
        if "topic" in ch:
            if YouTubeSearcher._topic_is_artist(ch, art_n):
                score += SCORE_TOPIC_CHANNEL
                logger.debug(f"{p} canale 'Topic' dell'artista → +{SCORE_TOPIC_CHANNEL} (tot={score})")
            else:
                logger.debug(f"{p} canale 'Topic' ma non dell'artista {art_n!r} (canale_norm={ch!r}) → nessun bonus (tot={score})")
        for k in YouTubeSearcher._OFFICIAL_KEYWORDS:
            if k in v:
                score += SCORE_OFFICIAL_KEYWORD
                logger.debug(f"{p} keyword ufficiale {k!r} nel titolo → +{SCORE_OFFICIAL_KEYWORD} (tot={score})")
        for k in YouTubeSearcher._BAD_KEYWORDS:
            if k in tit_n:
                continue  # la parola e' nel titolo richiesto (es. "Mio caro - Live"): non e' un difetto
            if k in v:
                score -= SCORE_BAD_KEYWORD_PENALTY
                logger.debug(f"{p} bad keyword {k!r} nel titolo → -{SCORE_BAD_KEYWORD_PENALTY} (tot={score})")
        if dur and duration:
            diff = abs(dur - duration)
            if diff < 5:
                score += SCORE_DURATION_EXACT
                logger.debug(f"{p} durata video={dur}s atteso={duration}s diff={diff}s → +{SCORE_DURATION_EXACT} (tot={score})")
            elif diff < 15:
                score += SCORE_DURATION_CLOSE
                logger.debug(f"{p} durata video={dur}s atteso={duration}s diff={diff}s → +{SCORE_DURATION_CLOSE} (tot={score})")
            elif diff > 60:
                score -= SCORE_DURATION_FAR_PENALTY
                logger.debug(f"{p} durata video={dur}s atteso={duration}s diff={diff}s → -{SCORE_DURATION_FAR_PENALTY} (tot={score})")
            else:
                logger.debug(f"{p} durata video={dur}s atteso={duration}s diff={diff}s → nessun bonus/penalità (tot={score})")
        else:
            logger.debug(f"{p} durata non disponibile per il confronto (video={dur}s, attesa={duration}s)")
        if tit_n:
            ratio = fuzz.token_sort_ratio(tit_n, v)
            delta = int(ratio * SCORE_FUZZY_MULTIPLIER)
            score += delta
            logger.debug(f"{p} fuzzy token_sort_ratio({tit_n!r}, {v!r})={ratio} × {SCORE_FUZZY_MULTIPLIER} → +{delta} (tot={score})")
        extra_n = YouTubeSearcher._extra_words(v, tit_n, art_n)
        if extra_n:
            penalty = extra_n * SCORE_EXTRA_WORD_PENALTY
            score -= penalty
            logger.debug(f"{p} {extra_n} parole extra nel titolo video → -{penalty} (tot={score})")
        if orig_art_n and orig_art_n != art_n:
            if orig_art_n not in v and orig_art_n not in ch:
                score -= SCORE_ORIGINAL_ARTIST_MISSING_PENALTY
                logger.debug(f"{p} artista originale {orig_art_n!r} assente da titolo e canale → -{SCORE_ORIGINAL_ARTIST_MISSING_PENALTY} (tot={score})")
        views = entry.get("view_count") or 0
        if max_same_artist_views > 0 and views * SCORE_VIEWS_GAP_RATIO < max_same_artist_views:
            score -= SCORE_VIEWS_GAP_PENALTY
            logger.debug(
                f"{p} views={views} ≪ max_stesso_artista={max_same_artist_views} "
                f"(rapporto ≥{SCORE_VIEWS_GAP_RATIO}x, possibile canale omonimo/impostore) "
                f"→ -{SCORE_VIEWS_GAP_PENALTY} (tot={score})"
            )
        logger.debug(f"{p} punteggio base (prima del bonus primo risultato) = {score}")
        return score

    @staticmethod
    def _limit_case(entry: dict, score: int, art_n: str, tit_n: str, duration: int) -> str:
        """Caso limite: punteggio poco sotto la soglia ma il video e' sul canale
        dell'artista stesso. Ritorna "" se il candidato NON e' accettabile,
        altrimenti la nota da mettere nel report. Tutte le condizioni devono
        valere: meglio nessuna canzone che una sbagliata."""
        if not art_n or score < SCORE_MIN_DOWNLOAD - SCORE_LIMIT_MARGIN:
            return ""
        v  = YouTubeSearcher._normalize(entry.get("title", ""))
        ch = YouTubeSearcher._normalize(entry.get("uploader", "") or entry.get("channel", ""))
        if art_n not in ch or art_n not in v or not tit_n or tit_n not in v:
            return ""
        if any(k in v and k not in tit_n for k in YouTubeSearcher._BAD_KEYWORDS):
            return ""
        dur = entry.get("duration") or 0
        if dur and duration and abs(dur - duration) > LIMIT_MAX_DURATION_DIFF:
            return ""
        return (f"CASO LIMITE: punteggio {score} < {SCORE_MIN_DOWNLOAD}, accettato perche' sul canale "
                f"dell'artista ('{entry.get('uploader') or entry.get('channel')}'), "
                f"durata {dur or '?'}s (attesa {duration or '?'}s) - verifica che sia quello giusto")

    _SEP = "═" * 100

    @staticmethod
    def search(query: str, artist: str = "", title: str = "",
               duration: int = 0, original_artist: str = "", tag: str = "",
               diagnostics: dict = None) -> List[str]:
        """Se `diagnostics` e' un dict, in caso di nessun URL vi scrive
        ["reason"] con il motivo (e il miglior candidato scartato)."""
        def why(msg: str) -> None:
            if diagnostics is not None:
                diagnostics["reason"] = msg

        logger.debug(YouTubeSearcher._SEP)
        logger.debug(
            f"[YouTube]{tag} INIZIO RICERCA query='{query}' "
            f"(artista='{artist}', titolo='{title}', durata={duration}s"
            + (f", orig='{original_artist}'" if original_artist and original_artist != artist else "")
            + ")"
        )
        art_n      = YouTubeSearcher._normalize(artist)
        tit_n      = YouTubeSearcher._normalize(title)
        orig_art_n = YouTubeSearcher._normalize(original_artist)
        logger.debug(f"[YouTube]{tag} normalizzati (invariati per tutti i candidati): art_n={art_n!r} tit_n={tit_n!r} orig_art_n={orig_art_n!r}")
        try:
            ydl_opts = {"quiet": True, "extract_flat": True, "verbose": True,
                        "logger": YtDlpLogAdapter(tag)}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                results = ydl.extract_info(f"ytsearch{YOUTUBE_RESULTS}:{query}", download=False)
            raw_entries = results.get("entries") or []
            entries = [e for e in raw_entries if e]
            if not entries and title and art_n and title != query:
                # YouTube a volte da' 0 risultati se la query contiene il nome
                # dell'artista (es. "Rocco Hunt Che me chiamme a fa") ma li da'
                # con il solo titolo. Scatta SOLO con 0 risultati, e tiene solo
                # i video che citano l'artista nel titolo o nel canale: senza
                # l'artista non si scarica nulla.
                logger.warning(f"[YouTube]{tag} 0 risultati per '{query}', riprovo col solo titolo '{title}' "
                               f"(solo candidati con l'artista {art_n!r})")
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    results = ydl.extract_info(f"ytsearch{YOUTUBE_RESULTS}:{title}", download=False)
                found = [e for e in (results.get("entries") or []) if e]
                entries = [e for e in found if YouTubeSearcher._matches_artist(e, art_n)]
                logger.debug(f"[YouTube]{tag} fallback solo-titolo: {len(found)} risultati, "
                             f"{len(entries)} con l'artista")
                raw_entries = entries
            if len(entries) != len(raw_entries):
                logger.debug(f"[YouTube]{tag} {len(raw_entries) - len(entries)} entries vuote/None scartate da yt-dlp")
            logger.debug(f"[YouTube]{tag} yt-dlp ha restituito {len(entries)} risultati grezzi (richiesti {YOUTUBE_RESULTS})")
            if not entries:
                logger.debug(f"[YouTube]{tag} Nessun risultato per: '{query}'")
                why(f"YouTube non ha restituito nessun risultato per '{query}' (puo' essere temporaneo: riprova)")
                return []
            max_same_artist_views = YouTubeSearcher._max_same_artist_views(entries, art_n, tit_n)
            logger.debug(f"[YouTube]{tag} max views tra i candidati con l'artista {art_n!r} e il titolo {tit_n!r}: {max_same_artist_views}")
            scored = []
            for i, e in enumerate(entries):
                base = YouTubeSearcher._score(e, art_n, tit_n, duration, orig_art_n, tag=tag, idx=i,
                                              max_same_artist_views=max_same_artist_views)
                if i == 0:
                    logger.debug(f"[Score]{tag} cand#{i + 1} bonus primo risultato yt-dlp → +{SCORE_FIRST_RESULT_BONUS} (tot={base + SCORE_FIRST_RESULT_BONUS})")
                    base += SCORE_FIRST_RESULT_BONUS
                scored.append((base, e))
            scored.sort(key=lambda x: x[0], reverse=True)
            best_score = scored[0][0]
            if diagnostics is not None:
                diagnostics["ranking"] = [
                    {"score": s, "views": e.get("view_count") or 0,
                     "channel": e.get("uploader") or e.get("channel") or "?",
                     "title": e.get("title") or "?", "id": e.get("id") or "?",
                     "url": e.get("url") or ""}
                    for s, e in scored]
            if best_score < SCORE_MIN_DOWNLOAD:
                note = YouTubeSearcher._limit_case(scored[0][1], best_score, art_n, tit_n, duration)
                if note:
                    logger.debug(f"[YouTube]{tag} {note} → {scored[0][1].get('url')}")
                    if diagnostics is not None:
                        diagnostics["note"] = note
                    return [scored[0][1]["url"]]
                logger.debug(
                    f"[YouTube]{tag} Score troppo basso ({best_score}) per '{query}', download saltato"
                )
                top = scored[0][1]
                why(f"punteggio troppo basso ({best_score} < {SCORE_MIN_DOWNLOAD}); miglior candidato scartato: "
                    f"'{top.get('title', '?')}' [{top.get('uploader') or top.get('channel') or '?'}] "
                    f"durata {top.get('duration') or '?'}s (attesa {duration or '?'}s) {top.get('url', '')}")
                return []
            top = scored[0][1]
            top_dur = top.get("duration") or 0
            top_text = (YouTubeSearcher._normalize(top.get("title", "")) + " "
                        + YouTubeSearcher._normalize(top.get("uploader", "") or top.get("channel", "")))
            # Non si scarta (le versioni di Spotify e YouTube spesso differiscono, es. rifatte
            # o live): si segnala nel report cosi' si puo' controllare a mano.
            doubts = []
            if duration and top_dur and abs(top_dur - duration) > SUSPECT_DURATION_DIFF:
                doubts.append(f"durata video {top_dur}s, attesa {duration}s")
            if art_n and art_n not in top_text:
                doubts.append(f"l'artista '{artist}' non compare nel titolo ne' nel canale "
                              f"('{top.get('uploader') or top.get('channel') or '?'}')")
            if doubts:
                note = "ATTENZIONE: " + "; ".join(doubts) + " - verifica che sia la versione giusta"
                logger.debug(f"[YouTube]{tag} {note} → {top.get('url')}")
                if diagnostics is not None:
                    diagnostics["note"] = note
            for rank, (s, e) in enumerate(scored, start=1):
                views = e.get("view_count") or 0
                logger.debug(
                    f"[YouTube]{tag} CLASSIFICA #{rank}  Score={s:3d}  cercato='{title[:30]}'  "
                    f"views={views:>10,}  canale='{e.get('uploader', '?')[:25]}'  "
                    f"channel_id={e.get('channel_id', '?')}  id={e.get('id', '?')}  "
                    f"titolo='{e.get('title', '?')[:60]}'"
                )
            urls = [e["url"] for _, e in scored]
            logger.debug(f"[YouTube]{tag} FINE RICERCA: {len(urls)} URL ordinati, scelto: {urls[0] if urls else 'nessuno'}")
            return urls
        except Exception as e:
            logger.error(f"[YouTube]{tag} Errore ricerca '{query}': {e}")
            why(f"errore durante la ricerca YouTube: {e}")
        return []
