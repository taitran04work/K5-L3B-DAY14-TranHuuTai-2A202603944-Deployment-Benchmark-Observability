# Deployment Information — Day 14

## Public URL


## Trạng thái

**Chưa deploy cloud theo yêu cầu của Tai.** Chưa đăng nhập Railway/Render, chưa tạo tài nguyên cloud, chưa commit/push. URL ở trên chủ động để trống, không phải bằng chứng deploy thành công. `PASS 12/12` local chỉ xác nhận cấu hình sẵn sàng deploy, không xác nhận có URL public.

## Nền tảng dự kiến và build context

Chọn Railway **hoặc** Render bằng tài khoản của Tai sau khi Tai duyệt:

- Railway: đặt **Root Directory = `/06-lab-complete`**; dùng `railway.toml` và Dockerfile trong thư mục đó. Tạo Redis riêng trên nền tảng, nối biến `REDIS_URL` vào agent. Không dùng URL Redis `localhost` trên cloud.
- Render: chọn Blueprint `06-lab-complete/render.yaml` trong repo; `rootDir: 06-lab-complete`, Dockerfile `./Dockerfile`. Tự cấp Redis và điền `REDIS_URL` qua dashboard; Blueprint chưa tự tạo Redis. `AGENT_API_KEY` dùng `generateValue`, không đưa giá trị vào Git.
- Không public cổng Redis; dùng mạng private/TLS theo dịch vụ Redis thực tế. Đợi `/ready` trả 200 trước khi nhận traffic.

## Biến môi trường cần đặt (CHƯA đặt trên cloud)

| Biến | Giá trị/cách đặt |
|---|---|
| `PORT` | Dùng port nền tảng cấp; mặc định local 8000 |
| `ENVIRONMENT` | `production` |
| `AGENT_API_KEY` | Secret ngẫu nhiên đủ mạnh do Tai tạo trên dashboard, không dán vào tài liệu |
| `REDIS_URL` | Connection URL của Redis cloud, không ghi credential vào repo |
| `RATE_LIMIT_PER_MINUTE` | `10` |
| `DAILY_BUDGET_USD` | `1` (có thể thay theo ngân sách thực tế) |
| `MONTHLY_BUDGET_USD` | `10` |
| `PRICE_INPUT_PER_1K` | `0.00015` — giá mô phỏng của lab, không phải báo giá API hiện hành |
| `PRICE_OUTPUT_PER_1K` | `0.0006` — giá mô phỏng của lab |
| `LOG_LEVEL` | `INFO` |

## Lệnh test sau khi Tai deploy

Chạy trong Bash. Nhập key tại máy, không dùng `set -x`, không chụp terminal có giá trị key. Những lệnh dưới đây chưa chạy trên cloud vì chưa có URL.

```bash
BASE=''  # Tai điền URL HTTPS sau khi deploy, không kèm dấu / cuối
: "${BASE:?Chưa điền URL public}"
read -rsp 'API key (hidden): ' AGENT_API_KEY; printf '\n'
export AGENT_API_KEY

curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"  # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"   # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' -d '{"question":"Hello"}' # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"question":"Hello"}' # 200

# Cần Linux/WSL hoặc Linux runner có Docker cho kiểm tra SIGTERM đầy đủ.
cd 06-lab-complete
python check_production_ready.py --public-url "$BASE"
unset AGENT_API_KEY
```

## Bằng chứng local và cloud còn thiếu

- Local: [output checker đầy đủ](reports/production-readiness.txt), [bài trả lời](MISSION_ANSWERS.md), [benchmark](BENCHMARK_REPORT.md).
- Chưa có `screenshots/dashboard.png`, `screenshots/running.png`, `screenshots/test.png`: đây là ảnh **cloud**, không dùng ảnh local thay thế.
- Sau khi Tai deploy: điền URL, chụp ba ảnh cloud không lộ key/token và chạy bốn lệnh tự kiểm trên. Tình trạng public của repo và nộp link LMS do Tai quyết định; agent không tự publish.
