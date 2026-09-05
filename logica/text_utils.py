import re

from .config import logger, FILENAME_MAX_LENGTH


def sanitize_filename(name: str, max_length: int = FILENAME_MAX_LENGTH) -> str:
    result = re.sub(r'[<>:"/\\|?*\n\r\t]', '_', name).strip()[:max_length]
    if result != name:
        logger.debug(f"[Filename] sanitizzato: {name!r} → {result!r}")
    return result
