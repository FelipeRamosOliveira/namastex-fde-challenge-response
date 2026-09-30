"""Cliente assíncrono e resiliente para POST /quote da API do desafio.

Estratégia (ver docs/adr/0003-resiliencia-quote.md):
- timeout curto por tentativa: a chamada lenta (8 s) é abandonada cedo;
- hedging: se a tentativa em voo passa de `hedge_after_s`, dispara outra em paralelo
  e usa a primeira que responder (seguro: /quote só calcula, não grava nada). Com orçamento:
  no máximo `quote_hedge_budget_ratio` das chamadas do minuto (piso `quote_hedge_budget_min`),
  e nenhum hedge enquanto houver cotação falhando (circuito degradado), para não dobrar a carga
  justamente quando a API está lenta;
- retry com backoff exponencial e jitter só para 5xx, timeout e erro de transporte;
- 422 (recusa de regra) e 400 (payload inválido) não repetem;
- circuit breaker compartilhado (KVStore) evita martelar a API quando ela está fora;
- cache da resposta REAL por payload + dia: o valor mostrado continua vindo da API. Cada entrega
  do cache ganha um `quote_id` próprio, com `source_quote_id` apontando para a resposta original.

Nunca devolve preço que não tenha vindo de um HTTP 200 da API.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

import httpx

from autoseguro.config import Settings
from autoseguro.tools.store import KVStore


class QuoteStatus(StrEnum):
    OK = "ok"
    RECUSADA = "recusada"  # 422: regra de aceitação
    INVALIDA = "invalida"  # 400: payload inválido
    INDISPONIVEL = "indisponivel"  # esgotou tentativas
    CIRCUITO_ABERTO = "circuito_aberto"


@dataclass
class Attempt:
    n: int
    http_status: int | None
    latency_ms: float
    outcome: str  # ok | recusada | invalida | erro_5xx | timeout | transporte | cancelada
    hedge: bool = False


@dataclass
class QuoteOutcome:
    status: QuoteStatus
    quote_request_id: str
    quote: dict[str, Any] | None = None
    quote_id: str | None = None
    motivo: str | None = None
    attempts: list[Attempt] = field(default_factory=list)
    from_cache: bool = False
    latency_ms: float = 0.0
    obtained_at: str | None = None
    source_quote_id: str | None = None  # cotação do cache: id da resposta original da API

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = str(self.status)
        return d


class _Transient(Exception):
    def __init__(self, outcome: str, http_status: int | None = None) -> None:
        self.outcome, self.http_status = outcome, http_status


def normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    p = {
        "plano_id": str(payload.get("plano_id") or "essencial").lower(),
        "idade": int(payload["idade"]),
        "veiculo_ano": int(payload["veiculo_ano"]),
    }
    if payload.get("cep"):
        dig = "".join(c for c in str(payload["cep"]) if c.isdigit())
        p["cep"] = f"{dig[:5]}-{dig[5:8]}" if len(dig) == 8 else str(payload["cep"])
    if payload.get("data_inicio"):
        p["data_inicio"] = str(payload["data_inicio"])
    return p


def _quote_valida(body: object) -> bool:
    if not isinstance(body, dict):
        return False
    ok_num = all(isinstance(body.get(k), int | float) for k in ("premio_mensal", "franquia"))
    return ok_num and isinstance(body.get("plano_nome"), str) and isinstance(body.get("coberturas"), list)


def _seconds_to_midnight(now: datetime | None = None) -> int:
    now = now or datetime.now()
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(60, int((tomorrow - now).total_seconds()))


class CircuitBreaker:
    """Conta COTAÇÕES que falharam (não tentativas), para o hedging não inflar a contagem.

    fechado -> (N cotações falhas seguidas) -> aberto -> (reset_s) -> meio_aberto:
    só UMA requisição passa como sonda (trava no KVStore), com uma única tentativa.
    """

    def __init__(self, store: KVStore, threshold: int, reset_s: float, name: str = "quote") -> None:
        self.store, self.threshold, self.reset_s = store, threshold, reset_s
        self._fail_key = f"breaker:{name}:fails"
        self._open_key = f"breaker:{name}:open_until"
        self._probe_key = f"breaker:{name}:probe"

    async def acquire(self) -> str:
        """'livre' (fechado), 'sonda' (meio-aberto, esta requisição testa) ou 'bloqueado'."""
        open_until = await self.store.get_json(self._open_key)
        if open_until is None:
            return "livre"
        if time.time() < open_until:
            return "bloqueado"
        ok = await self.store.set_if_absent(self._probe_key, 1, ttl_s=max(1, int(self.reset_s)))
        return "sonda" if ok else "bloqueado"

    async def state(self) -> str:
        open_until = await self.store.get_json(self._open_key)
        if open_until is None:
            return "fechado"
        return "aberto" if time.time() < open_until else "meio_aberto"

    async def success(self) -> None:
        for k in (self._fail_key, self._open_key, self._probe_key):
            await self.store.delete(k)

    async def failure(self, sonda: bool = False) -> None:
        n = await self.store.incr(self._fail_key)
        if sonda or n >= self.threshold:
            await self.store.set_json(self._open_key, time.time() + self.reset_s)
            await self.store.delete(self._probe_key)


class QuoteClient:
    def __init__(self, settings: Settings, store: KVStore, http: httpx.AsyncClient | None = None) -> None:
        self.s = settings
        self.store = store
        self.http = http or httpx.AsyncClient(base_url=settings.quote_api_url)
        self.breaker = CircuitBreaker(store, settings.breaker_failure_threshold, settings.breaker_reset_s)

    async def aclose(self) -> None:
        await self.http.aclose()

    @staticmethod
    def cache_key(payload: dict[str, Any], today: str | None = None) -> str:
        today = today or datetime.now().date().isoformat()
        raw = json.dumps(normalize_payload(payload), sort_keys=True) + today
        return "quote:" + hashlib.sha256(raw.encode()).hexdigest()[:24]

    async def _one(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        # Prazo total da tentativa: o timeout do httpx é por operação (conectar, ler...),
        # então uma resposta que pinga devagar poderia passar dele. asyncio.timeout fecha a conta.
        try:
            async with asyncio.timeout(self.s.quote_timeout_s):
                r = await self.http.post("/quote", json=payload, timeout=self.s.quote_timeout_s)
        except (TimeoutError, httpx.TimeoutException) as e:
            raise _Transient("timeout") from e
        except httpx.TransportError as e:
            raise _Transient("transporte") from e
        if r.status_code >= 500:
            raise _Transient("erro_5xx", r.status_code)
        try:
            body = r.json()
        except ValueError:
            body = {}
        if r.status_code == 200 and not _quote_valida(body):
            # 200 com corpo quebrado (proxy, HTML): não é cotação; trata como falha transitória
            raise _Transient("resposta_invalida", 200)
        return r.status_code, body

    async def cotar(self, payload: dict[str, Any]) -> QuoteOutcome:
        started = time.perf_counter()
        req_id = f"qr_{uuid.uuid4().hex[:12]}"
        payload = normalize_payload(payload)
        key = self.cache_key(payload)

        cached = await self.store.get_json(key)
        if cached:
            out = QuoteOutcome(**{**cached, "quote_request_id": req_id, "attempts": [], "from_cache": True})
            out.status = QuoteStatus(cached["status"])
            if out.quote_id:  # auditoria: leads diferentes recebiam o mesmo quote_id do cache
                out.source_quote_id = cached.get("source_quote_id") or cached["quote_id"]
                out.quote_id = f"q_{uuid.uuid4().hex[:12]}"
            out.latency_ms = round((time.perf_counter() - started) * 1000, 1)
            return out

        modo = await self.breaker.acquire()
        if modo == "bloqueado":
            return QuoteOutcome(QuoteStatus.CIRCUITO_ABERTO, req_id, motivo="circuit breaker aberto")
        max_attempts = 1 if modo == "sonda" else self.s.quote_max_attempts
        await self.store.incr(self._janela("chamadas"), ttl_s=120)

        attempts: list[Attempt] = []
        inflight: dict[asyncio.Task, tuple[int, float, bool]] = {}
        launched = 0
        next_launch_at = time.perf_counter()  # pode lançar já
        final: QuoteOutcome | None = None
        sem_hedge = False

        def launch(hedge: bool) -> None:
            nonlocal launched
            launched += 1
            t = asyncio.create_task(self._one(payload))
            inflight[t] = (launched, time.perf_counter(), hedge)

        try:
            while final is None:
                now = time.perf_counter()
                if not inflight and launched < max_attempts and now >= next_launch_at:
                    launch(hedge=False)
                if not inflight and launched >= max_attempts:
                    break
                # tempo até o próximo evento: hedge ou fim do backoff
                if inflight:
                    oldest = min(v[1] for v in inflight.values())
                    can_hedge = launched < max_attempts and len(inflight) == 1 and not sem_hedge
                    wait = max(0.0, oldest + self.s.quote_hedge_after_s - now) if can_hedge else None
                    done, _ = await asyncio.wait(inflight, timeout=wait, return_when=asyncio.FIRST_COMPLETED)
                    if not done:
                        if await self._pode_hedge():
                            launch(hedge=True)
                        else:
                            sem_hedge = True  # sem orçamento: espera a chamada em voo (ou o timeout)
                        continue
                    for t in done:
                        n, t0, hedge = inflight.pop(t)
                        lat = round((time.perf_counter() - t0) * 1000, 1)
                        try:
                            status, body = t.result()
                        except _Transient as e:
                            attempts.append(Attempt(n, e.http_status, lat, e.outcome, hedge))
                            if not inflight:
                                k = len(
                                    [
                                        a
                                        for a in attempts
                                        if a.outcome
                                        in ("erro_5xx", "timeout", "transporte", "resposta_invalida")
                                    ]
                                )
                                backoff = min(
                                    self.s.quote_backoff_max_s, self.s.quote_backoff_base_s * 2 ** (k - 1)
                                )
                                next_launch_at = time.perf_counter() + random.uniform(0, backoff)  # noqa: S311
                            continue
                        if status == 200:
                            attempts.append(Attempt(n, 200, lat, "ok", hedge))
                            await self.breaker.success()
                            final = QuoteOutcome(
                                QuoteStatus.OK,
                                req_id,
                                quote=body,
                                quote_id=f"q_{uuid.uuid4().hex[:12]}",
                                obtained_at=datetime.now().isoformat(timespec="seconds"),
                            )
                        elif status == 422:
                            attempts.append(Attempt(n, 422, lat, "recusada", hedge))
                            await self.breaker.success()
                            final = QuoteOutcome(QuoteStatus.RECUSADA, req_id, motivo=body.get("motivo"))
                        else:
                            attempts.append(Attempt(n, status, lat, "invalida", hedge))
                            final = QuoteOutcome(
                                QuoteStatus.INVALIDA, req_id, motivo=str(body.get("detalhe") or body)
                            )
                        break
                else:
                    await asyncio.sleep(max(0.0, next_launch_at - time.perf_counter()))
        finally:
            for t, (n, t0, hedge) in inflight.items():
                t.cancel()
                attempts.append(
                    Attempt(n, None, round((time.perf_counter() - t0) * 1000, 1), "cancelada", hedge)
                )

        if final is None:
            final = QuoteOutcome(QuoteStatus.INDISPONIVEL, req_id, motivo="tentativas esgotadas")
            await self.breaker.failure(sonda=modo == "sonda")
        final.attempts = sorted(attempts, key=lambda a: a.n)
        final.latency_ms = round((time.perf_counter() - started) * 1000, 1)

        if final.status in (QuoteStatus.OK, QuoteStatus.RECUSADA):
            cacheable = {
                k: v for k, v in final.to_dict().items() if k not in ("attempts", "quote_request_id")
            }
            await self.store.set_json(key, cacheable, ttl_s=_seconds_to_midnight())
        return final

    def _janela(self, nome: str) -> str:
        return f"hedge:{nome}:{int(time.time() // 60)}"  # janela de um minuto

    async def _pode_hedge(self) -> bool:
        """Hedge só com orçamento e com o circuito saudável (auditoria: dobrava a carga na lentidão)."""
        if (await self.store.get_json(self.breaker._fail_key) or 0) > 0:
            return False  # há cotação falhando: a API já está sofrendo
        chamadas = await self.store.get_json(self._janela("chamadas")) or 0
        usados = await self.store.get_json(self._janela("usados")) or 0
        limite = max(self.s.quote_hedge_budget_min, int(chamadas * self.s.quote_hedge_budget_ratio))
        if usados >= limite:
            return False
        await self.store.incr(self._janela("usados"), ttl_s=120)
        return True

    async def health(self) -> bool:
        try:
            r = await self.http.get("/health", timeout=2)
            return r.status_code == 200
        except httpx.HTTPError:
            return False
