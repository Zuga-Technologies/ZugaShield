"""The Pentagon — ZugaShield's security-posture dashboard backend.

Serves a single live dashboard page, aggregates real security signals from the
fleet (AgentPool rail, signature catalog, version drift, GitHub issues, red-team
ledger) on per-source intervals, and speaks the Domain Outcome Contract so the
existing 'shield' building on the Dominion city map lights up with real KPIs.

Justin heads this — it is the visual face of the security lane.

Run: cd ZugaShield/dashboard/backend && python -m uvicorn main:app --port 8019
"""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

from config import settings  # noqa: E402
from db import init_db  # noqa: E402
from routes.pentagon_api import router as pentagon_router  # noqa: E402
from routes.domain import router as domain_router  # noqa: E402

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    logger.info("Starting %s on port %s", settings.app_name, settings.port)
    init_db()
    from scheduler import run_forever
    task = asyncio.create_task(run_forever())
    logger.info("Collector loop started")
    yield
    task.cancel()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "https://zugabot.ai"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(pentagon_router)
app.include_router(domain_router)


@app.get("/api/health/live")
@app.get("/health/live")
async def health_live():
    return {"status": "ok", "service": settings.app_name}


@app.get("/")
async def dashboard_page():
    index = _STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"service": settings.app_name, "note": "dashboard page not built yet"}


if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.host, port=settings.port)
