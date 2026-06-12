"""
Production AI Agent — Kết hợp tất cả Day 12 concepts

Checklist:
  ✅ Config từ environment (12-factor)
  ✅ Structured JSON logging
  ✅ API Key authentication
  ✅ Rate limiting
  ✅ Cost guard
  ✅ Input validation (Pydantic)
  ✅ Health check + Readiness probe
  ✅ Graceful shutdown
  ✅ Security headers
  ✅ CORS
  ✅ Error handling
"""
import os
import time
import signal
import logging
import json
from datetime import datetime, timezone
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

from app.config import settings
from app.auth import verify_api_key
from app.rate_limiter import check_rate_limit
from app.cost_guard import check_budget, record_usage, get_usage

# Mock LLM (thay bằng OpenAI/Anthropic khi có API key)
from utils.mock_llm import ask as llm_ask

# ─────────────────────────────────────────────────────────
# Logging — JSON structured
# ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(message)s",
)
logger = logging.getLogger(__name__)

START_TIME = time.time()
_is_ready = False
_request_count = 0
_error_count = 0
_redis = None
_memory_history: dict[str, list[dict]] = defaultdict(list)


# ─────────────────────────────────────────────────────────
# Redis-backed conversation history
# ─────────────────────────────────────────────────────────
def _redis_client():
    global _redis
    if not settings.redis_url:
        return None
    if _redis is None:
        import redis

        _redis = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


def redis_ready() -> bool:
    try:
        client = _redis_client()
        return bool(client and client.ping())
    except Exception:
        return False


def load_history(user_id: str) -> list[dict]:
    try:
        client = _redis_client()
        if client and client.ping():
            messages = client.lrange(f"history:{user_id}", 0, -1)
            return [json.loads(message) for message in messages]
    except Exception:
        pass
    return _memory_history[user_id]


def append_history(user_id: str, role: str, content: str) -> list[dict]:
    message = {
        "role": role,
        "content": content,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        client = _redis_client()
        if client and client.ping():
            key = f"history:{user_id}"
            pipe = client.pipeline()
            pipe.rpush(key, json.dumps(message))
            pipe.ltrim(key, -20, -1)
            pipe.expire(key, 60 * 60 * 24 * 30)
            pipe.execute()
            return load_history(user_id)
    except Exception:
        pass

    history = _memory_history[user_id]
    history.append(message)
    del history[:-20]
    return history

# ─────────────────────────────────────────────────────────
# Lifespan
# ─────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _is_ready
    logger.info(json.dumps({
        "event": "startup",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
    }))
    time.sleep(0.1)  # simulate init
    _is_ready = True
    logger.info(json.dumps({"event": "ready"}))

    yield

    _is_ready = False
    logger.info(json.dumps({"event": "shutdown"}))

# ─────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)

@app.middleware("http")
async def request_middleware(request: Request, call_next):
    global _request_count, _error_count
    start = time.time()
    _request_count += 1
    try:
        response: Response = await call_next(request)
        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        if "server" in response.headers:
            del response.headers["server"]
        duration = round((time.time() - start) * 1000, 1)
        logger.info(json.dumps({
            "event": "request",
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "ms": duration,
        }))
        return response
    except Exception as e:
        _error_count += 1
        raise

# ─────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────
class AskRequest(BaseModel):
    user_id: str = Field("default", min_length=1, max_length=128,
                         description="Stable user/session identifier")
    question: str = Field(..., min_length=1, max_length=2000,
                          description="Your question for the agent")

class AskResponse(BaseModel):
    user_id: str
    question: str
    answer: str
    model: str
    history_count: int
    usage: dict
    timestamp: str

# ─────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────

@app.get("/", tags=["Info"])
def root():
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "endpoints": {
            "ask": "POST /ask (requires X-API-Key)",
            "health": "GET /health",
            "ready": "GET /ready",
        },
    }


@app.post("/ask", response_model=AskResponse, tags=["Agent"])
async def ask_agent(
    body: AskRequest,
    request: Request,
    _key: str = Depends(verify_api_key),
):
    """
    Send a question to the AI agent.

    **Authentication:** Include header `X-API-Key: <your-key>`
    """
    # Rate limit and budget are keyed by user_id so this remains stateless across replicas.
    check_rate_limit(body.user_id)
    check_budget(body.user_id)

    input_tokens = len(body.question.split()) * 2
    append_history(body.user_id, "user", body.question)

    logger.info(json.dumps({
        "event": "agent_call",
        "q_len": len(body.question),
        "user_id": body.user_id,
        "client": str(request.client.host) if request.client else "unknown",
    }))

    answer = llm_ask(body.question)
    history = append_history(body.user_id, "assistant", answer)

    output_tokens = len(answer.split()) * 2
    usage = record_usage(body.user_id, input_tokens, output_tokens)

    return AskResponse(
        user_id=body.user_id,
        question=body.question,
        answer=answer,
        model=settings.llm_model,
        history_count=len(history),
        usage=usage,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.get("/history/{user_id}", tags=["Agent"])
def history(user_id: str, _key: str = Depends(verify_api_key)):
    messages = load_history(user_id)
    return {
        "user_id": user_id,
        "messages": messages,
        "count": len(messages),
        "storage": "redis" if redis_ready() else "in-memory",
    }


@app.get("/health", tags=["Operations"])
def health():
    """Liveness probe. Platform restarts container if this fails."""
    status = "ok"
    checks = {
        "llm": "mock" if not settings.openai_api_key else "openai",
        "redis": "ok" if redis_ready() else "unavailable",
    }
    return {
        "status": status,
        "version": settings.app_version,
        "environment": settings.environment,
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "total_requests": _request_count,
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready", tags=["Operations"])
def ready():
    """Readiness probe. Load balancer stops routing here if not ready."""
    if not _is_ready:
        raise HTTPException(503, "Not ready")
    if settings.redis_url and not redis_ready():
        raise HTTPException(503, "Redis not ready")
    return {"ready": True, "redis": "ok" if settings.redis_url else "not configured"}


@app.get("/metrics", tags=["Operations"])
def metrics(_key: str = Depends(verify_api_key)):
    """Basic metrics (protected)."""
    usage = get_usage("default")
    return {
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "total_requests": _request_count,
        "error_count": _error_count,
        "default_user_usage": usage,
    }


# ─────────────────────────────────────────────────────────
# Graceful Shutdown
# ─────────────────────────────────────────────────────────
def _handle_signal(signum, _frame):
    logger.info(json.dumps({"event": "signal", "signum": signum}))

signal.signal(signal.SIGTERM, _handle_signal)


if __name__ == "__main__":
    logger.info(f"Starting {settings.app_name} on {settings.host}:{settings.port}")
    logger.info(f"API Key: {settings.agent_api_key[:4]}****")
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        timeout_graceful_shutdown=30,
    )
