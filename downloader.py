import glob
import threading
from pathlib import Path
from typing import Optional

import yt_dlp
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3NoHeaderError

from config import (
    logger,
    PREFERRED_QUALITY, SOCKET_TIMEOUT, RETRIES, DOWNLOAD_TIMEOUT,
)
from helpers import sanitize_filename


def tag_file(filepath: str, meta: dict) -> None:
    if not filepath or not Path(filepath).exists():
        return
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


class AudioDownloader:

    @staticmethod
    def _do_download(url: str, destination: str, filename: str = None,
                     progress_callback=None) -> Optional[str]:
        """Scarica tramite yt-dlp. Blocca il thread chiamante."""
        if filename:
            safe    = sanitize_filename(filename)
            outtmpl = str(Path(destination) / f"{safe}.%(ext)s")
        else:
            safe    = None
            outtmpl = str(Path(destination) / "%(title)s.%(ext)s")

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

        if safe:
            matches = glob.glob(str(Path(destination) / f"{safe}.*"))
            mp3 = [m for m in matches if m.endswith(".mp3")]
            return mp3[0] if mp3 else (matches[0] if matches else None)
        return None

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
