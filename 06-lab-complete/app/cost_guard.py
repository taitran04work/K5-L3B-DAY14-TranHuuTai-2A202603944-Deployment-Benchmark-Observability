"""UTC daily and monthly Redis ledgers; atomic check-and-charge."""
from datetime import datetime, timezone
from fastapi import HTTPException
from app.config import settings
from app.redis_client import r

BUDGET_SCRIPT = """
local cost = tonumber(ARGV[1])
for i = 1, 2 do
    local current = tonumber(redis.call('GET', KEYS[i]) or '0')
    if current >= tonumber(ARGV[i + 1]) or current + cost > tonumber(ARGV[i + 1]) then
        return 0
    end
end
if cost > 0 then
    for i = 1, 2 do
        redis.call('INCRBYFLOAT', KEYS[i], cost)
        redis.call('EXPIRE', KEYS[i], ARGV[3 + i])
    end
end
return 1
"""


def _check_and_charge(cost: float) -> None:
    now = datetime.now(timezone.utc)
    prefix = f"budget:{settings.environment}"
    allowed = r.eval(BUDGET_SCRIPT, 2, f"{prefix}:day:{now:%Y-%m-%d}",
                     f"{prefix}:month:{now:%Y-%m}", cost,
                     settings.daily_budget_usd, settings.monthly_budget_usd,
                     2 * 86400, 32 * 86400)
    if not allowed:
        raise HTTPException(status_code=402, detail="LLM budget exhausted")


def check_budget() -> None:
    _check_and_charge(0)


def record_cost(input_tokens: int, output_tokens: int) -> float:
    cost = (input_tokens * settings.price_input_per_1k +
            output_tokens * settings.price_output_per_1k) / 1000
    _check_and_charge(cost)
    return cost
