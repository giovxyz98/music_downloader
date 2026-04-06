import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from infra.config import logger, MAX_SEARCHES, MAX_HISTORY, RECENT_SEARCHES_SHOWN


class CacheManager:
    CACHE_FILE = Path(__file__).parent.parent / "music_cache.json"

    def __init__(self):
        self._lock = threading.Lock()
        self.data: dict = {"recent_searches": [], "download_history": [], "youtube_cache": {}}
        self._load()

    def _load(self):
        if self.CACHE_FILE.exists():
            try:
                with open(self.CACHE_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                with self._lock:
                    self.data["recent_searches"]  = loaded.get("recent_searches", [])
                    self.data["download_history"] = loaded.get("download_history", [])
                    self.data["youtube_cache"]    = loaded.get("youtube_cache", {})
            except Exception as e:
                logger.error(f"[Cache] Errore lettura: {e}")

    def _save_unlocked(self):
        """Salva il file JSON. Deve essere chiamato con self._lock già acquisito."""
        try:
            with open(self.CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[Cache] Errore salvataggio: {e}")

    def save(self):
        with self._lock:
            self._save_unlocked()

    def add_search(self, type_: str, query: str):
        with self._lock:
            self.data["recent_searches"] = [
                s for s in self.data["recent_searches"]
                if not (s["type"] == type_ and s["query"].lower() == query.lower())
            ]
            self.data["recent_searches"].insert(0, {
                "type":  type_,
                "query": query,
                "date":  datetime.now().isoformat(timespec="seconds"),
            })
            self.data["recent_searches"] = self.data["recent_searches"][:MAX_SEARCHES]
            self._save_unlocked()

    def add_download(self, entry: dict):
        with self._lock:
            self.data["download_history"].insert(0, {
                **entry,
                "date": datetime.now().isoformat(timespec="seconds"),
            })
            self.data["download_history"] = self.data["download_history"][:MAX_HISTORY]
            self._save_unlocked()

    def get_recent_searches(self, limit: int = RECENT_SEARCHES_SHOWN) -> List[Dict]:
        with self._lock:
            return list(self.data["recent_searches"][:limit])

    def get_download_history(self) -> List[Dict]:
        with self._lock:
            return list(self.data["download_history"])

    def clear_history(self):
        with self._lock:
            self.data["download_history"] = []
            self._save_unlocked()

    def get_youtube_urls(self, query: str) -> List[str]:
        with self._lock:
            cached = list(self.data["youtube_cache"].get(query, []))
        if cached:
            logger.debug(f"[Cache] YouTube hit: '{query}'")
        else:
            logger.debug(f"[Cache] YouTube miss: '{query}'")
        return cached

    def set_youtube_urls(self, query: str, urls: List[str]):
        with self._lock:
            self.data["youtube_cache"][query] = urls
            if len(self.data["youtube_cache"]) > MAX_SEARCHES:
                keys = list(self.data["youtube_cache"].keys())
                for k in keys[:-MAX_SEARCHES]:
                    del self.data["youtube_cache"][k]
            self._save_unlocked()
