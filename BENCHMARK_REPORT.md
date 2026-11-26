# Benchmark & Observability Report — Day 14

**Họ tên:** Trần Hữu Tài · **MSSV:** 2A202603944  
**Ngày chạy:** 26/11/2026 (UTC+07)  
**Môi trường:** Windows-10-10.0.26200-SP0; client Python 3.11.9; Docker Engine 29.1.3, Linux containers, 24 CPU logic, 4103053312 bytes RAM daemon (3.821GiB). Chi tiết: `reports/environment.json`.

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
| 1 | 4.59 | 201.4 | 232.9 | 1659.1 | 0.67% | PASS |
| 10 | 35.45 | 188.8 | 442.4 | 1693.1 | 1.67% | PASS |
| 50 | 106.45 | 198.7 | 521.3 | 1669.2 | 0.33% | FAIL |
| 100 | 48.78 | 660.1 | 3874.3 | 4224.6 | 0.67% | FAIL |

RPS không tăng tuyến tính: tại concurrency100, thông lượng thấp hơn50 và tail latency cao hơn. Đây là đo trên Windows/máy dùng chung, có một số Docker build chạy đồng thời trong đợt develop; gồm scheduling, network/client overhead và jitter ngẫu nhiên. Không thể quy toàn bộ khác biệt cho riêng khả năng scale của app. SLO FAIL được giữ nguyên, không sửa JSON cho đẹp số.

### 2.2 Tail latency

Cùng300 request, concurrency20, error injection0.01; restart v2 để đổi SLOW_RATE. Các file `load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json`.

| MOCK_SLOW_RATE | avg (ms) | p95 (ms) | p99 (ms) |
|---|---:|---:|---:|
| 0 | 210.6 | 467.5 | 475.0 |
| 0.03 | 261.8 | 471.0 | 1708.2 |
| 0.1 | 364.9 | 1694.0 | 1724.8 |

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
| Accuracy | 1/23 (4.35%) | 21/23 (91.30%) | 23/23 (100.00%) |
| Avg tokens / câu | 56.7 | 108.8 | 113.7 |
| Tổng cost (USD) | 0.000399 | 0.000757 | 0.000790 |
| Cost / câu đúng (USD) | 0.00039855 | 0.00003607 | 0.00003436 |
| Quality gate thực chạy | FAIL (80%) | PASS (80%, baseline v1) | PASS (100%, baseline v2) |

Nguồn lần lượt: `eval_v1.json`, `eval_v2.json`, `eval_v2_fixed.json`. Accuracy phần trăm trên bảng lấy trường accuracy đã làm tròn của JSON; phân số giữ count gốc. Vì JSON làm tròn cost tổng và cost/câu đúng riêng, không chia lại tổng đã làm tròn để thay cost/câu đúng.

### Câu sai ban đầu và cách sửa

| ID | missing_keywords trong eval_v2.json | Thay đổi KB |
|---|---|---|
| security-02 | token, hết hạn, chữ ký | Thêm tài liệu JWT có chữ ký, user, hạn dùng; ưu tiên khớp keyword JWT |
| scaling-03 | cpu, memory, custom metrics | Thêm tài liệu Kubernetes HPA, CPU/memory/custom metrics; đặt trước mục metric tổng quát |

Đã đồng bộ hai entry sang `production/utils/mock_llm.py`. Không thay dataset, scorer hoặc threshold để đạt điểm. Final gate sửa được2 câu và không có regression.

v2 dùng 1.92 lần token/câu so với v1 do có retrieval context, nhưng cost trên câu đúng rẻ hơn 11.05 lần; tăng tổng cost có thể đáng đổi lấy chất lượng. Eval23 mẫu không đủ kết luận latency: còn first-connection overhead và tail ngẫu nhiên, nên dùng bảng load300 request cho latency.

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

**Ảnh Grafana là pha chaos B**,30 users,3 agent, error0.2, slow0.3, modelsmall; không phải pha baseline scale. Snapshot API Prometheus ở `2026-11-26T15:50:43.902338+00:00`, cửa sổ1m:

| Chỉ số từ API | Giá trị |
|---|---:|
| `/ask` RPS | 15.800769 |
| p95 `/ask` (ms) | 1885.053 |
| Average `/ask` (ms) | 547.927 |
| Error rate `/ask` | 20.9436% |
| Instances up | 3 |
| Input tokens/s | 967.447101 |
| Output tokens/s | 504.479115 |

Nguồn số là `reports/observability-snapshot.json` (có nguyên PromQL và response), không lấy ước lượng từ ảnh. Dashboard refresh5s và chụp sau API vài giây nên con số tức thời trên ảnh có thể hơi khác.

| Instance | `/ask` req/s |
|---|---:|
| 172.25.0.5:8000 | 5.291198 |
| 172.25.0.8:8000 | 5.400295 |
| 172.25.0.9:8000 | 5.109277 |

**Exercise7.4:** p95 lớn hơn average cho thấy nhóm request chậm; ở đây injection slow tạo tail rõ rệt. Traffic ba instance gần nhau nhưng không bắt buộc bằng tuyệt đối do cửa sổ lấy mẫu và request duration; không dựa vào số instance đơn thuần để kết luận LB. Input tokens cao hơn output do prompt gồm system instruction, câu hỏi và retrieval context, trong khi output chỉ câu trả lời ngắn. Biểu đồ tokens có thể stack nên không đọc độ cao đường cộng dồn thành giá trị riêng. `curl http://localhost:18080/metrics` trả404 do Nginx chặn; Prometheus scrape agent trong mạng Docker, tránh lộ metrics public.

Port chuẩn8080 đang thuộc stack Part5, nên dùng override `scripts/compose.obs-ports.yml` để Nginx obs ở18080. Project là `k5-day14-observability`, tách khỏi hai stack cũng có thư mục tênproduction. Sửa `PYTHONUSERBASE=/home/agent/.local` trong Dockerfile Part7 vì user có home `/app` nhưng dependency được copy sang `/home/agent/.local`; trước sửa container thực sự crash với ModuleNotFoundError uvicorn, sau sửa chạy healthy.

### 4.2 Thí nghiệm phá hệ thống

| # | Cấu hình thực áp dụng | Alert FIRING được quan sát | Thời gian từ đổi cấu hình | Mốc UTC thay đổi → phát hiện |
|---|---|---|---:|---|
| A | ERROR=0.2, SLOW=0.03 | AgentHighErrorRate | 86.703s | 2026-11-26T15:46:13.088248+00:00 → 2026-11-26T15:47:39.788016+00:00 |
| B | ERROR=0.2, SLOW=0.3 | AgentHighErrorRate, AgentHighLatencyP95 | 152.109s | 2026-11-26T15:47:39.789518+00:00 → 2026-11-26T15:50:11.900278+00:00 |

A tăng riêng error-rate từ mặc định; B tiếp tục giữ error0.2 và tăng slow lên0.3 để cả hai alert đồng thời firing. Không gọi hai thay đổi đồng thời là hai phép thử độc lập. Đo bằng monotonic clock từ trước lệnh composeup, poll API5s/lần; thời gian bao gồm recreate/startup/ramp-up và có độ phân giải quan sát5s, không chỉ riêng tham số `for`.

Raw observations và timestamps: `reports/chaos-experiments.json`. Unit test alert rules bằng image Prometheus của đề bài: **SUCCESS** (output thật trong `reports/alert-rules-tests.txt`). Không sửa alert thresholds hay giảm `for` để ép firing.

- C (model large) và D (pause instance) **chưa chạy**; không có số đo hay ảnh giả cho hai mục này.
- E đổi sangv1: phân tích từ source và eval regression thực chạy; **chưa chạy chaos E trên stack**. Metric hạ tầng không đo tính đúng ngữ nghĩa nên có thể vẫn xanh khi chất lượng giảm; phát hiện bằng golden eval/quality gate, canary đánh giá câu trả lời, feedback và production quality monitoring.
- Với D về lý thuyết: pause giữ target trong DNS nên up=0 có thể cảnh báo; stop có thể làm target biến khỏi discovery. Lỗi504 do Nginx timeout không nhất thiết đi vào counter5xx của agent, nên cần thêm metrics/synthetic check tại gateway. Không ghi đây là kết quả thực nghiệm đã chạy.

### 4.3 Debug bằng trace

Trace chậm nhất **trong 200 candidates đã truy vấn** (không khẳng định chậm nhất toàn bộ lịch sử):

- trace_id: `d61c7f17ee042fdcdbb90a064576ba6e`.
- Tổng thời gian: **1753.534ms**.
- Span chậm nhất: `chat mock-llm-small`, **1677.802ms**, chiếm **95.68%** root duration.
- LLM là nút chậm chính, không phải chỉ bước retrieve; trace này thuộc benchmark baseline trước chaos.

Dòng log JSON có cùng trace_id:
```json
{
  "ts": "2026-11-26T15:42:45.834822+00:00",
  "level": "INFO",
  "service": "observable-agent",
  "instance": "6b7a979671fa",
  "event": "llm_call",
  "trace_id": "d61c7f17ee042fdcdbb90a064576ba6e",
  "span_id": "997e5bb0968df57e",
  "request_id": "a5c01dae3fa2",
  "model": "mock-llm-small",
  "agent_version": "v2",
  "input_tokens": 74,
  "output_tokens": 37,
  "cost_usd": 3.3e-05,
  "llm_ms": 1678.3
}
```

Trace lỗi: `99ea639c53e3ec6f704ce9bc735a975b`, HTTP503; LLM span `chat mock-llm-small` có event `exception`, `exception.type=utils.mock_llm.LLMError`, upstream unavailable mock. Root duration **98.086ms**. Log khớp:
```json
{
  "ts": "2026-11-26T15:43:06.333063+00:00",
  "level": "INFO",
  "service": "observable-agent",
  "instance": "6b7a979671fa",
  "event": "llm_error",
  "trace_id": "99ea639c53e3ec6f704ce9bc735a975b",
  "span_id": "b5e6a154b7ea7002",
  "request_id": "240695003afe",
  "error": "Upstream LLM error: 503 Service Unavailable (mock)"
}
```

Bằng chứng backend gốc: `reports/jaeger-slow-raw.json`, `reports/jaeger-error-raw.json` (APIv3/OTLP); bản chọn/chuẩn hoá tại `jaeger-*-trace.json`, tổng hợp/link log tại `trace-evidence.json`. Jaeger2.23 trên máy này không có legacy `/api/traces`; dùng QueryService APIv3 và mở chính trace đó trong UI. Các log đã lưu trước recreate container, không giả dựng lại từ screenshot.

## 5. Benchmark scaling (production, Locust headless,100 users,2 phút)

Cùng mocksmall, v2 fixedKB, slow0.03, error0.01; mỗi agent giới hạn0.5CPU/256MiB như compose mẫu. Wait time0.5–2s/user; đây là closed-loop user workload, không phải phát request không nghỉ.

Bảng theo dòng **Aggregated** của CSV (gồm `/ask` và `/health`):

| Instance | RPS | p50(ms) | p95(ms) | p99(ms) | Failures / requests (error rate) |
|---|---:|---:|---:|---:|---|
| 1 | 66.005010 | 190 | 220 | 1700 | 63/7878 (0.7997%) |
| 3 | 66.109055 | 190 | 220 | 1700 | 61/7886 (0.7735%) |

Riêng **POST /ask** để đối chiếu SLO của agent:

| Instance | `/ask` RPS | p50(ms) | p95(ms) | p99(ms) | Failures / requests (error rate) |
|---|---:|---:|---:|---:|---|
| 1 | 59.779861 | 190 | 220 | 1700 | 63/7135 (0.8830%) |
| 3 | 60.232508 | 190 | 220 | 1700 | 61/7185 (0.8490%) |

Nguồn `benchmark-results/scale_1_stats.csv`, `scale_3_stats.csv`, không dùng số ở console thay cho CSV snapshot. CSV của Locust là snapshot định kỳ, có thể khác tổng cuối stdout một ít do thời điểm flush; báo cáo nhất quán lấy CSV.

**Nhận xét:** p95 không cải thiện khi tăng1→3 instance, thông lượng gần nhau. Kết quả phù hợp giả thuyết100 users có think time chưa đủ bão hoà một instance và mockawait/tail đang chi phối, nhưng chưa có CPU sampling để khẳng định nút nghẽn. Thêm replica không làm mỗi LLM call nhanh hơn. Muốn kết luận capacity scaling phải tăng offered load/duration, kiểm resource saturation và lặp lại nhiều lần; không khẳng định “3 lần replica thì3 lần RPS”.

Lệnh thực dùng `compose run --no-deps` để giữ replica đã scale; nếu bỏ flag này, Compose run kéo dependency agent về `deploy.replicas:2`. Lượt bị ảnh hưởng đã được tách vào `reports/invalid-scale-2/`, **loại khỏi bảng**, sau đó đo lại đủ2 phút với1 và3 instance. Các file `reports/scale-1-containers.txt`, `scale-3-containers.txt` ghi trạng thái trước lượt hợp lệ. Exit1 của Locust do503 mô phỏng được giữ trong log, không tuyên bố load không có lỗi.

## 6. Kết luận

1. Percentile và error-rate phản ánh trải nghiệm khác nhau; average xanh không chứng minh tail tốt. Giữ cả lượt SLO FAIL và điều kiện chạy để tránh kết luận quá mức.
2. Eval bắt lỗi chất lượng mà latency/availability không bắt; so cost/câu đúng công bằng hơn chỉ cost/câu. KB phải sửa dựa trên missing_keywords mà không sửa bộ chấm.
3. Metrics chỉ chỗ có vấn đề; trace chỉ span gây chậm/lỗi; log có trace_id làm bằng chứng nối hai phía. Alert cần kéo dài đủ lâu để tránh spike, nhưng for quá lâu làm chậm phát hiện.

Production thật nên thêm metrics upstream latency/timeout/retry, queue depth, CPU/memory, gateway504, Redis availability, cost reservation/usage thực và chất lượng câu trả lời theo dataset/version. Sampling trace cần cân bằng chi phí với khả năng giữ được lỗi/tail hiếm.

**Giới hạn và bàn giao:** một máy dùng chung, mock thay provider thật,300 request/load và23 eval chưa đại diện traffic thật; không có deploy cloud. Docker cleanup bị approval policy chặn, không lách; xem `reports/cleanup-required.md`. Cleanup ban đầu gọi GET `/stop` bị405 nên dừng trước bước restore. Đã sửa sang POST, thêm2 regression test (kể cả stop lỗi vẫn restore), rồi chạy `scripts/recover_chaos.py` thật: Locust state=stopped/user_count=0; cả3 agent đã về error0.01/slow0.03/modelsmall. Bằng chứng recovery nằm trong `reports/chaos-experiments.json`; stack services vẫn cần người có quyền dừng. Chưa commit/push/nộp LMS.
