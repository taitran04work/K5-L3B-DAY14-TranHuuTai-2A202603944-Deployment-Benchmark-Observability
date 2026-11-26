"""Generate submission tables from real evidence; never invent measurements."""
import csv
import hashlib
import io
import json
import math
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports"
DEV = ROOT / "06-lab-complete/benchmark-observability/develop/reports"
PROD = ROOT / "06-lab-complete/benchmark-observability/production/benchmark-results"


def read(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def command(args):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()


def scalar(snapshot, key):
    values = snapshot["queries"][key]["response"]["data"]["result"]
    assert len(values) == 1, key
    number = float(values[0]["value"][1])
    assert math.isfinite(number), f"No live load when measuring {key}"
    return number


def main():
    for file in DEV.iterdir():
        if file.is_file():
            shutil.copy2(file, OUT / file.name)
    csv_out = ROOT / "benchmark-results"
    csv_out.mkdir(exist_ok=True)
    for file in PROD.iterdir():
        if file.is_file() and file.name != ".gitkeep":
            shutil.copy2(file, csv_out / file.name)
    examples = read("examples.json")
    checker = (OUT / "production-readiness.txt").read_text(encoding="utf-8")
    assert "PASS 12/12" in checker and "43/43 checks passed" in checker
    blob = command(["git", "hash-object", "06-lab-complete/check_production_ready.py"])
    original_blob = command(["git", "rev-parse", "HEAD:06-lab-complete/check_production_ready.py"])
    assert blob == original_blob, "Never change the grader"
    images = [json.loads(line) for line in (OUT / "image-inspect.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    sizes = {image["RepoTags"][0]: image["Size"] for image in images}
    sizes["reduction_percent"] = 100 * (1 - sizes["my-agent:advanced"] / sizes["my-agent:develop"])
    (OUT / "image-sizes.json").write_text(json.dumps(sizes, indent=2), encoding="utf-8")
    env = {"measured_at": datetime.now(timezone.utc).isoformat(), "host": platform.platform(), "python_client": platform.python_version(),
           "docker": command(["docker", "info", "--format", '{"version":"{{.ServerVersion}}","cpus":{{.NCPU}},"memory_bytes":{{.MemTotal}}}'])}
    env["docker"] = json.loads(env["docker"])
    (OUT / "environment.json").write_text(json.dumps(env, indent=2), encoding="utf-8")
    checklist = checker[checker.index("  📋 Checklist Deliverable"):].strip()
    img_cli = (OUT / "image-sizes.txt").read_text(encoding="utf-8").strip()
    mission = f'''# Day 14 Lab — Mission Answers

**Học viên:** Trần Hữu Tài · **MSSV:** 2A202603944 · **Lớp:** K5-L3B  
**Ngày thực hiện:** 26/11/2026 · **Phạm vi:** Part 1–7 local; cloud chưa deploy theo yêu cầu.

## Part 1: Localhost vs Production

### Exercise 1.1 — Anti-patterns tìm thấy

Trong `01-localhost-vs-production/develop/app.py`:
1. Dòng 17–18 hardcode API key và database connection string: không thể rotate an toàn và dễ lộ qua Git; không chép giá trị vào bài.
2. Dòng 34 in key ra log: log aggregator cũng thành một nơi rò secret.
3. Dòng 21 bật DEBUG cố định, không tách môi trường.
4. Dòng 52 cố định port 8000, bỏ qua `PORT` do cloud cấp.
5. Dòng 51 bind `localhost`, không nhận kết nối qua network container như `0.0.0.0`.
6. Dòng 53 bật reload: phù hợp lúc sửa code, không phù hợp chạy production ổn định.
7. Không có `/health` và `/ready`: nền tảng không biết process sống hay dependency đã sẵn sàng.
8. Không có lifecycle cleanup/shutdown hook; không có lớp xác thực cho `/ask`.

### Exercise 1.2 — Chạy bản develop thật

Chạy bằng uvicorn không reload, đặt `PYTHONPATH` về gốc repo để tìm `utils`. Harness tự sở hữu PID và đóng process sau mỗi ví dụ: `python scripts/run_examples.py`.

```bash
curl -X POST 'http://127.0.0.1:18001/ask?question=Hello'
```

Output đã lưu trong `reports/examples.json`:
```json
{json.dumps(examples['part1_develop'], ensure_ascii=False, indent=2)}
```

Gửi JSON thay vì query vào develop trả **{examples['part1_develop_json']['status']}**, đúng chữ ký `question: str` của bản mẫu. Production nhận JSON và trả **{examples['part1_production']['status']}**; `/health` và `/ready` đều **200**. Không đánh đồng “HTTP chạy được” với production-ready.

### Exercise 1.3 — So sánh có giải thích

| Feature | Develop | Production mẫu | Vì sao quan trọng? |
|---|---|---|---|
| Config/secret | Hằng số trong code | `config.py`, `os.getenv`, validate | Một image chạy nhiều môi trường, secret có thể rotate ngoài Git |
| Health | Không có | `/health`, uptime, environment | Liveness giúp phát hiện process hỏng; dependency lỗi không nhất thiết phải restart process |
| Readiness | Không có | Cờ `is_ready`, `/ready` | Chỉ route traffic sau startup; Part 6 bổ sung kiểm tra Redis thật |
| Logging | `print`, in cả key | logging có cấu trúc dự kiến | Lọc/search sự kiện, không log secret; formatter mẫu bọc JSON bằng chuỗi chưa bảo đảm escaping, Part 6 dùng `json.dumps` thực sự |
| Shutdown | Không có lifecycle cleanup | `lifespan` startup/shutdown | Uvicorn ngừng nhận request mới, drain request đang chạy rồi đóng connection |
| Network | `localhost:8000` | host `0.0.0.0`, port từ env | Container/cloud truy cập được, không cố định port |
| Validation | Query string bắt buộc | Kiểm `question` trong JSON | Trả lỗi 422 rõ ràng thay vì lỗi khó hiểu |

## Part 2: Docker

### Exercise 2.1 — Trả lời theo Dockerfile thực tế

1. Base image develop là **`python:3.11`**, không phải `python:3.11-slim` trong đáp án ví dụ. Production có builder và runtime dùng slim.
2. Working directory: `/app`. Các lệnh sau `WORKDIR` và đường dẫn tương đối chạy từ đây.
3. `COPY requirements.txt` trước source cho phép cache layer cài dependency khi chỉ sửa code; đổi requirements mới phải cài lại.
4. `CMD` cung cấp lệnh/arguments mặc định, có thể thay bằng arguments sau tên image trong `docker run`. `ENTRYPOINT` chọn chương trình chạy; arguments thường được nối vào và có thể override bằng `--entrypoint`. Exec form giúp tiến trình nhận signal trực tiếp; shell wrapper phải dùng `exec` để không nuốt SIGTERM.

### Exercise 2.2 — Build và gọi container thật

Build từ **gốc repo**, vì `COPY` dùng đường dẫn tính từ gốc:
```bash
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
docker build -f 02-docker/production/Dockerfile -t my-agent:advanced .
```

Bản develop chạy ở port18020; production ở18021. Bằng chứng: `reports/part2-develop-ask.txt` và `reports/part2-production-health.txt` (đều HTTP200). Toàn bộ là mock LLM local, không gọi dịch vụ trả phí.

### Exercise 2.3 — Kích thước đo trên máy này

Output `docker images my-agent` thật:
```text
{img_cli}
```

Đồng thời giữ raw `docker image inspect` trong `reports/image-inspect.jsonl` và bản rút gọn `reports/image-sizes.json`:

| Image | `.Size` (bytes, inspect) | `.Size` / 1,000,000 (MB) |
|---|---:|---:|
| my-agent:develop | {sizes['my-agent:develop']} | {sizes['my-agent:develop']/1_000_000:.6f} |
| my-agent:advanced | {sizes['my-agent:advanced']} | {sizes['my-agent:advanced']/1_000_000:.6f} |

**Giảm {sizes['reduction_percent']:.2f}%**, tính nhất quán bằng `(develop.Size - advanced.Size) / develop.Size × 100`. Docker29 trên máy này hiển thị `.Size` của inspect khác cột SIZE của images; giữ cả hai output, không trộn hai cột để tính phần trăm. Với SIZE đã làm tròn của `docker images`, cả production Part 2 (240MB) và Part 6 (286MB) đều dưới500MB. Checker Part6 dùng inspect và báo63MB (đơn vị chia1024², xem output gốc).

Builder cài/build dependency, có compiler; runtime chỉ copy kết quả cài package và source cần chạy. Slim và việc không mang compiler/build cache vào runtime làm image nhỏ hơn. Multi-stage tự nó không bảo đảm nhỏ nếu vẫn copy mọi thứ từ builder.

### Exercise 2.4 — Stack và test Nginx

```mermaid
flowchart LR
    Client -->|HTTP host18022 to80| Nginx
    Nginx -->|8000| Agent
    Agent -. REDIS_URL / dependency .-> Redis
    Agent -. QDRANT_URL / dependency .-> Qdrant
```

Compose có agent, Redis, Qdrant và Nginx; Redis/Qdrant có healthcheck, agent chờ dependency healthy. **Endpoint mock Part2 chưa truy vấn Redis/Qdrant thực sự**; các mũi tên nét đứt là cấu hình dependency, không phải bằng chứng RAG chạy thật. Nginx là cổng truy cập ngoài, agent không publish trực tiếp trong stack.

Port80 bị Windows từ chối bind nên dùng override `scripts/compose.part2-ports.yml` (18022), không dừng dịch vụ khác:
```bash
docker compose -p k5-day14-docker -f 02-docker/production/docker-compose.yml -f scripts/compose.part2-ports.yml up -d --build
curl -i http://localhost:18022/health
curl -i -X POST http://localhost:18022/ask -H 'Content-Type: application/json' -d '{{"question":"Explain microservices"}}'
```

Hai lệnh trả200; output nguyên văn tại `reports/part2-nginx-health.txt` và `reports/part2-nginx-ask.txt`. File `.env.local` dùng cho ví dụ để trống, đã bị Git ignore; không thêm credential.

## Part 3: Cloud Deployment

### Exercise 3.1 — Railway / Render

**Public URL:**

**Chưa deploy, chưa đăng nhập cloud và chưa có ảnh cloud**, đúng phạm vi Tai giao. Khung cấu hình, biến môi trường và bốn lệnh tự kiểm có trong [DEPLOYMENT.md](DEPLOYMENT.md). Không lấy localhost hoặc ảnh Grafana thay cho URL/ảnh cloud. Phần điểm deploy thực tế chưa đạt.

### Exercise 3.2 — So sánh railway.toml với render.yaml

| Mục | Railway | Render |
|---|---|---|
| Định dạng/phạm vi | TOML cấu hình service: `[build]`, `[deploy]` | YAML Blueprint liệt kê `services`, `envVars` |
| Build | `builder="DOCKERFILE"`, Dockerfile trong root directory service | `runtime: docker`, `rootDir`, `dockerfilePath` |
| Liveness | `healthcheckPath="/health"` | `healthCheckPath: /health` |
| Secret | Đặt trên Variables/dashboard, không ghi giá trị vào TOML | `generateValue: true` hoặc `sync: false`, không dùng plaintext `value` cho key |
| Redis | Cấp Redis rồi tham chiếu REDIS_URL qua variables | Tự cấp Redis và nhập REDIS_URL; Blueprint hiện tại chưa tạo Redis |
| Port | Dùng PORT nền tảng cấp, CMD của image có `${{PORT:-8000}}` | Cùng cơ chế PORT trong CMD |

Khác nhau do Railway tách service/variables trong project, còn Blueprint Render mô tả cấu hình triển khai bằng danh sách YAML. Hai file hiện ở `06-lab-complete/`; hướng dẫn root directory nằm trong DEPLOYMENT.md.

### Exercise 3.3 — Pipeline Cloud Run (4 dòng)

1. `cloudbuild.yaml` bắt đầu bằng cài requirements và chạy pytest; bước build khai báo `waitFor: [test]`.
2. Build Docker image, gắn tag commit SHA và `latest`, sử dụng cache từ image trước rồi push tất cả tag lên registry trong cấu hình mẫu.
3. Deploy image theo commit SHA lên Cloud Run tại `asia-southeast1`, giới hạn1–10 instance, CPU/memory/timeout và lấy secret qua Secret Manager.
4. `service.yaml` là định nghĩa service khai báo image, env/secret, concurrency80, scaling và probes `/health`/`/ready`; có thể dùng `gcloud run services replace` thay vì tự bấm dashboard. Chỉ đọc cấu hình, chưa chạy GCP.

Lưu ý review: block test mẫu không dùng `set -e` và có `echo` sau pytest; để dùng CI thật cần bảo đảm pytest fail làm step fail, không chỉ dựa vào thứ tự `waitFor`. Không sửa file đề bài ngoài phạm vi.

## Part 4: API Security

### Exercise 4.1–4.3 — Output HTTP thật

Harness `scripts/run_examples.py` khởi động đúng source mẫu, gọi `curl -i`, lấy JWT từ `/auth/token` bằng tài khoản demo của repo, chỉ giữ token trong RAM. Không log response chứa token.

**Không có API key:**
```http
{examples['part4_api_key_401']}
```

**Có API key hợp lệ (giá trị không đưa vào bài):**
```http
{examples['part4_api_key_200']}
```

**JWT student, sau10 request thành công:**
```http
{examples['part4_jwt_429']}
```

Vòng20 request ghi trong `reports/examples.json`: `{examples['part4_jwt_statuses']}`. Token endpoint trả200. API key mẫu Part4 trả403 cho key sai; **Part6 đã tuân hợp đồng chặt hơn: thiếu/sai đều401**.

- Key được đọc trong `verify_api_key` qua header `X-API-Key`. Rotate bằng cập nhật secret env và rolling restart; cần thiết kế giai đoạn chấp nhận key cũ/mới nếu muốn chuyển đổi không gián đoạn, bản lab chỉ hỗ trợ một key.
- JWT chứa subject, role, issued-at, expiry và chữ ký; server kiểm tra chữ ký và hạn dùng trước khi dùng role. Không tin role do client tự khai báo ngoài token đã xác minh.
- Rate limiter mẫu Part4 dùng deque timestamps trong60s: sliding-window log (không phải token bucket), student10/phút, teacher/admin100/phút. Admin **không miễn hoàn toàn**; muốn bypass phải có chính sách server rõ ràng sau xác thực, không chỉ thêm query parameter.
- Limiter/cost guard mẫu Part4 còn ở RAM nên không phù hợp nhiều worker. Part6 dùng Redis Lua atomic, không reset giới hạn khi worker/process khởi động lại.

### Exercise 4.4 — Cost guard

Rate limit bảo vệ tốc độ; cost guard bảo vệ tiền, vì mỗi request có thể dùng lượng token/model khác nhau. Trong Part6: ledger Redis theo UTC day/month, kiểm ngân sách trước LLM, tính cost từ token ước tính sau response và cộng atomic vào cả hai ledger; key kỳ mới tự tách state, TTL dọn ledger cũ. Monthly default10USD; daily1USD, cả hai đọc env. Hết ngân sách trả402, Redis lỗi trả503 (fail closed). Các con số giá là **giá mô phỏng của bài lab**, không phải giá API hiện hành.

Hai bài test40 lời gọi song song kiểm limiter không vượt10 lượt và ghi ledger không vượt ngân sách. Mock chỉ trả text nên token dùng `max(1,len(text)//4)`, không giả là token billing thật. Nếu nối provider thật: phải dùng token usage của provider và reservation/refund trước call để giới hạn cả chi phí đang in-flight, thay vì xem ledger sau call là hard cap bill tuyệt đối.

## Part 5: Scaling & Reliability

### Exercise 5.1 — Liveness khác readiness

`/health` nói process còn chạy; `/ready` nói dependency/khởi tạo đã đủ để nhận traffic. Redis chết thì Part6 `/health` vẫn200, `/ready`503, `/ask`503 thay vì âm thầm bỏ kiểm soát chi phí. Restart app liên tục khi Redis chết không sửa được Redis và dễ tạo restart storm.

### Exercise 5.2 — Graceful shutdown

Uvicorn sở hữu SIGTERM, ngừng accept kết nối mới rồi drain request đang xử lý. Cleanup connection đặt trong `lifespan`, không thay signal handler của uvicorn. Dockerfile dùng `sh -c "exec uvicorn ..."` nên uvicorn là PID1. Checker Linux thật xác minh request in-flight vẫn200, process exit0; `docker stop` exit0 trong0.6s. Đây là kiểm chứng Part6; không gán kết quả đó cho signal handler mẫu Part1.

### Exercise 5.3–5.5 — Stateless, balancing và history thật

```bash
# .env.local để trống, không có credential
docker compose -p k5-day14-scaling -f 05-scaling-reliability/production/docker-compose.yml up -d --build --scale agent=3
python 05-scaling-reliability/production/test_stateless.py
```

Stack mẫu Part5 dùng port8080 và `POST /chat`, **không phải `/ask` port80**. Output nguyên bản: [reports/stateless.txt](reports/stateless.txt). Năm request được chia qua ba instance `instance-627ca1`, `instance-9b9621`, `instance-e5509d`; history vẫn đủ10 messages (user+assistant). Script chỉ chứng minh chia tải và history chung, **không tự kill random instance**. Không tuyên bố đã chạy kịch bản kill nếu chưa chạy.

Lưu state trong RAM sẽ chia thành ba bản riêng và mất khi process chết; Redis dùng chung giúp request tiếp theo đến instance khác vẫn thấy state. Redis cũng cần persistence/backup và HA thực sự; stateless app không đồng nghĩa Redis không thể hỏng. Riêng rate-limit Part6 đã kiểm restart agent vẫn429 bằng checker.

## Part 6: Output check_production_ready.py

**Không sửa checker.** Git blob hiện tại và HEAD cùng `{blob}`. Chạy bản đầy đủ trong Linux container vì Python Windows bỏ qua SIGTERM:

```bash
docker build -f scripts/Dockerfile.checker -t day14-checker:local 06-lab-complete
docker run --name day14-full-check --network host -v "$(pwd -W):/workspace" -v /var/run/docker.sock:/var/run/docker.sock day14-checker:local
```

Runner có Docker CLI và socket để checker build/chạy container thật. Chỉ dùng runner tin cậy trên máy lab; **agent ứng dụng không mount Docker socket**. Linux/WSL đã có Python+dependency thì có thể chạy `python check_production_ready.py` trực tiếp trong `06-lab-complete/`.

Trích nguyên phần checklist từ [output đầy đủ](reports/production-readiness.txt):
```text
{checklist}
```

## AI log — Khai báo hỗ trợ

Có dùng **AI coding assistant (Hermes, profile coder2)** hỗ trợ đọc rubric/hợp đồng, viết Part6, thêm tests, chạy lệnh local, đo benchmark, debug Docker/Jaeger, chụp UI và soạn tài liệu từ JSON/CSV. Các đoạn giải thích và code trong bài có AI hỗ trợ, không khai là tự viết hoàn toàn.

Tất cả số đo và output trong bài lấy từ lệnh/API đã chạy trên máy; không tự đặt số, không dùng đáp án mẫu làm số đo. Lỗi gặp thật: Windows bỏ qua SIGTERM; teardown socket khi restart Python nhanh; thiếu PYTHONUSERBASE ở image Part7; port80 bị từ chối; Jaeger bản này dùng APIv3; Compose run tự đưa replicas về default2 nên phải đo lại với `--no-deps`. Chưa có review/duyệt cuối của Tai hoặc Lab Coach.

## Phần còn thiếu / lưu ý bàn giao

- Cloud deployment, URL public và ba ảnh cloud chưa làm theo yêu cầu; xem DEPLOYMENT.md.
- Chưa commit/push, chưa thay trạng thái public repo hoặc nộp LMS.
- Docker cleanup bị approval policy chặn trong headless session. Không lách policy; danh sách tài nguyên của task và lệnh để người có quyền dừng sẽ nằm trong `reports/cleanup-required.md`. Browser và Python harness có đóng process/context của mình.
'''
    (ROOT / "MISSION_ANSWERS.md").write_text(mission, encoding="utf-8")

    loads = [(c, read(f"load_v2_c{c}.json")) for c in (1, 10, 50, 100)]
    tails = [(slow, read(f"load_v2_slow_{slow}.json")) for slow in ("0", "0.03", "0.1")]
    ev = [read(f"eval_{version}.json") for version in ("v1", "v2", "v2_fixed")]
    for _, row in loads + tails:
        assert row["total_requests"] == 300
    assert ev[2]["passed"] == ev[2]["total"] == 23
    assert ev[2]["quality_gate"]["passed"] and not ev[2]["quality_gate"]["regressions"]
    load_rows = "\n".join(f"| {c} | {r['rps']:.2f} | {r['latency_ms']['p50']:.1f} | {r['latency_ms']['p95']:.1f} | {r['latency_ms']['p99']:.1f} | {100*r['error_rate']:.2f}% | {'PASS' if r['slo']['passed'] else 'FAIL'} |" for c, r in loads)
    tail_rows = "\n".join(f"| {slow} | {r['latency_ms']['avg']:.1f} | {r['latency_ms']['p95']:.1f} | {r['latency_ms']['p99']:.1f} |" for slow, r in tails)
    quality_rows = []
    for label, key, fmt in [("Avg tokens / câu", "avg_tokens", ".1f"), ("Tổng cost (USD)", "total_cost_usd", ".6f"), ("Cost / câu đúng (USD)", "cost_per_correct_usd", ".8f")]:
        quality_rows.append("| " + label + " | " + " | ".join(format(r[key], fmt) for r in ev) + " |")
    scales = []
    ask_scales = []
    for n in (1, 3):
        rows = list(csv.DictReader((csv_out / f"scale_{n}_stats.csv").read_text(encoding="utf-8").splitlines()))
        scales.append((n, next(r for r in rows if r["Name"] == "Aggregated")))
        ask_scales.append((n, next(r for r in rows if r["Name"] == "/ask")))
    def scale_table(rows):
        return "\n".join(f"| {n} | {float(r['Requests/s']):.6f} | {r['50%']} | {r['95%']} | {r['99%']} | {r['Failure Count']}/{r['Request Count']} ({100*int(r['Failure Count'])/int(r['Request Count']):.4f}%) |" for n, r in rows)
    chaos = read("chaos-experiments.json")
    assert {"AgentHighErrorRate", "AgentHighLatencyP95"} <= {a["labels"]["alertname"] for a in chaos["firing_snapshot"]["data"]["alerts"] if a["state"] == "firing"}
    alert_rows = "\n".join(f"| {r['label']} | ERROR={r['config']['MOCK_ERROR_RATE']}, SLOW={r['config']['MOCK_SLOW_RATE']} | {', '.join(r['alerts'])} | {r['elapsed_seconds']:.3f}s | {r['changed_at']} → {r['firing_observed_at']} |" for r in chaos["experiments"])
    snapshot = read("observability-snapshot.json")
    p95_ms = scalar(snapshot, "p95_seconds") * 1000
    avg_ms = scalar(snapshot, "avg_seconds") * 1000
    error_pct = scalar(snapshot, "error_rate") * 100
    rps = scalar(snapshot, "rps")
    per_instance = snapshot["queries"]["per_instance"]["response"]["data"]["result"]
    instance_rows = "\n".join(f"| {r['metric']['instance']} | {float(r['value'][1]):.6f} |" for r in per_instance)
    token_values = {r["metric"]["type"]: float(r["value"][1]) for r in snapshot["queries"]["tokens_per_second"]["response"]["data"]["result"]}
    trace = read("trace-evidence.json")
    s, e = trace["slow"], trace["error"]
    slow_log = next(row for row in s["logs"] if row["event"] == "llm_call")
    error_log = next(row for row in e["logs"] if row["event"] == "llm_error")
    wrong_rows = "\n".join(f"| {r['id']} | {', '.join(r['missing_keywords'])} | {'Thêm tài liệu JWT có chữ ký, user, hạn dùng; ưu tiên khớp keyword JWT' if r['id'] == 'security-02' else 'Thêm tài liệu Kubernetes HPA, CPU/memory/custom metrics; đặt trước mục metric tổng quát'} |" for r in ev[1]["results"] if not r["passed"])
    report = f'''# Benchmark & Observability Report — Day 14

**Họ tên:** Trần Hữu Tài · **MSSV:** 2A202603944  
**Ngày chạy:** 26/11/2026 (UTC+07)  
**Môi trường:** {env['host']}; client Python {env['python_client']}; Docker Engine {env['docker']['version']}, Linux containers, {env['docker']['cpus']} CPU logic, {env['docker']['memory_bytes']} bytes RAM daemon ({env['docker']['memory_bytes']/1024**3:.3f}GiB). Chi tiết: `reports/environment.json`.

Báo cáo theo cấu trúc `BENCHMARK_REPORT_TEMPLATE.md`. Các bảng được sinh trực tiếp từ JSON/CSV bằng `scripts/generate_submission.py`, không chép số đáp án mẫu. Chỉ benchmark mock offline; không suy ra hiệu năng hoặc chi phí API LLM thật.

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng |
|---|---|---|
| p95 latency `/ask` | ≤500ms | Giới hạn trải nghiệm đa số user, không để average che đuôi chậm |
| Error rate `/ask` | ≤2% | Phù hợp kiểm SLO của load_test.py, error budget2% |
| Accuracy golden dataset | ≥85%; gate cuối100% | Không phát hành bản nhanh nhưng sai; bài yêu cầu sửa đủ23/23 |

Phân biệt **SLO load test** với ngưỡng alert mẫu: error>5% kéo dài1m, p95>1s kéo dài2m. Alert không thay thế quality gate.

## 2. Benchmark hiệu năng (develop, load_test.py)

### 2.1 Concurrency vs latency — agent v2

Mỗi mức300 request, `MOCK_SLOW_RATE=0.03`, `MOCK_ERROR_RATE=0.01`; client và agent cùng máy, một process uvicorn. JSON tại `reports/load_v2_c*.json`. Đo trước khi sửa KB.

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---:|---:|---:|---:|---:|---|
{load_rows}

RPS không tăng tuyến tính: tại concurrency100, thông lượng thấp hơn50 và tail latency cao hơn. Đây là đo trên Windows/máy dùng chung, có một số Docker build chạy đồng thời trong đợt develop; gồm scheduling, network/client overhead và jitter ngẫu nhiên. Không thể quy toàn bộ khác biệt cho riêng khả năng scale của app. SLO FAIL được giữ nguyên, không sửa JSON cho đẹp số.

### 2.2 Tail latency

Cùng300 request, concurrency20, error injection0.01; restart v2 để đổi SLOW_RATE. Các file `load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json`.

| MOCK_SLOW_RATE | avg (ms) | p95 (ms) | p99 (ms) |
|---|---:|---:|---:|
{tail_rows}

Ở0.03, p99 tăng rõ trong khi average tăng ít hơn; ở0.1, tỷ lệ slow vượt5% nên p95 cũng đi vào nhóm chậm. Average trộn nhiều request nhanh với nhóm ít request chậm, không mô tả trải nghiệm người nằm ở tail. Dùng p95/p99 cho latency SLO, kết hợp error rate; không bỏ request lỗi khỏi nhận định availability. Mẫu300 và randomness không tạo ra tỷ lệ lỗi/slow chính xác bằng cấu hình.

### 2.3 Metrics — Exercise7.1

- Counter: `http_requests_total`, `llm_tokens_total`, `llm_cost_usd_total` (chỉ tăng; dùng rate trên cửa sổ).
- Gauge: `agent_in_flight_requests` tăng/giảm theo concurrent request.
- Histogram: `http_request_duration_seconds` và metric đã thêm `agent_question_length_chars`, buckets20/50/100/200/500/1000/2000 ký tự; test quan sát count tăng sau request thật.
- Label route dùng template và `unmatched` cho404. Dùng URL thật cho mỗi đường dẫn bot quét tạo series mới, làm cardinality/tốn RAM tăng không giới hạn. Không dùng độ dài câu hỏi làm label.

## 3. Benchmark chất lượng (develop, eval/run_eval.py)

Cùng golden dataset23 câu, threshold keyword0.6; `MOCK_ERROR_RATE=0` để cô lập chất lượng khỏi lỗi upstream. Slow-rate vẫn mặc định0.03. Report gốc có đủ23 kết quả từng câu.

| Chỉ số | Agent v1 | Agent v2 | Agent v2 fixed |
|---|---:|---:|---:|
| Accuracy | {ev[0]['passed']}/{ev[0]['total']} ({100*ev[0]['accuracy']:.2f}%) | {ev[1]['passed']}/{ev[1]['total']} ({100*ev[1]['accuracy']:.2f}%) | {ev[2]['passed']}/{ev[2]['total']} ({100*ev[2]['accuracy']:.2f}%) |
{chr(10).join(quality_rows)}
| Quality gate thực chạy | FAIL (80%) | PASS (80%, baseline v1) | PASS (100%, baseline v2) |

Nguồn lần lượt: `eval_v1.json`, `eval_v2.json`, `eval_v2_fixed.json`. Accuracy phần trăm trên bảng lấy trường accuracy đã làm tròn của JSON; phân số giữ count gốc. Vì JSON làm tròn cost tổng và cost/câu đúng riêng, không chia lại tổng đã làm tròn để thay cost/câu đúng.

### Câu sai ban đầu và cách sửa

| ID | missing_keywords trong eval_v2.json | Thay đổi KB |
|---|---|---|
{wrong_rows}

Đã đồng bộ hai entry sang `production/utils/mock_llm.py`. Không thay dataset, scorer hoặc threshold để đạt điểm. Final gate sửa được2 câu và không có regression.

v2 dùng {ev[1]['avg_tokens']/ev[0]['avg_tokens']:.2f} lần token/câu so với v1 do có retrieval context, nhưng cost trên câu đúng rẻ hơn {ev[0]['cost_per_correct_usd']/ev[1]['cost_per_correct_usd']:.2f} lần; tăng tổng cost có thể đáng đổi lấy chất lượng. Eval23 mẫu không đủ kết luận latency: còn first-connection overhead và tail ngẫu nhiên, nên dùng bảng load300 request cho latency.

### CI quality gate

`run_eval.py` trả exit1 nếu accuracy dưới min hoặc có regression. Đã chạy kiểm ngược v1 với baseline v2: `reports/eval_regression.json`, **FAIL với20 regressions**, không phải chỉ giải thích lý thuyết. Sau khi khởi động agent, job CI dùng:

```bash
python eval/run_eval.py --url http://localhost:8002 --min-accuracy 0.85 --baseline reports/eval_v2.json --out reports/eval_ci.json
```

Đặt step này làm required check của branch protection để chặn merge; không dùng `|| true`, không để lệnh echo cuối che exit code. Với bài nộp final dùng `--min-accuracy 1.0`. Baseline phải là artifact tin cậy của bản trước, không phải file tự hạ chuẩn trong PR. Chưa bật branch protection hoặc push workflow lên GitHub vì không có quyền publish trong task.

## 4. Observability stack (production)

### 4.1 Ảnh và readings thật

- [x] [Grafana có tải](screenshots/grafana-dashboard.png).
- [x] [Jaeger trace chậm](screenshots/jaeger-slow-trace.png).
- [x] [Jaeger trace lỗi, Events exception mở](screenshots/jaeger-error-trace.png).
- [x] [Prometheus có ít nhất2 alert FIRING cùng lúc](screenshots/prometheus-alert-firing.png).

Có thêm bản1280px cạnh mỗi ảnh; ảnh chính2560px. Browser chạy isolated và đóng trong finally. Grafana dùng anonymous Viewer có sẵn cho lab, không đăng nhập cloud.

**Ảnh Grafana là pha chaos B**,30 users,3 agent, error0.2, slow0.3, modelsmall; không phải pha baseline scale. Snapshot API Prometheus ở `{snapshot['captured_at']}`, cửa sổ1m:

| Chỉ số từ API | Giá trị |
|---|---:|
| `/ask` RPS | {rps:.6f} |
| p95 `/ask` (ms) | {p95_ms:.3f} |
| Average `/ask` (ms) | {avg_ms:.3f} |
| Error rate `/ask` | {error_pct:.4f}% |
| Instances up | {scalar(snapshot,'instances_up'):.0f} |
| Input tokens/s | {token_values['input']:.6f} |
| Output tokens/s | {token_values['output']:.6f} |

Nguồn số là `reports/observability-snapshot.json` (có nguyên PromQL và response), không lấy ước lượng từ ảnh. Dashboard refresh5s và chụp sau API vài giây nên con số tức thời trên ảnh có thể hơi khác.

| Instance | `/ask` req/s |
|---|---:|
{instance_rows}

**Exercise7.4:** p95 lớn hơn average cho thấy nhóm request chậm; ở đây injection slow tạo tail rõ rệt. Traffic ba instance gần nhau nhưng không bắt buộc bằng tuyệt đối do cửa sổ lấy mẫu và request duration; không dựa vào số instance đơn thuần để kết luận LB. Input tokens cao hơn output do prompt gồm system instruction, câu hỏi và retrieval context, trong khi output chỉ câu trả lời ngắn. Biểu đồ tokens có thể stack nên không đọc độ cao đường cộng dồn thành giá trị riêng. `curl http://localhost:18080/metrics` trả404 do Nginx chặn; Prometheus scrape agent trong mạng Docker, tránh lộ metrics public.

Port chuẩn8080 đang thuộc stack Part5, nên dùng override `scripts/compose.obs-ports.yml` để Nginx obs ở18080. Project là `k5-day14-observability`, tách khỏi hai stack cũng có thư mục tênproduction. Sửa `PYTHONUSERBASE=/home/agent/.local` trong Dockerfile Part7 vì user có home `/app` nhưng dependency được copy sang `/home/agent/.local`; trước sửa container thực sự crash với ModuleNotFoundError uvicorn, sau sửa chạy healthy.

### 4.2 Thí nghiệm phá hệ thống

| # | Cấu hình thực áp dụng | Alert FIRING được quan sát | Thời gian từ đổi cấu hình | Mốc UTC thay đổi → phát hiện |
|---|---|---|---:|---|
{alert_rows}

A tăng riêng error-rate từ mặc định; B tiếp tục giữ error0.2 và tăng slow lên0.3 để cả hai alert đồng thời firing. Không gọi hai thay đổi đồng thời là hai phép thử độc lập. Đo bằng monotonic clock từ trước lệnh composeup, poll API5s/lần; thời gian bao gồm recreate/startup/ramp-up và có độ phân giải quan sát5s, không chỉ riêng tham số `for`.

Raw observations và timestamps: `reports/chaos-experiments.json`. Unit test alert rules bằng image Prometheus của đề bài: **SUCCESS** (output thật trong `reports/alert-rules-tests.txt`). Không sửa alert thresholds hay giảm `for` để ép firing.

- C (model large) và D (pause instance) **chưa chạy**; không có số đo hay ảnh giả cho hai mục này.
- E đổi sangv1: phân tích từ source và eval regression thực chạy; **chưa chạy chaos E trên stack**. Metric hạ tầng không đo tính đúng ngữ nghĩa nên có thể vẫn xanh khi chất lượng giảm; phát hiện bằng golden eval/quality gate, canary đánh giá câu trả lời, feedback và production quality monitoring.
- Với D về lý thuyết: pause giữ target trong DNS nên up=0 có thể cảnh báo; stop có thể làm target biến khỏi discovery. Lỗi504 do Nginx timeout không nhất thiết đi vào counter5xx của agent, nên cần thêm metrics/synthetic check tại gateway. Không ghi đây là kết quả thực nghiệm đã chạy.

### 4.3 Debug bằng trace

Trace chậm nhất **trong {trace['slow_candidates']} candidates đã truy vấn** (không khẳng định chậm nhất toàn bộ lịch sử):

- trace_id: `{s['trace_id']}`.
- Tổng thời gian: **{s['root_ms']:.3f}ms**.
- Span chậm nhất: `{s['llm_span']}`, **{s['llm_ms']:.3f}ms**, chiếm **{100*s['llm_fraction']:.2f}%** root duration.
- LLM là nút chậm chính, không phải chỉ bước retrieve; trace này thuộc benchmark baseline trước chaos.

Dòng log JSON có cùng trace_id:
```json
{json.dumps(slow_log,ensure_ascii=False,indent=2)}
```

Trace lỗi: `{e['trace_id']}`, HTTP503; LLM span `{e['llm_span']}` có event `exception`, `exception.type=utils.mock_llm.LLMError`, upstream unavailable mock. Root duration **{e['root_ms']:.3f}ms**. Log khớp:
```json
{json.dumps(error_log,ensure_ascii=False,indent=2)}
```

Bằng chứng backend gốc: `reports/jaeger-slow-raw.json`, `reports/jaeger-error-raw.json` (APIv3/OTLP); bản chọn/chuẩn hoá tại `jaeger-*-trace.json`, tổng hợp/link log tại `trace-evidence.json`. Jaeger2.23 trên máy này không có legacy `/api/traces`; dùng QueryService APIv3 và mở chính trace đó trong UI. Các log đã lưu trước recreate container, không giả dựng lại từ screenshot.

## 5. Benchmark scaling (production, Locust headless,100 users,2 phút)

Cùng mocksmall, v2 fixedKB, slow0.03, error0.01; mỗi agent giới hạn0.5CPU/256MiB như compose mẫu. Wait time0.5–2s/user; đây là closed-loop user workload, không phải phát request không nghỉ.

Bảng theo dòng **Aggregated** của CSV (gồm `/ask` và `/health`):

| Instance | RPS | p50(ms) | p95(ms) | p99(ms) | Failures / requests (error rate) |
|---|---:|---:|---:|---:|---|
{scale_table(scales)}

Riêng **POST /ask** để đối chiếu SLO của agent:

| Instance | `/ask` RPS | p50(ms) | p95(ms) | p99(ms) | Failures / requests (error rate) |
|---|---:|---:|---:|---:|---|
{scale_table(ask_scales)}

Nguồn `benchmark-results/scale_1_stats.csv`, `scale_3_stats.csv`, không dùng số ở console thay cho CSV snapshot. CSV của Locust là snapshot định kỳ, có thể khác tổng cuối stdout một ít do thời điểm flush; báo cáo nhất quán lấy CSV.

**Nhận xét:** p95 không cải thiện khi tăng1→3 instance, thông lượng gần nhau. Kết quả phù hợp giả thuyết100 users có think time chưa đủ bão hoà một instance và mockawait/tail đang chi phối, nhưng chưa có CPU sampling để khẳng định nút nghẽn. Thêm replica không làm mỗi LLM call nhanh hơn. Muốn kết luận capacity scaling phải tăng offered load/duration, kiểm resource saturation và lặp lại nhiều lần; không khẳng định “3 lần replica thì3 lần RPS”.

Lệnh thực dùng `compose run --no-deps` để giữ replica đã scale; nếu bỏ flag này, Compose run kéo dependency agent về `deploy.replicas:2`. Lượt bị ảnh hưởng đã được tách vào `reports/invalid-scale-2/`, **loại khỏi bảng**, sau đó đo lại đủ2 phút với1 và3 instance. Các file `reports/scale-1-containers.txt`, `scale-3-containers.txt` ghi trạng thái trước lượt hợp lệ. Exit1 của Locust do503 mô phỏng được giữ trong log, không tuyên bố load không có lỗi.

## 6. Kết luận

1. Percentile và error-rate phản ánh trải nghiệm khác nhau; average xanh không chứng minh tail tốt. Giữ cả lượt SLO FAIL và điều kiện chạy để tránh kết luận quá mức.
2. Eval bắt lỗi chất lượng mà latency/availability không bắt; so cost/câu đúng công bằng hơn chỉ cost/câu. KB phải sửa dựa trên missing_keywords mà không sửa bộ chấm.
3. Metrics chỉ chỗ có vấn đề; trace chỉ span gây chậm/lỗi; log có trace_id làm bằng chứng nối hai phía. Alert cần kéo dài đủ lâu để tránh spike, nhưng for quá lâu làm chậm phát hiện.

Production thật nên thêm metrics upstream latency/timeout/retry, queue depth, CPU/memory, gateway504, Redis availability, cost reservation/usage thực và chất lượng câu trả lời theo dataset/version. Sampling trace cần cân bằng chi phí với khả năng giữ được lỗi/tail hiếm.

**Giới hạn và bàn giao:** một máy dùng chung, mock thay provider thật,300 request/load và23 eval chưa đại diện traffic thật; không có deploy cloud. Docker cleanup bị approval policy chặn, không lách; xem `reports/cleanup-required.md`. Cleanup ban đầu gọi GET `/stop` bị405 nên dừng trước bước restore. Đã sửa sang POST, thêm2 regression test (kể cả stop lỗi vẫn restore), rồi chạy `scripts/recover_chaos.py` thật: Locust state=stopped/user_count=0; cả3 agent đã về error0.01/slow0.03/modelsmall. Bằng chứng recovery nằm trong `reports/chaos-experiments.json`; stack services vẫn cần người có quyền dừng. Chưa commit/push/nộp LMS.
'''
    (ROOT / "BENCHMARK_REPORT.md").write_text(report, encoding="utf-8")
    print(json.dumps({"mission_written": True, "benchmark_written": True, "grader_unchanged": blob, "load_reports": len(loads)+len(tails), "eval_fixed": ev[2]["passed"], "scale_rows": len(scales), "alerts": [r["label"] for r in chaos["experiments"]]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
