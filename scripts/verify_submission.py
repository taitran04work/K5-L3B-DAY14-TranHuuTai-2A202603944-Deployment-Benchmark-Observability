"""Validate submission files against measured data and inventory only lab resources."""
import csv
import hashlib
import json
import re
import struct
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports"
PROJECTS = {"k5-day14-docker", "k5-day14-scaling", "k5-day14-observability"}


def load(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def main():
    report = (ROOT / "BENCHMARK_REPORT.md").read_text(encoding="utf-8")
    mission = (ROOT / "MISSION_ANSWERS.md").read_text(encoding="utf-8")
    checker = (OUT / "production-readiness.txt").read_text(encoding="utf-8")
    assert "PASS 12/12" in checker and "43/43 checks passed" in checker
    assert checker[checker.index("  📋 Checklist Deliverable"):].strip() in mission
    table_rows = 0
    for c in (1, 10, 50, 100):
        r = load(f"load_v2_c{c}.json")
        expected = f"| {c} | {r['rps']:.2f} | {r['latency_ms']['p50']:.1f} | {r['latency_ms']['p95']:.1f} | {r['latency_ms']['p99']:.1f} | {100*r['error_rate']:.2f}% | {'PASS' if r['slo']['passed'] else 'FAIL'} |"
        assert expected in report
        assert r["total_requests"] == 300
        table_rows += 1
    for slow in ("0", "0.03", "0.1"):
        r = load(f"load_v2_slow_{slow}.json")
        assert f"| {slow} | {r['latency_ms']['avg']:.1f} | {r['latency_ms']['p95']:.1f} | {r['latency_ms']['p99']:.1f} |" in report
        table_rows += 1
    evaluations = [load(f"eval_{v}.json") for v in ("v1", "v2", "v2_fixed")]
    assert evaluations[-1]["passed"] == evaluations[-1]["total"] == 23
    assert "| Accuracy | " + " | ".join(f"{r['passed']}/{r['total']} ({100*r['accuracy']:.2f}%)" for r in evaluations) + " |" in report
    for key, digits in (("avg_tokens", 1), ("total_cost_usd", 6), ("cost_per_correct_usd", 8)):
        assert " | ".join(f"{r[key]:.{digits}f}" for r in evaluations) in report
    table_rows += 4
    for n in (1, 3):
        path = ROOT / f"benchmark-results/scale_{n}_stats.csv"
        assert path.read_bytes() == (ROOT / "06-lab-complete/benchmark-observability/production/benchmark-results" / path.name).read_bytes()
        for row in csv.DictReader(path.read_text(encoding="utf-8").splitlines()):
            if row["Name"] in ("Aggregated", "/ask"):
                expected = f"| {n} | {float(row['Requests/s']):.6f} | {row['50%']} | {row['95%']} | {row['99%']} | {row['Failure Count']}/{row['Request Count']} ({100*int(row['Failure Count'])/int(row['Request Count']):.4f}%) |"
                assert expected in report
                table_rows += 1
    chaos = load("chaos-experiments.json")
    assert chaos["cleanup_recovery"]["verified_locust"] == {"state": "stopped", "user_count": 0}
    assert len(chaos["cleanup_recovery"]["verified_agent_configs"]) == 3
    for row in chaos["experiments"]:
        assert f"{row['elapsed_seconds']:.3f}s" in report
    shots = []
    for name in ("grafana-dashboard", "jaeger-slow-trace", "jaeger-error-trace", "prometheus-alert-firing"):
        for suffix, width in (("", 2560), ("-1280", 1280)):
            path = ROOT / f"screenshots/{name}{suffix}.png"
            data = path.read_bytes()
            assert data[:8] == b"\x89PNG\r\n\x1a\n"
            w, h = struct.unpack(">II", data[16:24])
            assert w == width
            shots.append({"path": str(path.relative_to(ROOT)), "width": w, "height": h, "sha256": hashlib.sha256(data).hexdigest()})
    raw_containers = subprocess.run(["docker", "ps", "-a", "--format", "json"], capture_output=True, text=True, check=True, timeout=20).stdout
    containers = [json.loads(line) for line in raw_containers.splitlines() if line.strip()]
    # Keep only name/id/state/ports, never image labels containing maintainers' email.
    owned = []
    for c in containers:
        labels = dict(item.split("=", 1) for item in c.get("Labels", "").split(",") if "=" in item)
        if c["Names"].startswith("day14-") or labels.get("com.docker.compose.project") in PROJECTS:
            owned.append({k: c[k] for k in ("ID", "Names", "State", "Ports")})
    running = [c for c in owned if c["State"] == "running"]
    inventory = {"captured_at": datetime.now(timezone.utc).isoformat(), "owned": owned, "running_count": len(running), "locust_load_stopped": True, "fault_defaults_restored": True, "cleanup_policy": "docker compose down denied; no bypass attempted"}
    (OUT / "cleanup-inventory.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    lines = ["# Cleanup cần người có quyền thực hiện", "", "Locust load đã xác minh stopped / 0 users; fault config của 3 agent đã về mặc định. Browser context đóng. Docker compose down bị approval policy từ chối trong headless session; không lách bằng interpreter hoặc scale-to-zero.", "", f"Còn **{len(running)} container của task đang chạy** tại {inventory['captured_at']}. Không dừng Docker Desktop, threadrop-db hoặc bất kỳ container/PID nào ngoài danh sách.", "", "| Container | ID | State |", "|---|---|---|"]
    lines += [f"| {c['Names']} | {c['ID']} | {c['State']} |" for c in owned]
    lines += ["", "Người có quyền có thể dừng đúng các container đang chạy bằng lệnh sau (chưa chạy thành công trong task):", "", "```bash", "docker stop " + " ".join(c["Names"] for c in running), "```", "", "Không dùng prune, down -v, xóa volume hoặc kill toàn bộ node/chrome. Không xóa dữ liệu. Container đã exit không cần kill. Giữ Redis volumes nếu còn cần kiểm thử lại.", "", "Sau cleanup: kiểm docker ps chỉ còn các service vốn có, rồi trả task về coder2 để gửi techlead review. Cloud URL và ba ảnh cloud vẫn chủ động chưa làm theo yêu cầu; không phải lý do block."]
    (OUT / "cleanup-required.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    emails = []
    for folder in (OUT, ROOT / "benchmark-results"):
        for path in folder.rglob("*"):
            if path.is_file() and path.suffix in (".md", ".txt", ".json", ".jsonl", ".csv"):
                if re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", path.read_text(encoding="utf-8", errors="replace")):
                    emails.append(str(path.relative_to(ROOT)))
    assert not emails, f"Email in submission evidence: {emails}"
    for doc in (ROOT / "MISSION_ANSWERS.md", ROOT / "BENCHMARK_REPORT.md", ROOT / "DEPLOYMENT.md"):
        assert doc.stat().st_size > 100
        for target in re.findall(r"\]\(([^)]+)\)", doc.read_text(encoding="utf-8")):
            if not target.startswith(("http", "#")):
                assert (ROOT / target).exists(), (doc.name, target)
    result = {"verified_at": inventory["captured_at"], "numeric_rows_verified": table_rows, "grader_pass_12_of_12": True, "fixed_eval_pass_23_of_23": True, "screenshots": shots, "email_findings": emails, "cleanup_pending_containers": len(running)}
    (OUT / "submission-verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
