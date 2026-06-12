"""Redis-backed monthly cost guard for LLM usage."""
import time
from dataclasses import dataclass

from fastapi import HTTPException

from app.config import settings


PRICE_PER_1K_INPUT_TOKENS = 0.00015
PRICE_PER_1K_OUTPUT_TOKENS = 0.0006


@dataclass
class Usage:
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class CostGuard:
    def __init__(self, monthly_budget_usd: float):
        self.monthly_budget_usd = monthly_budget_usd
        self._usage: dict[str, Usage] = {}
        self._redis = None

    def _client(self):
        if not settings.redis_url:
            return None
        if self._redis is None:
            import redis

            self._redis = redis.from_url(settings.redis_url, decode_responses=True)
        return self._redis

    @staticmethod
    def _month() -> str:
        return time.strftime("%Y-%m")

    def _key(self, user_id: str) -> str:
        return f"cost:{self._month()}:{user_id}"

    @staticmethod
    def estimate_cost(input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens / 1000 * PRICE_PER_1K_INPUT_TOKENS
            + output_tokens / 1000 * PRICE_PER_1K_OUTPUT_TOKENS
        )

    def _usage_from_redis(self, user_id: str) -> Usage:
        data = self._client().hgetall(self._key(user_id))
        return Usage(
            requests=int(data.get("requests", 0)),
            input_tokens=int(data.get("input_tokens", 0)),
            output_tokens=int(data.get("output_tokens", 0)),
            cost_usd=float(data.get("cost_usd", 0.0)),
        )

    def get_usage(self, user_id: str) -> dict:
        try:
            client = self._client()
            usage = self._usage_from_redis(user_id) if client and client.ping() else self._usage.get(user_id, Usage())
        except Exception:
            usage = self._usage.get(user_id, Usage())

        return {
            "user_id": user_id,
            "month": self._month(),
            "requests": usage.requests,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cost_usd": round(usage.cost_usd, 6),
            "monthly_budget_usd": self.monthly_budget_usd,
            "budget_remaining_usd": round(max(0, self.monthly_budget_usd - usage.cost_usd), 6),
            "budget_used_pct": round(usage.cost_usd / self.monthly_budget_usd * 100, 1),
        }

    def check_budget(self, user_id: str) -> None:
        usage = self.get_usage(user_id)
        if usage["cost_usd"] >= self.monthly_budget_usd:
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "Monthly budget exceeded",
                    "used_usd": usage["cost_usd"],
                    "budget_usd": self.monthly_budget_usd,
                    "resets_at": "first day of next month",
                },
            )

    def record_usage(self, user_id: str, input_tokens: int, output_tokens: int) -> dict:
        cost = self.estimate_cost(input_tokens, output_tokens)
        try:
            client = self._client()
            if client and client.ping():
                key = self._key(user_id)
                pipe = client.pipeline()
                pipe.hincrby(key, "requests", 1)
                pipe.hincrby(key, "input_tokens", input_tokens)
                pipe.hincrby(key, "output_tokens", output_tokens)
                pipe.hincrbyfloat(key, "cost_usd", cost)
                pipe.expire(key, 60 * 60 * 24 * 40)
                pipe.execute()
                return self.get_usage(user_id)
        except Exception:
            pass

        usage = self._usage.setdefault(user_id, Usage())
        usage.requests += 1
        usage.input_tokens += input_tokens
        usage.output_tokens += output_tokens
        usage.cost_usd += cost
        return self.get_usage(user_id)


cost_guard = CostGuard(monthly_budget_usd=settings.monthly_budget_usd)


def check_budget(user_id: str) -> None:
    cost_guard.check_budget(user_id)


def record_usage(user_id: str, input_tokens: int, output_tokens: int) -> dict:
    return cost_guard.record_usage(user_id, input_tokens, output_tokens)


def get_usage(user_id: str) -> dict:
    return cost_guard.get_usage(user_id)
