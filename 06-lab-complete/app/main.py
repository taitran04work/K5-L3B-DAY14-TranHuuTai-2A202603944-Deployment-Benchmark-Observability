"""Production AI Agent — authentication and shared Redis protections."""
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from redis import RedisError

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import r, redis_healthy
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                           "level": record.levelname, "event": record.getMessage(),
                           **getattr(record, "fields", {})}, ensure_ascii=False)


logger = logging.getLogger("agent")
handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logger.handlers = [handler]
logger.propagate = False
logger.setLevel(settings.log_level.upper())


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Uvicorn owns SIGTERM and drains requests before lifespan cleanup.
    logger.info("startup", extra={"fields": {"environment": settings.environment}})
    yield
    r.close()
    logger.info("graceful_shutdown")


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


@app.middleware("http")
async def request_log(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")
    logger.info("http_request", extra={"fields": {
        "route": route.path if route else "unmatched", "status": response.status_code,
        "ms": round((time.perf_counter() - start) * 1000, 2)}})
    return response


@app.exception_handler(RedisError)
async def redis_error(request: Request, exc: RedisError):
    logger.warning("redis_unavailable")
    return JSONResponse(status_code=503, content={"detail": "Redis unavailable"})


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    if not redis_healthy():
        raise HTTPException(status_code=503, detail="Redis unavailable")
    return {"status": "ready"}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)
    check_budget()
    answer = llm_ask(body.question)
    # Text-only mock: estimate tokens as chars / 4 (not provider billing).
    cost = record_cost(max(1, len(body.question) // 4), max(1, len(answer) // 4))
    logger.info("llm_call", extra={"fields": {"cost_usd": cost}})
    return {"question": body.question, "answer": answer, "cost_usd": cost}
