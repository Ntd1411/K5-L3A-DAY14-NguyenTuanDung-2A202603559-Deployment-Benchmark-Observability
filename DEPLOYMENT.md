# Deployment Information

## Public URL
https://k5-l3a-day14-nguyentuandung-2a202603559-deployme-production.up.railway.app

## Platform
Railway (`Root Directory`: `06-lab-complete`, multi-stage `Dockerfile` via `railway.toml`, paired with Railway managed Redis service)

## Test Commands

### CP6 Full Status Verification (4 checks)
```bash
export BASE="https://k5-l3a-day14-nguyentuandung-2a202603559-deployme-production.up.railway.app"
export AGENT_API_KEY="<YOUR_AGENT_API_KEY>"

curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"   # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"    # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

### Health Check
```bash
curl https://k5-l3a-day14-nguyentuandung-2a202603559-deployme-production.up.railway.app/health
# Expected: {"status":"ok","environment":"production"}
```

### Readiness Check (Redis)
```bash
curl https://k5-l3a-day14-nguyentuandung-2a202603559-deployme-production.up.railway.app/ready
# Expected: {"status":"ready","redis":"ok"}
```

### API Test (Unauthenticated → 401)
```bash
curl -i -X POST https://k5-l3a-day14-nguyentuandung-2a202603559-deployme-production.up.railway.app/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Hello"}'
# Expected: HTTP 401 {"detail":"Invalid or missing API key"}
```

### API Test (with authentication → 200)
```bash
curl -X POST https://k5-l3a-day14-nguyentuandung-2a202603559-deployme-production.up.railway.app/ask \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'
```

## Environment Variables Set
- `PORT` — Auto-injected by Railway (`Dockerfile` `CMD` listens on `${PORT:-8000}`)
- `REDIS_URL` — Referenced from Railway Redis service (`${{Redis.REDIS_URL}}`)
- `AGENT_API_KEY` — Configured securely in Railway Variables (never committed to Git)
- `ENVIRONMENT` — `production`
- `RATE_LIMIT_PER_MINUTE` — `10`
- `DAILY_BUDGET_USD` — `1.0`
- `MONTHLY_BUDGET_USD` — `10.0`

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
