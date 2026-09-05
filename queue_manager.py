from typing import List, Optional

from models import QueueItem


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
            return None
        item = QueueItem(query=query, label=label, meta=meta or {})
        self._items.append(item)
        return item

    def remove_at(self, idx: int) -> None:
        if 0 <= idx < len(self._items):
            self._items.pop(idx)

    def remove_indices(self, indices) -> None:
        for idx in sorted(indices, reverse=True):
            self.remove_at(idx)

    def clear(self) -> None:
        self._items.clear()
