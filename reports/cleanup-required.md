# Cleanup cần người có quyền thực hiện

Locust load đã xác minh stopped / 0 users; fault config của 3 agent đã về mặc định. Browser context đóng. Docker compose down bị approval policy từ chối trong headless session; không lách bằng interpreter hoặc scale-to-zero.

Còn **20 container của task đang chạy** tại 2026-11-26T16:02:21.568850+00:00. Không dừng Docker Desktop, threadrop-db hoặc bất kỳ container/PID nào ngoài danh sách.

| Container | ID | State |
|---|---|---|
| k5-day14-observability-agent-2 | 6d75d727698e | running |
| k5-day14-observability-agent-3 | ee0b4e527f5d | running |
| k5-day14-observability-agent-1 | a3b59626606e | running |
| day14-scale-3-verified | 504d72d1df48 | exited |
| day14-scale-1-verified | ee7c2eb0b06e | exited |
| day14-scale-1 | 7413cf2a8f8d | exited |
| day14-alert-unit-tests | beac1a1a9a8f | exited |
| k5-day14-observability-locust-1 | 4ec8bde34c29 | running |
| k5-day14-observability-nginx-1 | c31e2eb0cc2f | running |
| k5-day14-observability-grafana-1 | cc31044032d5 | running |
| k5-day14-observability-jaeger-1 | eba5c78449f8 | running |
| k5-day14-observability-prometheus-1 | f40dc36babb1 | running |
| k5-day14-docker-nginx-1 | e1d112fb760f | running |
| k5-day14-docker-agent-1 | 566c27822be3 | running |
| k5-day14-docker-qdrant-1 | 997e6877f5eb | running |
| k5-day14-docker-redis-1 | c023542185df | running |
| k5-day14-scaling-nginx-1 | 2e2c38c89c1d | running |
| k5-day14-scaling-agent-1 | efc74b7384fb | running |
| k5-day14-scaling-agent-2 | 3c603e85b6e0 | running |
| k5-day14-scaling-agent-3 | 1e51a3c76b06 | running |
| k5-day14-scaling-redis-1 | e5257eba2148 | running |
| day14-part2-production | 4bc701c5a9b7 | running |
| day14-part2-develop | eb473639e5ac | running |
| day14-full-check | 66c3770b7ca3 | exited |
| day14-hostnet-probe | a16308df16bd | exited |
| day14-test-redis | fd90f9719cbe | running |

Người có quyền có thể dừng đúng các container đang chạy bằng lệnh sau (chưa chạy thành công trong task):

```bash
docker stop k5-day14-observability-agent-2 k5-day14-observability-agent-3 k5-day14-observability-agent-1 k5-day14-observability-locust-1 k5-day14-observability-nginx-1 k5-day14-observability-grafana-1 k5-day14-observability-jaeger-1 k5-day14-observability-prometheus-1 k5-day14-docker-nginx-1 k5-day14-docker-agent-1 k5-day14-docker-qdrant-1 k5-day14-docker-redis-1 k5-day14-scaling-nginx-1 k5-day14-scaling-agent-1 k5-day14-scaling-agent-2 k5-day14-scaling-agent-3 k5-day14-scaling-redis-1 day14-part2-production day14-part2-develop day14-test-redis
```

Không dùng prune, down -v, xóa volume hoặc kill toàn bộ node/chrome. Không xóa dữ liệu. Container đã exit không cần kill. Giữ Redis volumes nếu còn cần kiểm thử lại.

Sau cleanup: kiểm docker ps chỉ còn các service vốn có, rồi trả task về coder2 để gửi techlead review. Cloud URL và ba ảnh cloud vẫn chủ động chưa làm theo yêu cầu; không phải lý do block.
