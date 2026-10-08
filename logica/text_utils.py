import re

from .config import logger, FILENAME_MAX_LENGTH


def sanitize_filename(name: str, max_length: int = FILENAME_MAX_LENGTH) -> str:
    result = re.sub(r'[<>:"/\\|?*\n\r\t]', '_', name).strip()[:max_length]
    if result != name:
        logger.debug(f"[Filename] sanitizzato: {name!r} → {result!r}")
    return result


def sanitize_folder_name(name: str) -> str:
    """Come sanitize_filename, ma senza punti e spazi finali. Windows li toglie da solo
    quando crea la cartella, e yt-dlp li sostituisce con '#' ("album..." -> "album..#"):
    il programma cercherebbe i file in una cartella diversa da quella dove finiscono."""
    result = sanitize_filename(name).rstrip(" .")
    return result or "_"
