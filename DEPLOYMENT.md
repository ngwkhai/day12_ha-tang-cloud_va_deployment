# Deployment Information

## Public URL
https://06-day12-production.up.railway.app

## Platform
Railway.

The repository already includes:
- `06-lab-complete/railway.toml`
- `06-lab-complete/render.yaml`

## Local Verification URL
```text
http://localhost:8000
```

## Test Commands

### Health Check
```bash
curl https://06-day12-production.up.railway.app/health
```

Expected:
```json
{"status":"ok"}
```

### Readiness Check
```bash
curl https://06-day12-production.up.railway.app/ready
```

Expected:
```json
{"ready":true,"redis":"ok"}
```

### API Test With Authentication
```bash
API_KEY=<your-railway-agent-api-key>

curl -X POST https://06-day12-production.up.railway.app/ask \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'
```

### Authentication Required
```bash
curl -X POST https://06-day12-production.up.railway.app/ask \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'
```

Expected: `401`.

### Rate Limit
```bash
API_KEY=<your-railway-agent-api-key>

for i in $(seq 1 15); do
  curl -s -X POST https://06-day12-production.up.railway.app/ask \
    -H "X-API-Key: $API_KEY" \
    -H "Content-Type: application/json" \
    -d '{"user_id": "rate-test", "question": "test"}'
  echo
done
```

Expected: request 11 or later returns `429`.

## Environment Variables Set
- `PORT`
- `AGENT_API_KEY`
- `JWT_SECRET`
- `ENVIRONMENT`
- `RATE_LIMIT_PER_MINUTE`
- `MONTHLY_BUDGET_USD`
- `REDIS_URL` optional; current Railway service falls back to in-memory because Redis is not configured.
- `ALLOWED_ORIGINS` optional.
- `OPENAI_API_KEY` optional; empty value uses mock LLM.

## Screenshots
Add cloud deployment screenshots after Railway or Render deploy:
- `screenshots/dashboard.png`
- `screenshots/running.png`
- `screenshots/test.png`
