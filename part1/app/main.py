import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from prometheus_client import Counter, Histogram, make_asgi_app
import redis.asyncio as aioredis

# -------------------------------------------------------------------
# Configuration from Environment Variables
# -------------------------------------------------------------------
APP_ENV = os.getenv("APP_ENV", "development")
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
WORKERS = int(os.getenv("WORKERS", "1"))
MAX_CONNECTIONS = int(os.getenv("MAX_CONNECTIONS", "100"))

# -------------------------------------------------------------------
# Logging Setup
# -------------------------------------------------------------------
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] [env=" + APP_ENV + "] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("data-sync")

# -------------------------------------------------------------------
# Prometheus Custom Metrics
# -------------------------------------------------------------------
SYNC_REQUESTS = Counter(
    "datasync_requests_total",
    "Total data-sync operation count",
    ["method", "status"],
)
SYNC_LATENCY = Histogram(
    "datasync_duration_seconds",
    "Duration of sync operations in seconds",
)

# -------------------------------------------------------------------
# Redis Client Lifecycle
# -------------------------------------------------------------------
redis_client: Optional[aioredis.Redis] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client
    logger.info("Initializing connection pool to Redis at %s:%d", REDIS_HOST, REDIS_PORT)
    pool = aioredis.ConnectionPool(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD if REDIS_PASSWORD else None,
        max_connections=MAX_CONNECTIONS,
        decode_responses=True,
    )
    redis_client = aioredis.Redis(connection_pool=pool)
    try:
        await redis_client.ping()
        logger.info("Successfully connected to Redis.")
    except Exception as exc:
        logger.warning("Could not reach Redis on startup: %s", exc)

    yield

    logger.info("Closing Redis connection pool.")
    if redis_client:
        await redis_client.close()


# -------------------------------------------------------------------
# FastAPI Application
# -------------------------------------------------------------------
app = FastAPI(title="data-sync", lifespan=lifespan)

# Mount Prometheus /metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


@app.get("/health")
async def health():
    """Health check endpoint required by probes."""
    return {"status": "ok"}


@app.get("/")
async def root():
    return {
        "service": "data-sync",
        "env": APP_ENV,
        "redis_host": REDIS_HOST,
        "max_connections": MAX_CONNECTIONS,
    }


@app.post("/sync/{key}")
async def sync_data(key: str, payload: dict):
    """Replicates a sync workflow by caching data into Redis."""
    if not redis_client:
        raise HTTPException(status_code=503, detail="Cache client not initialized")

    with SYNC_LATENCY.time():
        try:
            await redis_client.set(f"sync:{key}", str(payload), ex=3600)
            SYNC_REQUESTS.labels(method="POST", status="success").inc()
            logger.debug("Successfully synced key: %s", key)
            return {"key": key, "status": "synced"}
        except Exception as exc:
            SYNC_REQUESTS.labels(method="POST", status="error").inc()
            logger.error("Failed to sync key %s: %s", key, exc)
            raise HTTPException(status_code=500, detail="Redis write error")


@app.get("/sync/{key}")
async def get_synced_data(key: str):
    """Retrieves cached data from Redis."""
    if not redis_client:
        raise HTTPException(status_code=503, detail="Cache client not initialized")

    try:
        val = await redis_client.get(f"sync:{key}")
        if val is None:
            raise HTTPException(status_code=404, detail="Key not found")
        SYNC_REQUESTS.labels(method="GET", status="success").inc()
        return {"key": key, "data": val}
    except HTTPException:
        raise
    except Exception as exc:
        SYNC_REQUESTS.labels(method="GET", status="error").inc()
        logger.error("Failed to read key %s: %s", key, exc)
        raise HTTPException(status_code=500, detail="Redis read error")