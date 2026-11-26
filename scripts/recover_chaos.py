"""Recover the real cleanup failure without rerunning or changing benchmark data."""
import json
import subprocess
from pathlib import Path

import httpx
import run_chaos

ROOT = Path(__file__).resolve().parents[1]


def main():
    evidence = ROOT / "reports/chaos-experiments.json"
    run_chaos.result = json.loads(evidence.read_text(encoding="utf-8"))
    run_chaos.result["cleanup_recovery"] = {
        "original_failure": "GET /stop returned HTTP405; JSON decode failed before config restore",
        "fix": "POST /stop, raise_for_status, and restore in nested finally",
        "started_at": run_chaos.stamp(),
    }
    with httpx.Client(timeout=20) as client:
        run_chaos.cleanup(client)
        state = client.get("http://localhost:8089/stats/requests").json()
        assert state["state"] == "stopped" and state["user_count"] == 0
        run_chaos.result["cleanup_recovery"]["verified_locust"] = {"state": state["state"], "user_count": state["user_count"]}
    ids = subprocess.run(["docker", "ps", "-q", "--filter", "label=com.docker.compose.project=k5-day14-observability", "--filter", "label=com.docker.compose.service=agent"], capture_output=True, text=True, check=True, timeout=20).stdout.split()
    assert len(ids) == 3
    agents = json.loads(subprocess.run(["docker", "inspect", *ids], capture_output=True, text=True, check=True, timeout=20).stdout)
    configs = []
    for agent in agents:
        env = dict(value.split("=", 1) for value in agent["Config"]["Env"] if "=" in value)
        config = {key: env[key] for key in ("MOCK_ERROR_RATE", "MOCK_SLOW_RATE", "LLM_MODEL")}
        assert config == {"MOCK_ERROR_RATE": "0.01", "MOCK_SLOW_RATE": "0.03", "LLM_MODEL": "mock-llm-small"}
        configs.append({"name": agent["Name"], "config": config})
    run_chaos.result["cleanup_recovery"]["verified_agent_configs"] = configs
    run_chaos.save()
    print(json.dumps(run_chaos.result["cleanup_recovery"], indent=2))


if __name__ == "__main__":
    main()
