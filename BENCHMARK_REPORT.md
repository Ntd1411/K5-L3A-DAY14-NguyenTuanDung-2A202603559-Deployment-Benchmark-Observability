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

### 4.1 Screenshot

- [ ] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals)
- [ ] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian)
- [ ] Một trace lỗi trong Jaeger (có event `exception`)
- [ ] Trang Alerts của Prometheus với ít nhất 2 alert đang **firing**

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | | | |
| B | `MOCK_SLOW_RATE=0.3` | | | |
| C | `LLM_MODEL=mock-llm-large` | | | |
| D | `docker pause` 1 instance | | | |
| E | `AGENT_VERSION=v1` | | | |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

...

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất bạn tìm được:

- `trace_id`: ...
- Tổng thời gian: ... ms
- Span chiếm nhiều thời gian nhất: ... (... ms, ...%)
- Dòng log tương ứng (grep theo `trace_id`):

```json

```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | | | | | |
| 3 | | | | | |

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

...

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. ...
  2. ...
  3. ...
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?

...
