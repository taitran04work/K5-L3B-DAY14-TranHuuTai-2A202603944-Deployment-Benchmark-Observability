"""Regression tests for Locust POST /stop and unconditional config restore."""
import importlib.util
from pathlib import Path

import httpx
import pytest


def load_script():
    path = Path(__file__).resolve().parents[1] / "run_chaos.py"
    spec = importlib.util.spec_from_file_location("run_chaos_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("stop_status", [200, 503])
def test_cleanup_posts_stop_and_always_restores(monkeypatch, stop_status):
    script = load_script()
    calls = []
    requests = []
    monkeypatch.setattr(script, "configure", lambda label, **env: calls.append((label, env)))
    monkeypatch.setattr(script, "save", lambda: None)

    def respond(request):
        requests.append((request.method, request.url.path))
        return httpx.Response(stop_status, json={"success": stop_status == 200}, request=request)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        if stop_status == 200:
            script.cleanup(client)
            assert script.result["locust_stop"] == {"success": True}
        else:
            with pytest.raises(httpx.HTTPStatusError):
                script.cleanup(client)
    assert requests == [("POST", "/stop")]
    assert calls == [("restore", {"MOCK_ERROR_RATE": "0.01", "MOCK_SLOW_RATE": "0.03", "LLM_MODEL": "mock-llm-small"})]
    assert "restored_at" in script.result
