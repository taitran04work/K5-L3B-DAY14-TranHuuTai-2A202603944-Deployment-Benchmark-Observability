"""Exercise 7.1: question lengths must be a histogram, not labels."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from app import app


def test_question_length_is_observed(monkeypatch):
    monkeypatch.setenv("MOCK_ERROR_RATE", "0")
    with TestClient(app) as client:
        before = REGISTRY.get_sample_value("agent_question_length_chars_count") or 0
        assert client.post("/ask", json={"question": "Hello"}).status_code == 200
        assert REGISTRY.get_sample_value("agent_question_length_chars_count") == before + 1
        assert 'agent_question_length_chars_bucket{le="20.0"}' in client.get("/metrics").text
