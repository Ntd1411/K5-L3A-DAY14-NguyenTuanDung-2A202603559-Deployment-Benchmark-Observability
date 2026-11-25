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

*(Pending CP2)*

---

## Part 4: API Security

*(Pending CP3)*

---

## Part 5: Scaling & Reliability

*(Pending CP4)*

---

## Part 6: Final Project — Production AI Agent

*(Pending CP5)*

---

## AI log

*(Pending CP5)*
