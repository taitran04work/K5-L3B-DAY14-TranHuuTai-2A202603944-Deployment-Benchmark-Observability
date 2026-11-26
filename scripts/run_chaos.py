"""Two real fault experiments with measured alert detection and bounded load."""
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports"
COMPOSE = ["docker", "compose", "-p", "k5-day14-observability", "-f",
           str(ROOT / "06-lab-complete/benchmark-observability/production/docker-compose.yml"),
           "-f", str(ROOT / "scripts/compose.obs-ports.yml")]
result: dict = {"experiments": []}


def stamp():
    return datetime.now(timezone.utc).isoformat()


def save():
    (OUT / "chaos-experiments.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")


def configure(label, **env):
    completed = subprocess.run([*COMPOSE, "up", "-d", "--scale", "agent=3"], env={**os.environ, **env},
                               capture_output=True, text=True, encoding="utf-8", timeout=120)
    (OUT / f"chaos-{label}-compose.txt").write_text(completed.stdout + completed.stderr, encoding="utf-8")
    completed.check_returncode()


def wait_alerts(client, experiment, expected, timeout):
    deadline = time.monotonic() + timeout
    observations = []
    while time.monotonic() < deadline:
        data = client.get("http://localhost:9090/api/v1/alerts").json()
        active = {a["labels"]["alertname"] for a in data["data"]["alerts"] if a["state"] == "firing"}
        observations.append({"observed_at": stamp(), "response": data})
        if expected <= active:
            experiment.update(firing_observed_at=stamp(), elapsed_seconds=round(time.monotonic() - experiment.pop("monotonic_start"), 3), alerts=sorted(active), observations=observations)
            save()
            print(json.dumps({k: v for k, v in experiment.items() if k != "observations"}), flush=True)
            return
        time.sleep(5)
    experiment["observations"] = observations
    experiment.pop("monotonic_start", None)
    save()
    raise TimeoutError(f"Alerts not firing: {expected}")


def cleanup(client):
    try:
        stopped = client.post("http://localhost:8089/stop")
        stopped.raise_for_status()
        result["locust_stop"] = stopped.json()
        if not result["locust_stop"].get("success"):
            raise RuntimeError("Locust did not confirm stop")
    except Exception as exc:
        result["cleanup_error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        try:
            configure("restore", MOCK_ERROR_RATE="0.01", MOCK_SLOW_RATE="0.03", LLM_MODEL="mock-llm-small")
            result["restored_at"] = stamp()
        finally:
            save()


def main():
    with httpx.Client(timeout=20) as client:
        try:
            a = {"label": "A", "changed_at": stamp(), "monotonic_start": time.monotonic(), "config": {"MOCK_ERROR_RATE": "0.2", "MOCK_SLOW_RATE": "0.03", "LLM_MODEL": "mock-llm-small"}}
            result["experiments"].append(a)
            configure("A", **a["config"])
            response = client.post("http://localhost:8089/swarm", data={"user_count": "30", "spawn_rate": "5", "host": "http://nginx"})
            response.raise_for_status()
            result["locust_start"] = response.json()
            assert result["locust_start"]["success"]
            print("Started 30-user Locust load; waiting for error-rate alert.", flush=True)
            wait_alerts(client, a, {"AgentHighErrorRate"}, 210)
            b = {"label": "B", "changed_at": stamp(), "monotonic_start": time.monotonic(), "config": {"MOCK_ERROR_RATE": "0.2", "MOCK_SLOW_RATE": "0.3", "LLM_MODEL": "mock-llm-small"}}
            result["experiments"].append(b)
            configure("B", **b["config"])
            print("Injected slow-rate 0.3, keeping error-rate 0.2; waiting for both alerts.", flush=True)
            wait_alerts(client, b, {"AgentHighErrorRate", "AgentHighLatencyP95"}, 270)
            result["firing_snapshot"] = client.get("http://localhost:9090/api/v1/alerts").json()
            result["locust_stats"] = client.get("http://localhost:8089/stats/requests").json()
            save()
            print("Both alerts FIRING. Holding load for 240 seconds for real UI capture.", flush=True)
            time.sleep(240)
        finally:
            cleanup(client)
            print("Stopped lab load and restored default fault settings (stack still running).", flush=True)


if __name__ == "__main__":
    main()
