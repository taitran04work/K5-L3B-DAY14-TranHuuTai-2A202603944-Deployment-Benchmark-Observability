"""Run lab examples against real HTTP processes; never print auth tokens."""
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports"
OUT.mkdir(exist_ok=True)


@contextmanager
def server(folder, port, **overrides):
    # Fail before spawning if a pre-existing service owns the chosen port.
    deadline = time.monotonic() + 3
    while True:
        with socket.socket() as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                break
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Port already has a listener: {port}")
        time.sleep(0.2)
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONIOENCODING": "utf-8", **overrides}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1",
                             "--port", str(port), "--no-access-log"], cwd=ROOT / folder,
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"Owned server PID={proc.pid}, folder={folder}, port={port}", flush=True)
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10) as client:
            for _ in range(100):
                if proc.poll() is not None:
                    raise RuntimeError(f"Server exited: {folder}")
                try:
                    client.get("/health")
                    break
                except httpx.ConnectError:
                    time.sleep(0.1)
            else:
                raise TimeoutError(folder)
            yield client
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        time.sleep(0.5)  # Windows launcher/socket teardown is not instantaneous.
        print(f"Stopped PID={proc.pid}", flush=True)


def snapshot(resp):
    return {"status": resp.status_code, "body": resp.json()}


def curl(url, headers=None):
    cmd = ["curl", "-sS", "-i", "-X", "POST", url, "-H", "Content-Type: application/json",
           "-d", '{"question":"Hello"}']
    for k, v in (headers or {}).items():
        cmd += ["-H", f"{k}: {v}"]
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=True, timeout=15).stdout


def main():
    result = {}
    with server("01-localhost-vs-production/develop", 18001) as c:
        result["part1_develop"] = snapshot(c.post("/ask", params={"question": "Hello"}))
        assert result["part1_develop"]["status"] == 200
        result["part1_develop_json"] = snapshot(c.post("/ask", json={"question": "Hello"}))
    with server("01-localhost-vs-production/production", 18002) as c:
        result["part1_production"] = snapshot(c.post("/ask", json={"question": "Hello"}))
        result["part1_health"] = snapshot(c.get("/health"))
        result["part1_ready"] = snapshot(c.get("/ready"))
    key = secrets.token_urlsafe(24)
    with server("04-api-gateway/develop", 18004, AGENT_API_KEY=key) as c:
        result["part4_api_key_401"] = curl(str(c.base_url) + "/ask")
        result["part4_api_key_200"] = curl(str(c.base_url) + "/ask", {"X-API-Key": key})
        assert "401 Unauthorized" in result["part4_api_key_401"]
        assert "200 OK" in result["part4_api_key_200"]
    with server("04-api-gateway/production", 18005, JWT_SECRET=secrets.token_urlsafe(32)) as c:
        login = c.post("/auth/token", json={"username": "student", "password": "demo123"})
        login.raise_for_status()
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        result["part4_token_status"] = login.status_code
        result["part4_jwt_statuses"] = [c.post("/ask", headers=headers, json={"question": "Hello"}).status_code for _ in range(20)]
        result["part4_jwt_429"] = curl(str(c.base_url) + "/ask", headers)
        assert result["part4_jwt_statuses"] == [200] * 10 + [429] * 10
    (OUT / "examples.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
