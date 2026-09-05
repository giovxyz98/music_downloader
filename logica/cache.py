import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from .config import logger, MAX_SEARCHES, MAX_HISTORY, RECENT_SEARCHES_SHOWN, ROOT_DIR


class CacheManager:
    CACHE_FILE = ROOT_DIR / "music_cache.json"

    def __init__(self):
        self._lock = threading.Lock()
        self.data: dict = {"recent_searches": [], "download_history": []}
        self._load()

    def _load(self):
        if self.CACHE_FILE.exists():
            try:
                with open(self.CACHE_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                with self._lock:
                    self.data["recent_searches"]  = loaded.get("recent_searches", [])
                    self.data["download_history"] = loaded.get("download_history", [])
                logger.debug(
                    f"[Cache] Caricato {self.CACHE_FILE.name}: "
                    f"{len(self.data['recent_searches'])} ricerche recenti, "
                    f"{len(self.data['download_history'])} voci cronologia"
                )
            except Exception as e:
                logger.error(f"[Cache] Errore lettura: {e}")
        else:
            logger.debug(f"[Cache] {self.CACHE_FILE.name} non esiste ancora, parto con stato vuoto")

    def _save_unlocked(self):
        """Salva il file JSON. Deve essere chiamato con self._lock già acquisito."""
        try:
            with open(self.CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            logger.debug(f"[Cache] Salvato {self.CACHE_FILE.name}")
        except Exception as e:
            logger.error(f"[Cache] Errore salvataggio: {e}")

    def save(self):
        with self._lock:
            self._save_unlocked()

    def add_search(self, type_: str, query: str):
        with self._lock:
            before = len(self.data["recent_searches"])
            self.data["recent_searches"] = [
                s for s in self.data["recent_searches"]
                if not (s["type"] == type_ and s["query"].lower() == query.lower())
            ]
            dedup_removed = before - len(self.data["recent_searches"])
            self.data["recent_searches"].insert(0, {
                "type":  type_,
                "query": query,
                "date":  datetime.now().isoformat(timespec="seconds"),
            })
            over_limit = len(self.data["recent_searches"]) - MAX_SEARCHES
            self.data["recent_searches"] = self.data["recent_searches"][:MAX_SEARCHES]
            logger.debug(
                f"[Cache] add_search type={type_!r} query={query!r} "
                f"(rimossi {dedup_removed} duplicati, troncati {max(over_limit, 0)} per limite {MAX_SEARCHES}) "
                f"→ {len(self.data['recent_searches'])} ricerche in cronologia"
            )
            self._save_unlocked()

    def add_download(self, entry: dict):
        with self._lock:
            self.data["download_history"].insert(0, {
                **entry,
                "date": datetime.now().isoformat(timespec="seconds"),
            })
            over_limit = len(self.data["download_history"]) - MAX_HISTORY
            self.data["download_history"] = self.data["download_history"][:MAX_HISTORY]
            logger.debug(
                f"[Cache] add_download entry={entry} "
                f"(troncate {max(over_limit, 0)} voci per limite {MAX_HISTORY}) "
                f"→ {len(self.data['download_history'])} voci cronologia"
            )
            self._save_unlocked()

    def get_recent_searches(self, limit: int = RECENT_SEARCHES_SHOWN) -> List[Dict]:
        with self._lock:
            result = list(self.data["recent_searches"][:limit])
            logger.debug(f"[Cache] get_recent_searches(limit={limit}) → {len(result)} risultati")
            return result

    def get_download_history(self) -> List[Dict]:
        with self._lock:
            result = list(self.data["download_history"])
            logger.debug(f"[Cache] get_download_history() → {len(result)} voci")
            return result

    def clear_history(self):
        with self._lock:
            n = len(self.data["download_history"])
            self.data["download_history"] = []
            logger.info(f"[Cache] clear_history: cancellate {n} voci di cronologia download")
            self._save_unlocked()

