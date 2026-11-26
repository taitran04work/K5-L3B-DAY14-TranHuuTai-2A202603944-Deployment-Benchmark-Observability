"""Read-only diagnostics for the lab's owned processes and evidence."""
import json
import subprocess
from pathlib import Path
import psutil

root = Path(__file__).resolve().parents[1]
listeners = {c.pid: c.laddr.port for c in psutil.net_connections(kind="tcp") if c.status == "LISTEN" and c.laddr.port in (8001, 8002, 8080, 18080)}
for proc in psutil.process_iter(["pid", "ppid", "name", "cmdline"]):
    try:
        cmd = " ".join(proc.info["cmdline"] or [])
        if proc.pid in listeners or (str(root).lower() in cmd.lower() and proc.info["name"].lower().startswith("python")):
            print(json.dumps({**proc.info, "port": listeners.get(proc.pid)}, ensure_ascii=False))
    except psutil.Error:
        pass
for file in (root / "06-lab-complete/benchmark-observability/develop/reports").glob("*.json"):
    report = json.loads(file.read_text(encoding="utf-8"))
    print(file.name, json.dumps({k: v for k, v in report.items() if k != "results"}, ensure_ascii=False))
