"""Regression tests; use an isolated Redis DB, never production state."""
import json
import logging
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.update(AGENT_API_KEY="test-only-key", REDIS_URL="redis://127.0.0.1:16379/15",
                  ENVIRONMENT="staging", RATE_LIMIT_PER_MINUTE="10",
                  DAILY_BUDGET_USD="1", MONTHLY_BUDGET_USD="10")

from app.config import settings
from app.main import app


def test_configuration_reads_environment():
    assert settings.agent_api_key == os.environ["AGENT_API_KEY"]
    assert settings.redis_url == os.environ["REDIS_URL"]
    assert settings.environment == "staging"
    assert settings.rate_limit_per_minute == 10


def test_health_and_readiness():
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 200


def test_protected_request_pipeline(monkeypatch):
    from uuid import uuid4
    key = uuid4().hex
    monkeypatch.setattr(settings, "agent_api_key", key)
    with TestClient(app) as client:
        assert client.post("/ask", json={"question": "Hello"}).status_code == 401
        headers = {"X-API-Key": key}
        assert client.post("/ask", headers={"X-API-Key": "wrong"}, json={"question": "Hello"}).status_code == 401
        for _ in range(10):
            assert client.post("/ask", headers=headers, json={"question": "Hello"}).status_code == 200
        limited = client.post("/ask", headers=headers, json={"question": "Hello"})
        assert limited.status_code == 429
        assert int(limited.headers["Retry-After"]) > 0
        monkeypatch.setattr(settings, "agent_api_key", uuid4().hex)
        headers = {"X-API-Key": settings.agent_api_key}
        monkeypatch.setattr(settings, "daily_budget_usd", 0)
        assert client.post("/ask", headers=headers, json={"question": "Hello"}).status_code == 402
        assert client.post("/ask", headers=headers, json={"question": ""}).status_code == 422


def test_unavailable_redis_does_not_affect_liveness(monkeypatch):
    import redis
    from app import redis_client
    bad = redis.Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.1, socket_timeout=0.1)
    monkeypatch.setattr(redis_client, "r", bad)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 503


def test_missing_configured_key_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "agent_api_key", "")
    with TestClient(app) as client:
        assert client.post("/ask", json={"question": "Hello"}).status_code == 401


def test_json_formatter_escapes_quotes_and_newlines():
    from app.main import JsonFormatter
    record = logging.LogRecord("agent", logging.INFO, "", 1, 'quote " and\nnewline', (), None)
    encoded = JsonFormatter().format(record)
    assert len(encoded.splitlines()) == 1
    assert json.loads(encoded)["event"] == record.msg


def test_rate_limit_is_atomic_across_parallel_clients(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from uuid import uuid4
    from fastapi import HTTPException
    from app.rate_limiter import check_rate_limit
    key = uuid4().hex

    def attempt(_):
        try:
            check_rate_limit(key)
            return 200
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=20) as pool:
        statuses = list(pool.map(attempt, range(40)))
    assert statuses.count(200) == 10
    assert statuses.count(429) == 30


def test_budget_is_atomic_across_parallel_charges(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from uuid import uuid4
    from fastapi import HTTPException
    from app.cost_guard import record_cost
    monkeypatch.setattr(settings, "environment", uuid4().hex)
    monkeypatch.setattr(settings, "daily_budget_usd", 0.001)

    def charge(_):
        try:
            return record_cost(1000, 0)
        except HTTPException as exc:
            assert exc.status_code == 402
            return 0

    with ThreadPoolExecutor(max_workers=20) as pool:
        costs = list(pool.map(charge, range(40)))
    assert sum(cost > 0 for cost in costs) == 6
    assert sum(costs) <= 0.001
