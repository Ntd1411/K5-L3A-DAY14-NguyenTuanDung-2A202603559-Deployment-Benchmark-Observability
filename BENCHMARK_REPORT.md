# Benchmark & Observability Report — Day 14

**Họ tên:** Nguyen Tuan Dung (2A202603559)  
**Ngày chạy:** 2026-11-25  
**Môi trường:** Linux 7.3.4-1-cachyos x86_64, 8 CPU cores, 11 GiB RAM, Python 3.11.18 (`.venv`), Docker 29.10.0 / Docker Compose 5.8.0

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Latency cơ bản của mock LLM + retrieval là ~150–250 ms; ngưỡng p95 ≤ 500 ms đảm bảo 95% người dùng nhận phản hồi nhanh ngay cả khi có ~3% request slow tail (~1.7 s). |
| Error rate `/ask` | < 2 % | Mock LLM mặc định có `MOCK_ERROR_RATE=0.01` (1% lỗi upstream 503); đặt error budget 2% để cho phép nhiễu tạm thời mà vẫn chặn suy giảm hệ thống rõ rệt. |
| Accuracy trên golden dataset | ≥ 85 % (mục tiêu sau sửa KB: 100 %) | Quality gate trong CI ([`.github/workflows/eval.yml`](.github/workflows/eval.yml)) chặn merge nếu accuracy < 85% hoặc có câu nào bị regression so với baseline. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2, `--requests 300`, `MOCK_SLOW_RATE=0.03`)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.12 | 194.5 | 224.1 | 1701.2 | 0.00% | ✅ PASS |
| 10 | 34.61 | 196.3 | 230.6 | 1697.3 | 0.67% | ✅ PASS |
| 50 | 97.09 | 205.3 | 441.4 | 1729.2 | 2.00% | ✅ PASS |
| 100 | 42.06 | 783.2 | 4698.0 | 5241.8 | 2.00% | ❌ FAIL |

**Nhận xét:** RPS có tăng tuyến tính theo concurrency không? Vì sao?

RPS **không tăng tuyến tính** theo concurrency:
- Từ `concurrency=1` → `10` → `50`, RPS tăng gần tuyến tính (`4.12` → `34.61` → `97.09 req/s`) vì agent chạy FastAPI async (`asyncio.sleep` trong mock LLM/retrieval không block event loop), nhiều request chờ I/O song song hiệu quả.
- Đến `concurrency=100`, RPS **tụt mạnh xuống `42.06 req/s`** và `p50`/`p95` nhảy vọt (`783.2 ms` / `4698.0 ms`, vi phạm SLO) vì một process uvicorn duy nhất bị bão hoà hàng đợi socket/event-loop scheduling và overhead context-switch, làm latency xếp hàng cộng dồn vào mọi request.

### 2.2 Tail latency (`--requests 300 --concurrency 20`)

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 202.2 | 273.6 | 318.9 |
| 0.03 (mặc định) | 220.1 | 237.9 | 1677.6 |
| 0.1 | 367.4 | 1699.3 | 1714.4 |

**Nhận xét:** Chỉ số nào nhạy nhất với request chậm? Vì sao SLO không nên đặt theo average?

- **`p99` nhạy nhất trước tiên**, sau đó đến **`p95`** khi tỉ lệ chậm vượt quá 5%: ở `MOCK_SLOW_RATE=0.03` (3% request chậm), `avg` chỉ nhích nhẹ từ `202.2 ms` lên `220.1 ms` (+17.9 ms) nhưng **`p99` tăng vọt hơn 5 lần lên `1677.6 ms`**. Khi `MOCK_SLOW_RATE=0.1` (10% > 5% request chậm), cả `p95` cũng nhảy lên `1699.3 ms` (fail SLO 500 ms) trong khi `avg` mới là `367.4 ms` (vẫn dưới 500 ms).
- Không đặt SLO theo `average` vì trung bình cộng **che giấu nhóm người dùng ở đuôi phân phối (tail latency)** — hệ thống nhìn có vẻ ổn theo `avg` nhưng thực tế 5–10% người dùng đang phải chờ ~1.7 giây.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | 100.0% (23/23) |
| Avg tokens / câu | 57.3 | 109.0 | 113.7 |
| Tổng cost (USD) | $0.000407 | $0.000759 | $0.000790 |
| Cost / câu đúng (USD) | $0.00040695 | $0.00003616 | $0.00003436 |
| Quality gate | ❌ FAIL | ✅ PASS (`≥ 80%`) | ✅ PASS (`≥ 100%`, 0 regression) |

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02` | `token`, `hết hạn`, `chữ ký` | Bổ sung entry `(["jwt"], ...)` vào `KNOWLEDGE_BASE` trong `develop/utils/mock_llm.py` (và đồng bộ sang `production/utils/mock_llm.py`). |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Bổ sung entry `(["hpa", "kubernetes", "autoscal"], ...)` vào `KNOWLEDGE_BASE` trong `develop/utils/mock_llm.py` (và đồng bộ sang `production/utils/mock_llm.py`). |

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**

- **Chất lượng vs Chi phí & Latency:** Agent v2 thêm bước retrieval (RAG) đưa tài liệu vào prompt nên `avg tokens/câu` gần gấp đôi (`57.3` → `109.0–113.7`), `p95 latency` tăng nhẹ (`193.2 ms` → `213.1–223.3 ms`) và tổng chi phí cho 23 câu tăng từ `$0.000407` lên `$0.000790`. Đổi lại, **accuracy tăng từ `4.3%` lên `100.0%`** và **`cost / câu đúng` giảm gần 12 lần** (`$0.00040695` → `$0.00003436`), chứng minh đầu tư retrieval rất hiệu quả.
- **CI Quality Gate (Exercise 7.3):** Đã tạo [`.github/workflows/eval.yml`](.github/workflows/eval.yml) chạy `python eval/run_eval.py --url http://localhost:8000 --min-accuracy 0.85` trên mỗi `pull_request`. Khi kiểm thử chạy v1 đối chiếu `--baseline reports/eval_v2.json`, `run_eval.py` phát hiện accuracy dưới ngưỡng và 20 câu bị regression rồi thoát với **exit code `1`**, giúp GitHub Actions chặn merge tự động.

---

## 4. Observability stack (production)

### 4.1 Screenshot & Quan sát Dashboard (Exercise 7.4)

- [x] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals): [`screenshots/grafana-dashboard.png`](screenshots/grafana-dashboard.png) (`16.5 req/s`, error rate `0.77%`, p95 `292.48 ms`, saturation `4` in-flight, `2` instances, cost 1h `$0.6819`)
- [x] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian): [`screenshots/jaeger-slow-trace.png`](screenshots/jaeger-slow-trace.png) (`1.7s`, span `chat mock-llm-small` chiếm `1.7s` / `1670.5 ms`)
- [x] Một trace lỗi trong Jaeger (có event `exception`): [`screenshots/jaeger-error-trace.png`](screenshots/jaeger-error-trace.png) (`HTTP 503`, `utils.mock_llm.LLMError: Upstream LLM error: 503 Service Unavailable (mock)`)
- [x] Trang Alerts của Prometheus với ≥ 2 alert đang **firing**: [`screenshots/prometheus-alert-firing.png`](screenshots/prometheus-alert-firing.png) (`AgentHighErrorRate` và `AgentInstanceDown` cùng ở trạng thái `FIRING`)

**Trả lời Exercise 7.4 (số liệu đo từ Prometheus API & Grafana khi chạy 2 instance dưới tải Locust 30 users):**
1. **p95 và avg:** Khi chạy tải ổn định trên 2 instance, Prometheus ghi nhận `p95 = 296.1 ms` (`0.2961 s`, trên Grafana lúc chụp: `292.48 ms`) còn `avg = 245.5 ms` (`0.2455 s`), trong khi `p99` nhảy lên ~`1.8 s` trên biểu đồ. Khoảng cách giữa `avg`/`p95` và `p99` phản ánh 3% request slow tail (`+1500 ms`) mà giá trị trung bình làm mờ đi.
2. **Phân tải Nginx ("Requests/s theo instance"):** Nginx round-robin phân phối traffic đều giữa 2 instance — đo thực tế qua Prometheus: `172.23.0.8:8000` nhận `7.60 req/s` và `172.23.0.6:8000` nhận `7.22 req/s`.
3. **Vì sao input tokens/s lớn hơn output tokens/s:** Đo thực tế `input = 1136.3 tokens/s` so với `output = 593.7 tokens/s` (gấp ~`1.91×`) vì agent v2 thực hiện bước retrieval (RAG) rồi ghép `SYSTEM_PROMPT` + đoạn tài liệu truy xuất được + câu hỏi vào prompt đầu vào, dài hơn câu trả lời ngắn ở đầu ra.
4. **`curl http://localhost:8080/metrics`:** Trả về **`HTTP 404 Not Found`** (đã kiểm chứng thực tế `METRICS_STATUS=404`). Trong `nginx/nginx.conf`, khối `location = /metrics { return 404; }` chủ động chặn truy cập công khai vì `/metrics` làm lộ route, traffic, cost và cấu trúc nội bộ; chỉ Prometheus trong mạng Docker nội bộ scrape trực tiếp từng `agent:8000/metrics`.

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (`for: 1m`, đo được `20.4%`) | `85.1 s` | Golden Signals `Error rate`, `Requests/s theo status code` (`503`), `LLM calls theo kết quả` (`error`) |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (`for: 2m`, đo được `p95 = 1969.5 ms`) | `145.2 s` | `Latency /ask — p50 / p95 / p99`, Golden Signals `Latency p95` |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (`for: 2m`, đo được `$13.20/giờ` > `$2/giờ`) | `145.2 s` | `Cost burn rate (USD/giờ)`, `LLM latency p95 theo model` |
| D | `docker pause` 1 instance (`agent-1`) | `AgentInstanceDown` (`for: 30s`, `172.23.0.6:8000` `up=0`) | `40.0 s` | Golden Signals `Instances` (tụt từ 2 xuống 1), `Requests/s theo instance` |
| E | `AGENT_VERSION=v1` | Không có alert nào mới từ `v1` (`agent_info{version="v1"}=1`, `error_rate=1.53%`) | Không firing | `Retrieval hit ratio (agent v2)` biến mất, `Tokens/s` giảm, bảng version chuyển `v1` |

- **Phân tích thí nghiệm D (`docker pause` vs `docker stop` và lỗi 504):**
  - Dùng `docker pause` vì container bị pause vẫn còn bản ghi trong Docker DNS nhưng không phản hồi scrape `/metrics`, nên Prometheus đánh dấu `up{job="agent"} == 0` và bật `AgentInstanceDown`; ngược lại `docker stop` xoá container khỏi DNS khiến Prometheus chỉ coi là target không còn tồn tại.
  - Nếu Nginx gặp timeout với instance bị pause và trả HTTP `504 Gateway Timeout`, lỗi này xảy ra ở tầng proxy nên không xuất hiện trong `http_requests_total` của agent — cần giám sát thêm access log/metrics của chính load balancer hoặc synthetic probe từ bên ngoài.
- **Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**
  - Metric hạ tầng (CPU, RPS, latency, HTTP 5xx) đều xanh khi agent trả lời sai nhưng nhanh và vẫn trả `200 OK`. Để phát hiện suy giảm chất lượng trong production cần: (1) chạy **eval CI quality gate** (`run_eval.py --baseline ...`) chặn deploy khi đổi prompt/model/retrieval; (2) **scheduled eval / shadow eval** trên tập golden dataset định kỳ; (3) theo dõi **business/RAG metrics** (retrieval hit ratio, user feedback thumbs-down, tỷ lệ fallback) và **LLM-as-judge** lấy mẫu trên traffic thật.

### 4.3 Debug bằng trace

**Trace chậm nhất đã phân tích (từ Jaeger & JSON log của `agent-1`):**

- `trace_id`: `bcf9a5cd860dae86c97984ad966ccd2d`
- Tổng thời gian: `1696.7 ms` (hiển thị trên Jaeger UI: `1.7s`)
- Span chiếm nhiều thời gian nhất: `chat mock-llm-small` (`1670.5 ms` trong log / `1.7s` trên Jaeger UI, chiếm **98.5%** tổng thời gian request; còn `agent.retrieve_context` chỉ mất `20.9 ms`)
- Dòng log tương ứng (grep theo `trace_id`):

```json
{"ts": "2026-11-25T08:12:23.611839+00:00", "level": "INFO", "service": "observable-agent", "instance": "db001b15d951", "event": "llm_call", "trace_id": "bcf9a5cd860dae86c97984ad966ccd2d", "span_id": "743658928308ea28", "request_id": "b1b638b1fe21", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 69, "output_tokens": 31, "cost_usd": 2.9e-05, "llm_ms": 1670.5}
{"ts": "2026-11-25T08:12:23.612293+00:00", "level": "INFO", "service": "observable-agent", "instance": "db001b15d951", "event": "http_request", "trace_id": "bcf9a5cd860dae86c97984ad966ccd2d", "span_id": "743658928308ea28", "request_id": "b1b638b1fe21", "method": "POST", "route": "/ask", "status": 200, "ms": 1696.7}
```

**Trace lỗi đã phân tích (`95f530c4b57606edd8c12d15266aee03`):**
- Tổng thời gian: `99.8 ms` (`100ms` trên Jaeger UI, HTTP `503`), span `chat mock-llm-small` (`74.0ms`) ghi event `exception` với `utils.mock_llm.LLMError: Upstream LLM error: 503 Service Unavailable (mock)` khớp với dòng log JSON `llm_error` có cùng `trace_id`:
  `{"ts": "2026-11-25T08:11:55.579019+00:00", "level": "INFO", "service": "observable-agent", "instance": "db001b15d951", "event": "llm_error", "trace_id": "95f530c4b57606edd8c12d15266aee03", "span_id": "f5d321ee4ec4a1d5", "request_id": "eb1d775f3359", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}`

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Số liệu khớp trực tiếp với [`benchmark-results/scale_1_stats.csv`](benchmark-results/scale_1_stats.csv) và [`benchmark-results/scale_3_stats.csv`](benchmark-results/scale_3_stats.csv) (dòng `Aggregated`; giá trị riêng của `POST /ask` đặt trong ngoặc):

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | `65.17` (`POST /ask`: `59.68`) | `200` (`200`) | `250` (`260`) | `1700` (`1700`) | `60 / 7768` (`0.77%`, `POST /ask`: `60 / 7114` = `0.84%`) |
| 3 | `65.75` (`POST /ask`: `59.56`) | `200` (`200`) | `280` (`280`) | `1700` (`1700`) | `74 / 7840` (`0.94%`, `POST /ask`: `74 / 7102` = `1.04%`) |

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

- Scale từ 1 lên 3 instance **không làm giảm p95** (`250 ms` → `280 ms`, p50 vẫn `200 ms`, p99 vẫn `1700 ms`) và tổng throughput hầu như giữ nguyên (`65.17` vs `65.75 req/s`).
- **Nút thắt không nằm ở CPU của FastAPI agent** mà nằm ở: (1) **tải sinh ra bị chặn bởi think time của Locust** (100 virtual users, mỗi user nghỉ `0.5–2s` trung bình `1.25s` + ~`0.25s` xử lý → tối đa ~`66 req/s`, mà 1 instance async I/O đã xử lý thoải mái chưa bão hoà); và (2) **latency của chính upstream LLM call** (`mock-llm-small` mất ~120–180 ms và 3% slow tail `+1500 ms` bất kể có bao nhiêu replica). Scale lên 3 instance chủ yếu tăng **headroom chịu tải cực đại** (khi concurrency lớn hoặc có tác vụ CPU-bound) và **high availability** khi 1 container gặp sự cố.

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. **Luôn đo và đặt SLO theo percentile (`p95`/`p99`) thay vì `average`:** `avg` dễ che giấu 3–10% request slow tail khiến người dùng chờ gần 2 giây dù chỉ số trung bình nhìn rất đẹp.
  2. **Ba trụ cột Metrics – Traces – Logs liên kết chặt chẽ:** Prometheus/Grafana phát hiện bất thường ở mức tổng hợp, Jaeger xác định chính xác span nào chậm/lỗi (`chat mock-llm-small`), và `trace_id` nối trực tiếp sang JSON log để xem chi tiết.
  3. **Infra observability không bắt được lỗi chất lượng AI:** Đổi sang `agent v1` vẫn xanh mọi panel và không alert nào firing, nên bắt buộc phải có **eval trên golden dataset + quality gate** song song với giám sát hạ tầng.
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?
  - Thêm giám sát ở tầng **Nginx/Load Balancer** (bắt lỗi `502`/`504` mà agent không tự đếm được), **LLM-as-judge / semantic eval** chạy mẫu trên traffic thật, **retrieval hit ratio alert** (cảnh báo khi tỷ lệ tìm thấy context tụt đột ngột), **Redis readiness / rate-limit 429 & cost-guard 402 alerts**, và **sampling trace** (ví dụ 10% trace thường + 100% trace lỗi/chậm) để tiết kiệm chi phí lưu trữ khi traffic lớn.
