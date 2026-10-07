import glob
import threading
from pathlib import Path
from typing import Optional

import yt_dlp
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3NoHeaderError
from mutagen.mp3 import MP3

from .config import (
    logger, YtDlpLogAdapter, FFMPEG_DIR,
    PREFERRED_QUALITY, SOCKET_TIMEOUT, RETRIES, DOWNLOAD_TIMEOUT,
)
from .text_utils import sanitize_filename


def check_mp3(filepath: str) -> str:
    """Controllo veloce (solo header, nessuna decodifica). Ritorna '' se il file
    sembra valido, altrimenti il motivo. Non vede buchi o glitch nel mezzo."""
    try:
        size = Path(filepath).stat().st_size
        info = MP3(filepath).info
    except Exception as e:
        return f"illeggibile: {e}"
    if info.length < 10:
        return f"durata troppo breve ({info.length:.0f}s)"
    expected = info.bitrate / 8 * info.length
    if size < 0.9 * expected:
        return f"troncato ({size} byte su ~{expected:.0f})"
    return ""


def mp3_bitrate_kbps(filepath: str) -> int:
    try:
        return round(MP3(filepath).info.bitrate / 1000)
    except Exception:
        return 0


def tag_file(filepath: str, meta: dict, tag: str = "") -> None:
    if not filepath or not Path(filepath).exists():
        logger.warning(f"[Tags]{tag} File assente o vuoto, tagging saltato: {filepath!r}")
        return
    try:
        try:
            tags = EasyID3(filepath)
            logger.debug(f"[Tags]{tag} Header ID3 esistente su {Path(filepath).name}")
        except ID3NoHeaderError:
            logger.debug(f"[Tags]{tag} Nessun header ID3, ne creo uno nuovo su {Path(filepath).name}")
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
                logger.debug(f"[Tags]{tag} {key}={val!r} → {Path(filepath).name}")
            else:
                logger.debug(f"[Tags]{tag} {key} assente in meta, non scritto → {Path(filepath).name}")
        tags.save()
        logger.debug(f"[Tags]{tag} Salvataggio ID3 completato su {Path(filepath).name}")
    except Exception as e:
        logger.error(f"[Tags]{tag} Errore su {filepath}: {e}")


class AudioDownloader:

    @staticmethod
    def _do_download(url: str, destination: str, filename: str = None,
                     progress_callback=None, tag: str = "") -> Optional[str]:
        """Scarica tramite yt-dlp. Blocca il thread chiamante."""
        if filename:
            safe    = sanitize_filename(filename)
            outtmpl = str(Path(destination) / f"{safe}.%(ext)s")
        else:
            safe    = None
            outtmpl = str(Path(destination) / "%(title)s.%(ext)s")

        def _hook(d):
            # Il progresso vero e proprio (%, velocità, ETA) lo logga già
            # YtDlpLogAdapter tramite il logger interno di yt-dlp: qui serve
            # solo per inoltrare la percentuale alla UI, non ridondarlo nel log.
            status = d.get("status")
            if status == "downloading" and progress_callback:
                total      = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                downloaded = d.get("downloaded_bytes", 0)
                if total:
                    progress_callback(min(downloaded / total * 100, 100))
            elif status == "finished":
                logger.debug(f"[yt-dlp]{tag} download raw completato, filename={d.get('filename', '?')!r}, avvio post-processing FFmpeg")

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
            "verbose":                       True,
            "logger":                        YtDlpLogAdapter(tag),
            "progress_hooks":                [_hook],
            "socket_timeout":                SOCKET_TIMEOUT,
            "retries":                       RETRIES,
            "concurrent_fragment_downloads": 3,
        }
        if FFMPEG_DIR:
            opts["ffmpeg_location"] = FFMPEG_DIR
        logger.debug(f"[yt-dlp]{tag} avvio download url={url!r} outtmpl={outtmpl!r} opts={ {k: v for k, v in opts.items() if k != 'progress_hooks'} }")
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

        if safe:
            matches = glob.glob(str(Path(destination) / f"{safe}.*"))
            logger.debug(f"[yt-dlp]{tag} glob '{safe}.*' → {matches}")
            mp3 = [m for m in matches if m.endswith(".mp3")]
            result = mp3[0] if mp3 else (matches[0] if matches else None)
            logger.debug(f"[yt-dlp]{tag} file risultante: {result!r}")
            return result
        return None

    @staticmethod
    def download(url: str, destination: str, filename: str = None,
                 progress_callback=None, tag: str = "") -> Optional[str]:
        """Scarica con timeout globale di DOWNLOAD_TIMEOUT secondi.
        Il thread interno è daemon: se scade, il download continua in background
        ma il chiamante riceve RuntimeError e può passare al prossimo URL."""
        result: dict = {"path": None, "error": None}

        def _inner():
            try:
                result["path"] = AudioDownloader._do_download(
                    url, destination, filename, progress_callback, tag=tag
                )
            except Exception as e:
                result["error"] = e

        t = threading.Thread(target=_inner, daemon=True)
        t.start()
        t.join(DOWNLOAD_TIMEOUT)

        if t.is_alive():
            logger.warning(f"[yt-dlp]{tag} timeout dopo {DOWNLOAD_TIMEOUT}s su url={url!r}, il thread continua in background come daemon")
            raise RuntimeError(f"Download timeout dopo {DOWNLOAD_TIMEOUT}s")
        if result["error"] is not None:
            raise result["error"]
        return result["path"]
