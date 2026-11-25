# Day 14 Lab — Mission Answers

## CP0 — Setup Verification

- **Repository Name:** `K5-L3A-DAY14-NguyenTuanDung-2A202603559-Deployment-Benchmark-Observability`
- **Remote (`git remote -v`):**
  ```text
  origin	https://github.com/Ntd1411/K5-L3A-DAY14-NguyenTuanDung-2A202603559-Deployment-Benchmark-Observability.git (fetch)
  origin	https://github.com/Ntd1411/K5-L3A-DAY14-NguyenTuanDung-2A202603559-Deployment-Benchmark-Observability.git (push)
  ```
- **OS (`python -c "import os; print(os.name)"`):** `posix`
- **System Python (`python --version`):** `Python 3.14.10`
- **Project Virtualenv (`.venv/bin/python --version`):** `Python 3.11.18` (`VENV_OK` verified for `fastapi`, `uvicorn`, `redis`, `jwt`, `pydantic`, `dotenv`, `psutil`, `requests`)
- **Docker (`docker --version`):** `Docker version 29.10.0, build fdd4b8e5da`
- **Docker Compose (`docker compose version`):** `Docker Compose version 5.8.0`
- **Docker Smoke Test (`docker run --rm hello-world`):**
  ```text
  Hello from Docker!
  This message shows that your installation appears to be working correctly.
  ```
  (Digest: `sha256:1e4c05b897a751332ce85c7e9449da2d93514ea2dea6dbb0e2753c9e949b2bfa`)

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-Patterns Detected in `01-localhost-vs-production/develop/app.py` and Fixes

1. **Hardcoded secrets in source code**
   - **Anti-pattern (`develop/app.py` L17–L18):** `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` and `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"` are committed directly in source code.
   - **Fix (`production/config.py` L27, L32, L37–L46):** Secrets are read from environment variables via `os.getenv("OPENAI_API_KEY", "")` (L27) and `os.getenv("AGENT_API_KEY", "")` (L32), and `Settings.validate()` (L37–L46) warns if `OPENAI_API_KEY` is unset and raises `ValueError("AGENT_API_KEY must be set in production!")` if `AGENT_API_KEY` is missing when `environment == "production"`.

2. **No centralized config management**
   - **Anti-pattern (`develop/app.py` L21–L22):** `DEBUG = True` and `MAX_TOKENS = 500` are hardcoded module-level constants with no environment override or validation.
   - **Fix (`production/config.py` L14–L35, L50; `production/app.py` L24):** Centralizes all settings in the `Settings` dataclass (`host`, `port`, `debug`, `app_name`, `app_version`, `environment`, `openai_api_key`, `llm_model`, `max_tokens`, `api_key`, `allowed_origins`) loaded from `os.getenv(...)` and instantiated once as `settings = Settings().validate()` (L50), imported in `production/app.py` (L24).

3. **`print()` debugging and secret leakage in logs**
   - **Anti-pattern (`develop/app.py` L33–L34, L38, L48):** Uses unstructured `print()` statements and explicitly prints the API key to stdout (`print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` at L34).
   - **Fix (`production/app.py` L28–L32, L49–L55, L111–L122):** Configures structured JSON logging via `logging.basicConfig(..., format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}')` (L28–L31) with level governed by `settings.debug`, and logs only non-sensitive metadata (`event`, `question_length`, `client_ip`, `response_length`) via `json.dumps(...)` (L111–L122).

4. **Missing health check and readiness endpoints**
   - **Anti-pattern (`develop/app.py` L42–L43):** Only exposes `/` (L25–L27) and `/ask` (L30–L39); platforms and load balancers have no `/health` or `/ready` probe to detect crashes or startup readiness.
   - **Fix (`production/app.py` L35–L36, L135–L173):** Implements `GET /health` (L135–L149) returning status, `uptime_seconds`, `version`, `environment`, and UTC `timestamp`; `GET /ready` (L152–L161) returning `503` while `is_ready` is `False` and `{"ready": true}` once ready; plus `GET /metrics` (L164–L173).

5. **Hardcoded `localhost`, hardcoded port `8000`, and `reload=True`**
   - **Anti-pattern (`develop/app.py` L49–L54):** `uvicorn.run("app:app", host="localhost", port=8000, reload=True)` binds only loopback (unreachable from outside a container), ignores cloud-injected `PORT` (and crashes on port conflict), and leaves hot-reload enabled.
   - **Fix (`production/config.py` L17–L19; `production/app.py` L194–L199):** Defaults `host` to `"0.0.0.0"` (`HOST`), reads `port` from `PORT` (default `8000`), defaults `debug` to `False` (`DEBUG`), and runs `uvicorn.run("app:app" if settings.debug else app, host=settings.host, port=settings.port, reload=settings.debug)`.

6. **No graceful shutdown or lifecycle management**
   - **Anti-pattern (`develop/app.py`):** No FastAPI `lifespan` context manager or `SIGTERM` handler; terminating the process stops immediately without flipping readiness or draining in-flight requests.
   - **Fix (`production/app.py` L39–L68, L73, L180–L189):** Defines `@asynccontextmanager async def lifespan(app: FastAPI)` (L39–L68) attached to `FastAPI(..., lifespan=lifespan)` (L73) to set `is_ready = True` on startup and `is_ready = False` with shutdown drain on exit, and registers `signal.signal(signal.SIGTERM, handle_sigterm)` (L180–L189).

7. **Missing request-body validation and CORS policy**
   - **Anti-pattern (`develop/app.py` L30–L31):** `/ask` takes a bare query parameter `question: str` with no empty-input check and defines no `CORSMiddleware`.
   - **Fix (`production/app.py` L77–L82, L102–L108):** Adds `CORSMiddleware` restricted to `settings.allowed_origins` and `GET`/`POST` methods (L77–L82), and parses a JSON request body in `/ask`, raising `HTTPException(status_code=422, detail="question field is required")` when `question` is empty (L102–L108).

---

### Exercise 1.2: Live Execution & `curl` Outputs

> **Environment note:** Host port `8000` was already occupied by an unrelated pre-existing container (`p108-backend-1`). Running `01-localhost-vs-production/develop/app.py` directly confirmed Anti-pattern #5 immediately (`ERROR: [Errno 98] Address already in use`), so `develop` was served via `.venv/bin/uvicorn app:app --host 127.0.0.1 --port 18001` for endpoint testing, while `production/app.py` adapted cleanly via `PORT=18002`.

**Develop (`01-localhost-vs-production/develop/app.py`) — direct `python app.py` port conflict:**
```text
INFO:     Will watch for changes in these directories: ['/d/Coding/VINUNI/K5-L3A-DAY14-NguyenTuanDung-2A202603559-Deployment-Benchmark-Observability/01-localhost-vs-production/develop']
ERROR:    [Errno 98] Address already in use
Starting agent on localhost:8000...
```

**Develop — `curl -i -X POST "http://localhost:18001/ask?question=Hello"`:**
```http
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 07:13:40 GMT
server: uvicorn
content-length: 103
content-type: application/json

{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

**Production (`PORT=18002 .venv/bin/python app.py` in `01-localhost-vs-production/production/`) — `GET /health`:**
```http
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 07:13:42 GMT
server: uvicorn
content-length: 129
content-type: application/json

{"status":"ok","uptime_seconds":0.3,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T07:13:42.334382+00:00"}
```

**Production — `GET /ready`:**
```http
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 07:13:42 GMT
server: uvicorn
content-length: 14
content-type: application/json

{"ready":true}
```

**Production — `POST /ask` (`{"question": "Hello"}`):**
```http
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 07:13:42 GMT
server: uvicorn
content-length: 167
content-type: application/json

{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.","model":"gpt-4o-mini"}
```

---

### Exercise 1.3: Develop vs Production Comparison & Concepts

| Dimension | Develop (`develop/app.py`) | Production (`production/app.py` & `config.py`) | Why Important |
|-----------|----------------------------|------------------------------------------------|---------------|
| **Config & Secrets** | Hardcoded constants (`OPENAI_API_KEY`, `DATABASE_URL`, `DEBUG`, `MAX_TOKENS`) | `Settings` dataclass reading `os.getenv(...)` + `validate()` fail-fast check | Prevents credential leaks in Git and enables dev/staging/prod parity without code edits |
| **Health & Readiness** | None | `GET /health` (liveness), `GET /ready` (503 until `is_ready`), `GET /metrics` | Allows orchestrators/LBs to restart crashed pods and avoid routing traffic before startup completes |
| **Logging** | Unstructured `print()` calls, including printing `OPENAI_API_KEY` | Structured JSON `logging` format; logs metadata only (`question_length`, `client_ip`) | Log aggregators (Datadog, Loki) can parse/alert on JSON logs without exposing secrets |
| **Graceful Shutdown** | Abrupt exit on stop signal | `lifespan` flips `is_ready = False` + drains; `SIGTERM` handler registered | Prevents dropped in-flight user requests and 502 errors during rolling deploys |
| **Host / Port / Reload** | `host="localhost"`, `port=8000`, `reload=True` | `HOST` (`0.0.0.0`), `PORT` (env var), `reload=settings.debug` (default `False`) | Containers/cloud PaaS require `0.0.0.0` binding, dynamic `PORT`, and no file-watcher overhead |
| **Validation & CORS** | Query param `question: str` with no empty check; no CORS config | JSON body check (`422` if `question` empty) + `CORSMiddleware` with `ALLOWED_ORIGINS` | Rejects malformed input early with standard HTTP codes and blocks unauthorized browser origins |

- **Why hardcoded secrets are dangerous:** Pushing hardcoded API keys or database passwords to GitHub (even temporarily) exposes them permanently in Git history and to automated secret-scanning bots within seconds, leading to unauthorized API billing, data breaches, and emergency key rotation across every environment.
- **Why health checks and graceful shutdown matter:** Health/readiness probes tell load balancers and container platforms when a process is alive (`/health`) and ready for traffic (`/ready`), while graceful shutdown (`SIGTERM` + `lifespan` cleanup) marks the instance unready and lets active requests finish before exit—together eliminating downtime and dropped responses during restarts or rolling deployments.

---

## Part 2: Docker

### Exercise 2.1: Basic Dockerfile (`02-docker/develop/Dockerfile`) Analysis

1. **Base image:** `python:3.11` (L8) — the full Debian-based Python 3.11 image (~1 GB+ including compilers and system packages).
2. **Working directory:** `/app` (L11: `WORKDIR /app`) — all subsequent relative `COPY`, `RUN`, and `CMD` paths execute inside `/app`.
3. **Why `COPY 02-docker/develop/requirements.txt .` + `RUN pip install` before copying application code (`app.py`):** Docker caches each layer sequentially. Because `requirements.txt` changes far less often than `app.py`, installing dependencies before copying source code lets Docker reuse the cached `pip install` layer on code-only rebuilds instead of re-downloading and reinstalling packages every time.
4. **`CMD` vs `ENTRYPOINT`:** `ENTRYPOINT` defines the fixed executable that always runs at container start (only overridden via `--entrypoint`), whereas `CMD` defines default arguments to `ENTRYPOINT` or the default command when no `ENTRYPOINT` is present (and can be overridden directly at the end of `docker run <image> <cmd>`). In `02-docker/develop/Dockerfile` (L30), `CMD ["python", "app.py"]` sets the default command.

---

### Exercise 2.2: Build & Run `my-agent:develop`

- Built from repository root: `docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .`
- Checked `02-docker/develop/app.py` L20–L22: `@app.post("/ask")` accepts query parameter `question: str`.
- Ran `docker run -d --rm --name cp2-dev -p 18003:8000 my-agent:develop` (mapped host port `18003` → container `8000` because host port `8000` was occupied by pre-existing `p108-backend-1`), tested `GET /health` and `POST /ask?question=What%20is%20Docker%3F`, then stopped with `docker stop cp2-dev`.

**`GET /health` (`cp2-dev`):**
```http
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 07:16:13 GMT
server: uvicorn
content-length: 53
content-type: application/json

{"status":"ok","uptime_seconds":0.5,"container":true}
```

**`POST /ask?question=What%20is%20Docker%3F` (`cp2-dev`):**
```http
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 07:16:13 GMT
server: uvicorn
content-length: 103
content-type: application/json

{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

- **Image size (`my-agent:develop`):** `1.66GB` disk usage (`426MB` content size), exact `docker image inspect` size = **`1,662,983,448` bytes (`1,662.98 MB` decimal / `1,585.94 MiB` binary)**.

---

### Exercise 2.3: Multi-Stage Build (`02-docker/production/Dockerfile`) & Size Comparison

- **Stage 1 (`builder` — `FROM python:3.11-slim AS builder`):** Installs build-time OS packages (`gcc`, `libpq-dev`), copies `02-docker/production/requirements.txt`, and installs Python dependencies with `pip install --no-cache-dir --user -r requirements.txt` into `/root/.local`. This stage is used only for compilation and discarded from the final image.
- **Stage 2 (`runtime` — `FROM python:3.11-slim AS runtime`):** Starts from a clean slim base image, creates a non-root user (`appuser`), copies only the installed packages (`COPY --from=builder /root/.local /home/appuser/.local`), copies `02-docker/production/main.py` and `utils/mock_llm.py`, sets `USER appuser`, defines `HEALTHCHECK`, and starts Uvicorn with 2 workers (`CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]`).
- **Why smaller and safer:** Build tools (`gcc`, `libpq-dev`, apt caches) and the full Debian toolchain from `python:3.11` are excluded from the runtime image, shrinking attack surface and disk/pull size while running as non-root `appuser`.

**Actual `docker images my-agent` output:**
```text
IMAGE               ID             DISK USAGE   CONTENT SIZE   EXTRA
my-agent:advanced   7a39f637155e        237MB         57.4MB
my-agent:develop    cd96b895a32a       1.66GB          426MB
```

**Actual `docker image inspect --format '{{.RepoTags}} {{.Size}}' my-agent:develop my-agent:advanced` output:**
```text
[my-agent:develop] 1662983448
[my-agent:advanced] 237366004
```

| Image | Base / Strategy | Disk Usage (`docker images`) | Exact Size (Bytes) | Exact Size (MB, $10^6$ / MiB, $2^{20}$) |
|-------|-----------------|------------------------------|--------------------|-----------------------------------------|
| `my-agent:develop` | Single-stage `python:3.11` | `1.66GB` (content `426MB`) | `1,662,983,448` | `1,662.98 MB` (`1,585.94 MiB`) |
| `my-agent:advanced` | Multi-stage `python:3.11-slim` | `237MB` (content `57.4MB`) | `237,366,004` | `237.37 MB` (`226.37 MiB`) |
| **Reduction** | — | **-1.42 GB** | **-1,425,617,444** | **-1,425.62 MB (`-1,359.57 MiB`) — 85.73% smaller (7.01×)** |

---

### Exercise 2.4: Docker Compose Multi-Service Stack (`02-docker/production/`)

#### Architecture Diagram

```text
                    Docker Bridge Network: internal
                 ┌───────────────────────────────────────────┐
                 │                                           │
Client ──HTTP──▶ │  nginx (nginx:alpine)                     │
  (host :80/443) │    │  rate limit: 10r/s (burst=20)        │
                 │    │  security headers + proxy_pass       │
                 │    ▼                                      │
                 │  agent (my-agent runtime, :8000 internal) │
                 │    ├──▶ redis (redis:7-alpine, :6379)     │
                 │    │       └── volume: redis_data         │
                 │    └──▶ qdrant (qdrant:v1.9.0, :6333)     │
                 │            └── volume: qdrant_data        │
                 └───────────────────────────────────────────┘
```

#### Services & Inter-Service Communication
- **Services started (`docker compose -p k5-day14-docker up -d --build`):**
  1. `redis` (`redis:7-alpine`, port `6379` internal, persistent `redis_data` volume, `redis-cli ping` healthcheck).
  2. `qdrant` (`qdrant/qdrant:v1.9.0`, ports `6333-6334` internal, persistent `qdrant_data` volume, `/dev/tcp/localhost/6333` healthcheck).
  3. `agent` (`02-docker/production/Dockerfile` `runtime` target, port `8000` internal only, `depends_on` `redis` and `qdrant` with `condition: service_healthy`, reads `.env.local`).
  4. `nginx` (`nginx:alpine`, host ports `80:80` and `443:443`, mounts `./nginx/nginx.conf:ro`).
- **How they communicate:** All four services share the private `internal` bridge network and resolve each other via Docker Compose DNS (`agent`, `redis`, `qdrant`). Only `nginx` exposes ports to the host; it terminates external HTTP traffic, enforces `limit_req` (`10r/s`, `burst=20`) on `/`, adds security headers (`X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `X-XSS-Protection`), and proxies requests to `http://agent_backend` (`server agent:8000`). Inside the network, `agent` connects to Redis via `REDIS_URL=redis://redis:6379/0` and Qdrant via `QDRANT_URL=http://qdrant:6333`.

**`docker compose -p k5-day14-docker ps`:**
```text
NAME                       IMAGE                   COMMAND                  SERVICE   CREATED          STATUS                            PORTS
k5-day14-docker-agent-1    k5-day14-docker-agent   "uvicorn main:app --…"   agent     14 seconds ago   Up 2 seconds (health: starting)   8000/tcp
k5-day14-docker-nginx-1    nginx:alpine            "/docker-entrypoint.…"   nginx     14 seconds ago   Up 2 seconds                      0.0.0.0:80->80/tcp, [::]:80->80/tcp, 0.0.0.0:443->443/tcp, [::]:443->443/tcp
k5-day14-docker-qdrant-1   qdrant/qdrant:v1.9.0    "./entrypoint.sh"        qdrant    15 seconds ago   Up 13 seconds (healthy)           6333-6334/tcp
k5-day14-docker-redis-1    redis:7-alpine          "docker-entrypoint.s…"   redis     15 seconds ago   Up 13 seconds (healthy)           6379/tcp
```

**`curl -i http://localhost/health` (via Nginx):**
```http
HTTP/1.1 200 OK
Server: nginx
Date: Wed, 25 Nov 2026 07:16:42 GMT
Content-Type: application/json
Content-Length: 95
Connection: keep-alive
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"status":"ok","uptime_seconds":0.8,"version":"2.0.0","timestamp":"2026-11-25T07:16:42.692509"}
```

**`curl -i -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question": "Explain microservices"}'` (via Nginx):**
```http
HTTP/1.1 200 OK
Server: nginx
Date: Wed, 25 Nov 2026 07:16:42 GMT
Content-Type: application/json
Content-Length: 103
Connection: keep-alive
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

- **Cleanup verified:** `docker compose -p k5-day14-docker down -v` and `docker rmi my-agent:develop my-agent:advanced` removed all containers, volumes, networks, and images cleanly (`docker ps -a` confirmed zero `cp2-dev` or `k5-day14-docker-*` containers remaining).

---

## Part 4: API Security (`04-api-gateway/`)

### Exercise 4.1: API Key Authentication (`04-api-gateway/develop/`)

#### Live Test Outputs (`AGENT_API_KEY=secret-key-123`, port `8004`)

**(a) Missing `X-API-Key` header → `401 Unauthorized`**
```http
HTTP/1.1 401 Unauthorized
date: Wed, 25 Nov 2026 07:13:18 GMT
server: uvicorn
content-length: 67
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}
```

**(b) Wrong `X-API-Key` header (`wrong-key`) → `403 Forbidden`**
```http
HTTP/1.1 403 Forbidden
date: Wed, 25 Nov 2026 07:13:18 GMT
server: uvicorn
content-length: 29
content-type: application/json

{"detail":"Invalid API key."}
```

**(c) Valid `X-API-Key: secret-key-123` → `200 OK`**
```http
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 07:13:18 GMT
server: uvicorn
content-length: 114
content-type: application/json

{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

#### Analysis (Exercise 4.1 Questions)
1. **Where the API key is checked:**
   - In `04-api-gateway/develop/app.py`, `api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)` extracts the `X-API-Key` header.
   - `verify_api_key(api_key: str = Security(api_key_header))` checks it against `API_KEY = os.getenv("AGENT_API_KEY", "demo-key-change-in-production")`, and is injected into the protected endpoint via `_key: str = Depends(verify_api_key)` on `@app.post("/ask")`. (`GET /` and `GET /health` remain public.)
2. **Error behavior:**
   - Missing header (`not api_key`) raises `HTTPException(status_code=401, detail="Missing API key. Include header: X-API-Key: <your-key>")`.
   - Mismatched key (`api_key != API_KEY`) raises `HTTPException(status_code=403, detail="Invalid API key.")`.
   - Note: an empty `question` after passing auth raises `422` (`question is required`).
3. **Zero-downtime key rotation strategy:**
   - Support an overlap window with **multiple active keys** (e.g., `AGENT_API_KEYS` comma-separated or `AGENT_API_KEY` + `AGENT_API_KEY_PREVIOUS` loaded into a `set` and checked with constant-time comparison `hmac.compare_digest`).
   - Rollout steps: (1) add the new key alongside the old key on the server and redeploy, (2) update clients/callers to send the new key, (3) verify traffic has shifted off the old key via logs/metrics, (4) remove the old key from the environment and redeploy.

---

### Exercise 4.2 & 4.3: JWT Authentication & Rate Limiting (`04-api-gateway/production/`)

#### Live Test Outputs (port `8004`, JWT tokens redacted)

**(a) `POST /ask` without token → `401 Unauthorized`**
```http
HTTP/1.1 401 Unauthorized
date: Wed, 25 Nov 2026 07:13:19 GMT
server: uvicorn
www-authenticate: Bearer
content-length: 76
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"detail":"Authentication required. Include: Authorization: Bearer <token>"}
```

**(b) Login at `POST /auth/token` (`student` / `demo123`) → `200 OK`**
```http
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 07:13:19 GMT
server: uvicorn
content-length: 307
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"access_token":"<REDACTED_JWT_TOKEN>","token_type":"bearer","expires_in_minutes":60,"hint":"Include in header: Authorization: Bearer <REDACTED_JWT_PREFIX>..."}
```

**(c) `POST /ask` with `Authorization: Bearer <REDACTED_JWT_TOKEN>` → `200 OK`**
```http
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 07:13:19 GMT
server: uvicorn
content-length: 192
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"question":"Explain JWT","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","usage":{"requests_remaining":9,"budget_remaining_usd":1.9e-05}}
```

**(d) Rate limit loop (12 sequential `POST /ask` calls as `student`) — `200 OK` down to `requests_remaining: 0`, then `429 Too Many Requests`:**
- Calls 1–9 succeed with `200 OK` (`requests_remaining` counts down from `8` to `0`, after the initial call above already used 1 of the 10-request window).
- Call 10 (11th total call in the 60s window) is rejected with `429 Too Many Requests`:

Call 9 (`200 OK`, last allowed request in window):
```http
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 07:13:20 GMT
server: uvicorn
content-length: 211
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"question":"Test 9","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.","usage":{"requests_remaining":0,"budget_remaining_usd":0.000181}}
```

Call 10 (`429 Too Many Requests` with `X-RateLimit-*` and `Retry-After` headers):
```http
HTTP/1.1 429 Too Many Requests
date: Wed, 25 Nov 2026 07:13:20 GMT
server: uvicorn
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795590860
retry-after: 59
content-length: 98
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

#### Exercise 4.3 Questions
1. **Algorithm used (`04-api-gateway/production/rate_limiter.py`):**
   - **Sliding Window** implemented with a per-user `collections.deque` of UNIX timestamps (`self._windows[user_id]`).
   - On each `check(user_id)`, expired timestamps (`window[0] < now - self.window_seconds`) are popped from the left. If `len(window) >= self.max_requests`, it raises HTTP `429` with `X-RateLimit-Limit`, `X-RateLimit-Remaining: 0`, `X-RateLimit-Reset`, and `Retry-After` computed from the oldest active timestamp (`int(oldest + window_seconds - now) + 1`). Otherwise it appends `now`.
2. **Configured limits & role-based selection:**
   - `rate_limiter_user`: **10 requests / 60 seconds** (used for `"user"` role, e.g., `student`).
   - `rate_limiter_admin`: **100 requests / 60 seconds** (used for `"admin"` role, e.g., `teacher`).
   - In `04-api-gateway/production/app.py`, `ask_agent` selects the limiter by role:
     `limiter = rate_limiter_admin if role == "admin" else rate_limiter_user`.
     To bypass rate limiting completely for admins, guard the check with `if role != "admin": rate_info = limiter.check(username)`.
3. **Why Redis is needed in multi-instance deployments:**
   - `RateLimiter._windows` lives in local process memory. Behind a load balancer with `N` instances, each instance maintains an independent `deque`, so a user could send up to `N × 10` req/min (and counters reset whenever a container restarts).
   - Storing rate-limit state in **Redis** (e.g., sorted set `ZADD`/`ZREMRANGEBYSCORE`/`ZCARD` or atomic `INCR` + `EXPIRE` counter keys) gives every instance a single shared, persistent view of each user's quota.

---

### Exercise 4.4: Cost Guard Implementation & Rationale

1. **How Cost Guard works (`04-api-gateway/production/cost_guard.py` + Redis pattern):**
   - **Per-user & global budgets:** `CostGuard` enforces both a per-user daily budget (`daily_budget_usd = 1.0`) and a global daily cap (`global_daily_budget_usd = 10.0`).
   - **Pre-call check & status codes:** `check_budget(user_id)` runs *before* calling the LLM. If the global budget is exhausted, it returns `503 Service Unavailable`; if the user's budget is exhausted, it raises `402 Payment Required`.
   - **Warning threshold:** When `record.total_cost_usd >= daily_budget_usd * warn_at_pct` (`0.8`, i.e., 80%), it logs a warning (`User <id> at X% budget`) before the hard block is hit.
   - **Token accounting:** After `ask()` completes, `record_usage(user_id, input_tokens, output_tokens)` computes USD cost (`$0.00015 / 1K input`, `$0.0006 / 1K output`) and increments both the user's total and `_global_cost`.
   - **Redis key design for production (`INCRBYFLOAT` + `EXPIRE`):**
     - Instead of in-memory dicts, track spend in Redis keyed by user and billing window:
       - Per-user key: `budget:{user_id}:{YYYY-MM}` (monthly, `EXPIRE` 32 days = `2764800`s) or `budget:{user_id}:{YYYY-MM-DD}` (daily, `EXPIRE` 2 days = `172800`s).
       - Global key: `budget:global:{YYYY-MM-DD}` (or `{YYYY-MM}`).
     - Pre-check reads `float(r.get(key) or 0)` against the cap (`402` if exceeded); after the LLM call (or with estimated cost before the call), `r.incrbyfloat(key, cost)` atomically adds the spend and `r.expire(key, ttl)` ensures automatic period reset without manual cron cleanup.
2. **Why BOTH Rate Limiting and Cost Guard are needed:**
   - **Rate limiting protects speed/availability (anti-DoS & burst control):** It caps request frequency (e.g., 10 req/min) so traffic spikes don't saturate workers or downstream APIs. However, a patient attacker or script sending 9 large-context requests every minute for 24 hours stays below the rate limit while generating huge LLM token bills.
   - **Cost guard protects money/LLM token budget:** It caps cumulative dollar spend (per-user and global) over a day or month. However, cost guard alone doesn't stop rapid-fire bursts of short/cheap requests (or auth/validation spam) from overloading the service. Together, rate limiting bounds *throughput* while cost guard bounds *financial exposure*.

---

## Part 5: Scaling & Reliability

*(Pending CP4)*

---

## Part 6: Final Project — Production AI Agent

*(Pending CP5)*

---

## AI log

*(Pending CP5)*
