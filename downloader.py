import re
import threading
import unicodedata
import urllib.request
from pathlib import Path
from typing import List, Optional

import yt_dlp
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, APIC, ID3NoHeaderError
from rapidfuzz import fuzz

from config import (
    logger,
    PREFERRED_QUALITY, SOCKET_TIMEOUT, RETRIES, YOUTUBE_RESULTS,
    FILENAME_MAX_LENGTH, DOWNLOAD_TIMEOUT,
    SCORE_ARTIST_IN_TITLE, SCORE_TITLE_IN_TITLE, SCORE_ARTIST_IN_CHANNEL,
    SCORE_TOPIC_CHANNEL, SCORE_OFFICIAL_KEYWORD, SCORE_BAD_KEYWORD_PENALTY,
    SCORE_DURATION_EXACT, SCORE_DURATION_CLOSE, SCORE_DURATION_FAR_PENALTY,
    SCORE_FUZZY_MULTIPLIER,
)


def sanitize_filename(name: str, max_length: int = FILENAME_MAX_LENGTH) -> str:
    return re.sub(r'[<>:"/\\|?*\n\r\t]', '_', name).strip()[:max_length]


def tag_file(filepath: str, meta: dict) -> None:
    if not filepath or not Path(filepath).exists():
        return
    # Tag testuali
    try:
        try:
            tags = EasyID3(filepath)
        except ID3NoHeaderError:
            tags = EasyID3()
            tags.save(filepath)
            tags = EasyID3(filepath)
        mapping = {
            "title":       meta.get("title"),
            "artist":      meta.get("artist"),
            "albumartist": meta.get("albumartist"),
            "album":       meta.get("album"),
            "date":        meta.get("year"),
            "tracknumber": meta.get("tracknumber"),
            "genre":       meta.get("genre"),
        }
        for key, val in mapping.items():
            if val:
                tags[key] = [str(val)]
                logger.debug(f"[Tags] {key}={val!r} → {Path(filepath).name}")
        tags.save()
    except Exception as e:
        logger.error(f"[Tags] Errore su {filepath}: {e}")
    # Copertina
    cover_url = meta.get("cover_url", "")
    if cover_url:
        try:
            tags2 = ID3(filepath)
            tags2.delall("APIC")
            with urllib.request.urlopen(cover_url, timeout=SOCKET_TIMEOUT) as resp:
                img_data = resp.read()
            tags2.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=img_data))
            tags2.save()
            logger.debug(f"[Tags] Copertina incorporata: {Path(filepath).name}")
        except Exception as e:
            logger.error(f"[Tags] Errore artwork {filepath}: {e}")


class AudioDownloader:

    _BAD_KEYWORDS      = {"live", "karaoke", "instrumental", "remix", "cover",
                          "sped up", "slowed", "8d", "nightcore"}
    _OFFICIAL_KEYWORDS = {"official video", "official audio"}

    @staticmethod
    def _normalize(s: str) -> str:
        s = unicodedata.normalize("NFKD", s)
        s = s.encode("ascii", "ignore").decode()
        s = s.lower()
        s = re.sub(r"[^\w\s]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    @staticmethod
    def _score(entry: dict, art_n: str, tit_n: str, duration: int) -> int:
        """art_n e tit_n devono essere già normalizzati dal chiamante."""
        v   = AudioDownloader._normalize(entry.get("title", ""))
        ch  = AudioDownloader._normalize(entry.get("uploader", "") or entry.get("channel", ""))
        dur = entry.get("duration") or 0

        score = 0
        if art_n and art_n in v:  score += SCORE_ARTIST_IN_TITLE
        if tit_n and tit_n in v:  score += SCORE_TITLE_IN_TITLE
        if art_n and art_n in ch: score += SCORE_ARTIST_IN_CHANNEL
        if "topic" in ch:         score += SCORE_TOPIC_CHANNEL
        for k in AudioDownloader._OFFICIAL_KEYWORDS:
            if k in v: score += SCORE_OFFICIAL_KEYWORD
        for k in AudioDownloader._BAD_KEYWORDS:
            if k in v: score -= SCORE_BAD_KEYWORD_PENALTY
        if dur and duration:
            diff = abs(dur - duration)
            if   diff <  5: score += SCORE_DURATION_EXACT
            elif diff < 15: score += SCORE_DURATION_CLOSE
            elif diff > 60: score -= SCORE_DURATION_FAR_PENALTY
        if tit_n:
            score += int(fuzz.partial_ratio(tit_n, v) * SCORE_FUZZY_MULTIPLIER)
        return score

    @staticmethod
    def search_youtube(query: str, artist: str = "", title: str = "",
                       duration: int = 0) -> List[str]:
        logger.debug(f"[YouTube] Ricerca: '{query}' (artista='{artist}', titolo='{title}', durata={duration}s)")
        # Pre-normalizzazione: evita di ricalcolare per ogni risultato
        art_n = AudioDownloader._normalize(artist)
        tit_n = AudioDownloader._normalize(title)
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "extract_flat": True}) as ydl:
                results = ydl.extract_info(f"ytsearch{YOUTUBE_RESULTS}:{query}", download=False)
            entries = [e for e in (results.get("entries") or []) if e]
            if not entries:
                logger.warning(f"[YouTube] Nessun risultato per: '{query}'")
                return []
            scored = sorted(
                entries,
                key=lambda e: AudioDownloader._score(e, art_n, tit_n, duration),
                reverse=True,
            )
            for e in scored:
                s = AudioDownloader._score(e, art_n, tit_n, duration)
                logger.debug(
                    f"[YouTube] Score={s:3d}  canale='{e.get('uploader', '?')}'  "
                    f"titolo='{e.get('title', '?')[:60]}'"
                )
            urls = [e["url"] for e in scored]
            logger.debug(f"[YouTube] {len(urls)} risultati, primo: {urls[0] if urls else 'nessuno'}")
            return urls
        except Exception as e:
            logger.error(f"[YouTube] Errore ricerca '{query}': {e}")
        return []

    @staticmethod
    def _do_download(url: str, destination: str, filename: str = None,
                     progress_callback=None) -> Optional[str]:
        """Scarica tramite yt-dlp. Blocca il thread chiamante."""
        if filename:
            safe       = sanitize_filename(filename)
            outtmpl    = str(Path(destination) / f"{safe}.%(ext)s")
            final_path = str(Path(destination) / f"{safe}.mp3")
        else:
            outtmpl    = str(Path(destination) / "%(title)s.%(ext)s")
            final_path = None

        def _hook(d):
            if progress_callback and d["status"] == "downloading":
                total      = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                downloaded = d.get("downloaded_bytes", 0)
                if total:
                    progress_callback(min(downloaded / total * 100, 100))

        opts = {
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": PREFERRED_QUALITY,
            }],
            "noplaylist":                    True,
            "quiet":                         True,
            "progress_hooks":                [_hook],
            "socket_timeout":                SOCKET_TIMEOUT,
            "retries":                       RETRIES,
            "concurrent_fragment_downloads": 3,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        return final_path

    @staticmethod
    def download(url: str, destination: str, filename: str = None,
                 progress_callback=None) -> Optional[str]:
        """Scarica con timeout globale di DOWNLOAD_TIMEOUT secondi.
        Il thread interno è daemon: se scade, il download continua in background
        ma il chiamante riceve RuntimeError e può passare al prossimo URL."""
        result: dict = {"path": None, "error": None}

        def _inner():
            try:
                result["path"] = AudioDownloader._do_download(
                    url, destination, filename, progress_callback
                )
            except Exception as e:
                result["error"] = e

        t = threading.Thread(target=_inner, daemon=True)
        t.start()
        t.join(DOWNLOAD_TIMEOUT)

        if t.is_alive():
            raise RuntimeError(f"Download timeout dopo {DOWNLOAD_TIMEOUT}s")
        if result["error"] is not None:
            raise result["error"]
        return result["path"]
