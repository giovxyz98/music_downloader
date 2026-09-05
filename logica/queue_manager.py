from typing import List, Optional

from .config import logger
from .models import QueueItem


class QueueManager:
    """Gestisce la coda di download: dati puri, nessuna dipendenza da tkinter."""

    def __init__(self):
        self._items: List[QueueItem] = []

    @property
    def items(self) -> List[QueueItem]:
        return list(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def add(self, query: str, label: str, meta: dict = None) -> Optional[QueueItem]:
        if any(item.query == query for item in self._items):
            logger.debug(f"[Queue] add rifiutato, duplicato di query={query!r} già in coda (label={label!r})")
            return None
        item = QueueItem(query=query, label=label, meta=meta or {})
        self._items.append(item)
        logger.debug(f"[Queue] add: '{label}' query={query!r} meta={meta!r} → coda ora a {len(self._items)} elementi")
        return item

    def remove_at(self, idx: int) -> None:
        if 0 <= idx < len(self._items):
            removed = self._items.pop(idx)
            logger.debug(f"[Queue] remove_at({idx}): rimossa '{removed.label}' → coda ora a {len(self._items)} elementi")
        else:
            logger.warning(f"[Queue] remove_at({idx}) fuori range (coda a {len(self._items)} elementi), ignorato")

    def remove_indices(self, indices) -> None:
        logger.debug(f"[Queue] remove_indices({sorted(indices)})")
        for idx in sorted(indices, reverse=True):
            self.remove_at(idx)

    def clear(self) -> None:
        n = len(self._items)
        self._items.clear()
        logger.debug(f"[Queue] clear: svuotati {n} elementi")
