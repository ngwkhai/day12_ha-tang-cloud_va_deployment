# Day 12 Lab - Mission Answers

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found
1. App develop dùng config mặc định trong code thay vì đọc toàn bộ từ environment variables.
2. Server dev thường bind `127.0.0.1`, phù hợp local nhưng không phù hợp container/cloud.
3. Thiếu `/health` và `/ready`, platform không biết lúc nào app sống hoặc sẵn sàng nhận traffic.
4. Không có structured logging nên khó debug khi chạy trên cloud.
5. Không có graceful shutdown, request đang xử lý có thể bị mất khi platform gửi `SIGTERM`.
6. Secret/API key dễ bị hardcode nếu không dùng `.env.example` và env vars.

### Exercise 1.3: Comparison table
| Feature | Develop | Production | Why Important? |
|---------|---------|------------|----------------|
| Config | Một số giá trị cố định trong code | Đọc từ env vars | Deploy cùng image cho nhiều môi trường |
| Host/Port | Local/dev defaults | `0.0.0.0` và `$PORT` | Container/cloud route traffic được |
| Health | Thiếu hoặc đơn giản | `/health` và `/ready` | Load balancer và platform kiểm tra trạng thái |
| Logging | Plain text | JSON structured logs | Dễ search, alert, trace lỗi |
| Shutdown | Dừng đột ngột | Có graceful shutdown | Không mất request đang xử lý |
| Security | Ít guardrail | API key, no hardcoded secrets | Giảm rủi ro lộ API công khai |

## Part 2: Docker

### Exercise 2.1: Dockerfile questions
1. Base image: bản basic dùng `python:3.11`, dễ học nhưng lớn; production dùng `python:3.11-slim` để giảm size.
2. Working directory: `WORKDIR /app` giúp mọi lệnh copy/run chạy từ một thư mục ổn định trong container.
3. Copy requirements trước source code: tận dụng Docker layer cache; code đổi không bắt buộc cài lại dependencies.
4. `EXPOSE 8000`: documentation cho port app, còn publish ra host cần `-p` hoặc compose `ports`.
5. `CMD`: command mặc định khi container start, ví dụ chạy Uvicorn/FastAPI.

### Exercise 2.3: Image size comparison
- Develop image: `agent-develop` = 1.67 GB.
- Production image: `06-lab-complete-agent` = 272 MB.
- Difference: production nhỏ hơn khoảng 83.7%.
- Lý do: production dùng slim image, multi-stage build, chỉ copy runtime packages và source cần thiết.

### Exercise 2.4: Docker Compose architecture
```text
Client
  |
  v
Agent container :8000
  |
  v
Redis container :6379
```

Production examples mở rộng thêm Nginx reverse proxy/load balancer trước nhiều agent replicas.

## Part 3: Cloud Deployment

### Exercise 3.1: Railway deployment
- Config file: `03-cloud-deployment/railway/railway.toml` and `06-lab-complete/railway.toml`.
- Start command reads `$PORT`, which Railway injects automatically.
- Required variables: `AGENT_API_KEY`, optional `OPENAI_API_KEY`, `REDIS_URL`, `ENVIRONMENT`.
- Public URL: https://06-day12-production.up.railway.app
- Screenshot: add deployment screenshots under `screenshots/` after cloud deploy.

### Exercise 3.2: Render vs Railway
| Item | Railway | Render |
|------|---------|--------|
| Config | `railway.toml` | `render.yaml` |
| Deploy style | CLI or GitHub-connected project | Blueprint from GitHub |
| Env vars | CLI/dashboard variables | Dashboard or `render.yaml` declarations |
| Best for | Fast MVP/demo | More explicit infrastructure-as-code |

### Exercise 3.3: Cloud Run CI/CD
`cloudbuild.yaml` builds and pushes the container image, then deploys it to Cloud Run using `service.yaml`. This gives repeatable production deploys on every approved source change.

## Part 4: API Security

### Exercise 4.1: API Key authentication
- Protected endpoint: `POST /ask`.
- Required header: `X-API-Key`.
- Missing or invalid key returns `401`.
- Valid key allows the agent request to continue.

Example:
```bash
curl -H "X-API-Key: dev-key-change-me-in-production" \
  -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"user_id":"test","question":"hello"}'
```

### Exercise 4.2: JWT authentication
JWT is useful when users log in and the API needs stateless identity, role, and expiry data. API keys are simpler for internal services and demos; JWT is better for end-user auth.

### Exercise 4.3: Rate limiting
The final app uses a sliding-window limiter with Redis when available and in-memory fallback for local tests. Limit is configured with `RATE_LIMIT_PER_MINUTE=10`.

Expected behavior:
- Requests 1-10 in a minute return `200` if authenticated.
- Request 11 returns `429 Too Many Requests`.

### Exercise 4.4: Cost guard implementation
The final app estimates token cost before/after an LLM call and tracks monthly usage per `user_id`. Usage is stored in Redis when available, with an in-memory fallback. If a user reaches `MONTHLY_BUDGET_USD=10.0`, `/ask` returns `402`.

## Part 5: Scaling & Reliability

### Exercise 5.1: Health checks
- `/health`: liveness probe; returns app status, uptime, request count, LLM mode, and Redis status.
- `/ready`: readiness probe; returns `503` if app startup is incomplete or Redis is unavailable when configured.

### Exercise 5.2: Graceful shutdown
The app logs `SIGTERM` and Uvicorn runs with graceful shutdown support. This lets in-flight requests finish before the process exits.

### Exercise 5.3: Stateless design
Conversation history, rate-limit counters, and cost usage are keyed by `user_id` and stored in Redis when configured. This lets multiple app instances serve the same user without relying on local memory.

### Exercise 5.4: Load balancing
The scaling demo uses Nginx in front of multiple agent replicas. Requests can be routed to different instances while shared session state remains consistent through Redis.

### Exercise 5.5: Test stateless
Run:
```bash
cd 05-scaling-reliability/production
docker compose -p scaling up --scale agent=3
python test_stateless.py
```

Expected result:
- Multiple requests may be served by different instances.
- Conversation history remains complete because state is stored in Redis.

## Part 6: Final Project

The final production-ready agent is in `06-lab-complete/` and includes:
- Environment-based config.
- API key authentication.
- Redis-backed rate limiting.
- Redis-backed monthly cost guard.
- Redis-backed conversation history.
- Health and readiness probes.
- Structured request logs.
- Multi-stage Dockerfile with non-root runtime user.
- Docker Compose stack with agent and Redis.
- Railway and Render deployment config.
