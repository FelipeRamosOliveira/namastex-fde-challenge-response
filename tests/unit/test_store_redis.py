"""RedisStore (usado no Docker) com fakeredis: cache, fila, sonda do breaker e lock distribuído."""

import asyncio

import fakeredis.aioredis
import pytest

from autoseguro.tools.store import RedisStore


@pytest.fixture
def store():
    return RedisStore(client=fakeredis.aioredis.FakeRedis(decode_responses=True))


async def test_basico(store):
    await store.set_json("a", {"x": 1}, ttl_s=60)
    assert await store.get_json("a") == {"x": 1}
    assert await store.incr("n") == 1 and await store.incr("n") == 2
    assert await store.set_if_absent("p", 1, ttl_s=5) is True
    assert await store.set_if_absent("p", 1, ttl_s=5) is False
    await store.push("fila", {"i": 1})
    await store.push("fila", {"i": 2})
    assert await store.list_all("fila") == [{"i": 1}, {"i": 2}]


async def test_lock_serializa(store):
    ordem = []

    async def tarefa(n):
        async with store.lock("conv:x", timeout_s=5):
            ordem.append(("in", n))
            await asyncio.sleep(0.05)
            ordem.append(("out", n))

    await asyncio.gather(tarefa(1), tarefa(2))
    assert ordem[0][0] == "in" and ordem[1][0] == "out" and ordem[1][1] == ordem[0][1]
