"""Fixtures compartilhadas. A quote-api usada nos testes de integração é a ORIGINAL do
desafio (submódulo vendor/challenge), subida em processo local com a instabilidade configurável."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
QUOTE_SERVICE = ROOT / "vendor" / "challenge" / "quote-service"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def run_quote_api(failure: float = 0.0, slow: float = 0.0, slow_seconds: float = 8.0, seed: int | None = 42):
    port = _free_port()
    env = {
        **os.environ,
        "QUOTE_FAILURE_RATE": str(failure),
        "QUOTE_SLOW_RATE": str(slow),
        "QUOTE_SLOW_SECONDS": str(slow_seconds),
    }
    if seed is not None:
        env["QUOTE_SEED"] = str(seed)
    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", "warning"],
        cwd=QUOTE_SERVICE,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                if httpx.get(url + "/health", timeout=0.5).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        else:
            raise RuntimeError("quote-api não subiu")
        yield url
    finally:
        proc.kill()  # a API mock segura requisições lentas em time.sleep; não precisa de shutdown gracioso
        proc.wait(timeout=5)


@pytest.fixture
def quote_api():
    """Uso: with quote_api(failure=1.0) as url: ..."""
    if not QUOTE_SERVICE.exists():
        pytest.skip("submódulo vendor/challenge ausente")
    return run_quote_api


@pytest.fixture(scope="session")
def stable_quote_url():
    if not QUOTE_SERVICE.exists():
        pytest.skip("submódulo vendor/challenge ausente")
    with run_quote_api(failure=0.0, slow=0.0) as url:
        yield url
