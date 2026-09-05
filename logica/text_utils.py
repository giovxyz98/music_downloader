import re

from .config import FILENAME_MAX_LENGTH


def sanitize_filename(name: str, max_length: int = FILENAME_MAX_LENGTH) -> str:
    return re.sub(r'[<>:"/\\|?*\n\r\t]', '_', name).strip()[:max_length]
