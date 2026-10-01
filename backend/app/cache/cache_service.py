"""快取抽象層。v1為backend process內的記憶體實作，供候選池/持股清單即時查詢、每日條件結果暫存、
告警防重複發送使用。未來若backend擴展為多worker或需要pub/sub即時推播，替換這個類別的實作接Redis即可，
不需更動呼叫端邏輯。"""

import time
from typing import Any


class CacheService:
    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, float | None]] = {}

    def get(self, key: str) -> Any | None:
        item = self._store.get(key)
        if item is None:
            return None
        value, expires_at = item
        if expires_at is not None and time.time() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl_seconds: float | None = None) -> None:
        expires_at = time.time() + ttl_seconds if ttl_seconds else None
        self._store[key] = (value, expires_at)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)


cache_service = CacheService()
