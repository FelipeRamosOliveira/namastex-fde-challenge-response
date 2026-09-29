"""Armazenamento chave-valor assíncrono para cache, circuit breaker e fila de handoff.

Redis em produção/Docker; memória nos testes e quando REDIS_URL não está definido.
"""

from __future__ import annotations

import json
import time
from typing import Any, Protocol


class KVStore(Protocol):
    async def get_json(self, key: str) -> Any | None: ...
    async def set_json(self, key: str, value: Any, ttl_s: int | None = None) -> None: ...
    async def incr(self, key: str, ttl_s: int | None = None) -> int: ...
    async def delete(self, key: str) -> None: ...
    async def push(self, key: str, value: Any) -> None: ...
    async def list_all(self, key: str) -> list[Any]: ...


class MemoryStore:
    def __init__(self, clock=time.monotonic) -> None:
        self._d: dict[str, tuple[Any, float | None]] = {}
        self._clock = clock

    def _alive(self, key: str) -> bool:
        if key not in self._d:
            return False
        _, exp = self._d[key]
        if exp is not None and self._clock() >= exp:
            del self._d[key]
            return False
        return True

    async def get_json(self, key: str) -> Any | None:
        return self._d[key][0] if self._alive(key) else None

    async def set_json(self, key: str, value: Any, ttl_s: int | None = None) -> None:
        self._d[key] = (json.loads(json.dumps(value)), self._clock() + ttl_s if ttl_s else None)

    async def incr(self, key: str, ttl_s: int | None = None) -> int:
        cur = (await self.get_json(key)) or 0
        exp = self._d[key][1] if self._alive(key) else (self._clock() + ttl_s if ttl_s else None)
        self._d[key] = (cur + 1, exp)
        return cur + 1

    async def delete(self, key: str) -> None:
        self._d.pop(key, None)

    async def push(self, key: str, value: Any) -> None:
        cur = (await self.get_json(key)) or []
        cur.append(value)
        self._d[key] = (json.loads(json.dumps(cur)), None)

    async def list_all(self, key: str) -> list[Any]:
        return (await self.get_json(key)) or []


class RedisStore:
    def __init__(self, url: str, prefix: str = "autoseguro:") -> None:
        import redis.asyncio as redis

        self._r = redis.from_url(url, decode_responses=True)
        self._p = prefix

    async def get_json(self, key: str) -> Any | None:
        raw = await self._r.get(self._p + key)
        return json.loads(raw) if raw is not None else None

    async def set_json(self, key: str, value: Any, ttl_s: int | None = None) -> None:
        await self._r.set(self._p + key, json.dumps(value, ensure_ascii=False), ex=ttl_s)

    async def incr(self, key: str, ttl_s: int | None = None) -> int:
        n = await self._r.incr(self._p + key)
        if ttl_s and n == 1:
            await self._r.expire(self._p + key, ttl_s)
        return int(n)

    async def delete(self, key: str) -> None:
        await self._r.delete(self._p + key)

    async def push(self, key: str, value: Any) -> None:
        await self._r.rpush(self._p + key, json.dumps(value, ensure_ascii=False))

    async def list_all(self, key: str) -> list[Any]:
        return [json.loads(x) for x in await self._r.lrange(self._p + key, 0, -1)]


def make_store(redis_url: str | None) -> KVStore:
    return RedisStore(redis_url) if redis_url else MemoryStore()
