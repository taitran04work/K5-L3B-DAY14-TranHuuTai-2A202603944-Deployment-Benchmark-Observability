"""Exercise real load/eval scripts, retaining their outputs and exit codes."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from run_examples import server

ROOT = Path(__file__).resolve().parents[1]
FOLDER = "06-lab-complete/benchmark-observability/develop"
BASE = ROOT / FOLDER
REPORTS = BASE / "reports"
REPORTS.mkdir(exist_ok=True)


def run(args, name, allowed=(0, 1)):
    completed = subprocess.run([sys.executable, *args], cwd=BASE,
                               env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                               capture_output=True, text=True, encoding="utf-8", timeout=240)
    (REPORTS / f"{name}.txt").write_text(completed.stdout + completed.stderr, encoding="utf-8")
    print(completed.stdout, flush=True)
    assert completed.returncode in allowed, (name, completed.returncode, completed.stderr)
    return {"command": args, "exit_code": completed.returncode}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["baseline", "load", "tail", "fixed"])
    phase = parser.parse_args().phase
    manifest = []
    if phase == "baseline":
        with server(FOLDER, 8001, AGENT_VERSION="v1", MOCK_ERROR_RATE="0"):
            manifest.append(run(["eval/run_eval.py", "--url", "http://localhost:8001", "--out", "reports/eval_v1.json"], "eval_v1"))
        with server(FOLDER, 8002, AGENT_VERSION="v2", MOCK_ERROR_RATE="0"):
            manifest.append(run(["eval/run_eval.py", "--url", "http://localhost:8002", "--baseline", "reports/eval_v1.json", "--out", "reports/eval_v2.json"], "eval_v2"))
    if phase in ("baseline", "load"):
        with server(FOLDER, 8002, AGENT_VERSION="v2", MOCK_ERROR_RATE="0.01", MOCK_SLOW_RATE="0.03"):
            for c in [1, 10, 50, 100]:
                name = f"load_v2_c{c}"
                manifest.append(run(["load_test.py", "--url", "http://localhost:8002", "--requests", "300", "--concurrency", str(c), "--out", f"reports/{name}.json"], name))
    if phase in ("baseline", "load", "tail"):
        for slow in (["0.03", "0.1"] if phase == "tail" else ["0", "0.03", "0.1"]):
            with server(FOLDER, 8002, AGENT_VERSION="v2", MOCK_ERROR_RATE="0.01", MOCK_SLOW_RATE=slow):
                name = f"load_v2_slow_{slow}"
                manifest.append(run(["load_test.py", "--url", "http://localhost:8002", "--requests", "300", "--concurrency", "20", "--out", f"reports/{name}.json"], name))
    if phase == "fixed":
        with server(FOLDER, 8002, AGENT_VERSION="v2", MOCK_ERROR_RATE="0"):
            manifest.append(run(["eval/run_eval.py", "--url", "http://localhost:8002", "--min-accuracy", "1.0", "--baseline", "reports/eval_v2.json", "--out", "reports/eval_v2_fixed.json"], "eval_v2_fixed", allowed=(0,)))
        with server(FOLDER, 8001, AGENT_VERSION="v1", MOCK_ERROR_RATE="0"):
            manifest.append(run(["eval/run_eval.py", "--url", "http://localhost:8001", "--baseline", "reports/eval_v2.json", "--out", "reports/eval_regression.json"], "eval_regression", allowed=(1,)))
    (REPORTS / f"manifest_{phase}.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
