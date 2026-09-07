"""
backend-fastapi/app/main.py — FastAPI app root
PRD F1.2 backend FastAPI skeleton
"""
from __future__ import annotations
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from sqlalchemy import text

from .config import settings
from .db import engine, SessionLocal
from .models import Base
from .routes import auth, students, materials, zones, detections, activities, dashboard, dashboard_htmx, videos, cameras, schools, storage, system, hold_sessions
from .websocket import manager
from .services.minio_service import minio_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
log = logging.getLogger("tkm.main")

# Prometheus metrics
REQ_COUNT = Counter("tkm_requests_total", "Total HTTP requests", ["method", "path", "status"])
REQ_LATENCY = Histogram("tkm_request_latency_seconds", "HTTP request latency", ["method", "path"])

BASE = Path(__file__).parent
# Templates live at backend-fastapi/templates/ (repo level); app/templates/ is legacy empty dir.
# Prefer whichever actually contains .html files.
_REPO_TEMPLATES = BASE.parent / "templates"
_REPO_STATIC = BASE.parent / "static"
STATIC_DIR = _REPO_STATIC if any(_REPO_STATIC.glob("*.css")) or _REPO_STATIC.is_dir() else (BASE / "static")
_candidates = [p for p in (_REPO_TEMPLATES, BASE / "templates") if (p / "index.html").exists() or (p / "login.html").exists()]
TEMPLATES_DIR = _candidates[0] if _candidates else (BASE / "templates")
STATIC_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="TK Montessori — Computer Vision Activity Monitoring (YOLOv8 + ArUco, fullstack)",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(students.router)
app.include_router(materials.router)
app.include_router(zones.router)
app.include_router(detections.router)
app.include_router(activities.router)
app.include_router(dashboard.router)
app.include_router(dashboard_htmx.router)
app.include_router(videos.router)
app.include_router(cameras.router)
app.include_router(schools.router)
app.include_router(storage.router)
app.include_router(system.router)
app.include_router(hold_sessions.router)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    dur = time.perf_counter() - start
    REQ_COUNT.labels(request.method, request.url.path, response.status_code).inc()
    REQ_LATENCY.labels(request.method, request.url.path).observe(dur)
    return response


@app.on_event("startup")
async def on_startup() -> None:
    log.info("Starting %s v%s", settings.app_name, settings.app_version)
    # Ensure tables exist (fallback if alembic not run)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        log.info("DB schema ensured (Base.metadata.create_all)")
    except Exception as e:
        log.warning("DB schema init deferred: %s", e)
    # MinIO buckets
    try:
        minio_service._ensure_buckets()
    except Exception as e:
        log.warning("MinIO init deferred: %s", e)


@app.get("/health")
async def health() -> dict:
    db_ok = False
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            db_ok = True
    except Exception as e:
        log.warning("DB health failed: %s", e)
    return {
        "status": "ok" if db_ok else "degraded",
        "service": settings.app_name,
        "version": settings.app_version,
        "db": db_ok,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/metrics")
def metrics() -> JSONResponse:
    return JSONResponse(content={"prometheus": generate_latest().decode()[:0] or ""}, media_type=CONTENT_TYPE_LATEST) if False else \
        __import__("fastapi.responses", fromlist=["Response"]).Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/v1/health/full")
async def health_full() -> dict:
    """Detailed health including MinIO, Redis, Postgres."""
    out: dict = {"db": False, "minio": False, "redis": False}
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            out["db"] = True
    except Exception as e:
        out["db_error"] = str(e)
    try:
        out["minio_buckets"] = [
            b["Name"] for b in minio_service.client.list_buckets().get("Buckets", [])
        ]
        out["minio"] = True
    except Exception as e:
        out["minio_error"] = str(e)
    try:
        import redis
        r = redis.from_url(settings.redis_url)
        r.ping()
        out["redis"] = True
    except Exception as e:
        out["redis_error"] = str(e)
    return out


# ----- Templates -----
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "dashboard_utama.html", {"request": request, "settings": settings})


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"request": request, "settings": settings})


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_utama(request: Request):
    return templates.TemplateResponse(request, "dashboard_utama.html", {"request": request, "settings": settings})


@app.get("/dashboard/ortu", response_class=HTMLResponse)
async def dashboard_ortu(request: Request):
    return templates.TemplateResponse(request, "dashboard_ortu.html", {"request": request, "settings": settings})


@app.get("/admin", response_class=HTMLResponse)
async def dashboard_admin(request: Request):
    return templates.TemplateResponse(request, "dashboard_admin.html", {"request": request, "settings": settings})


# ----- WebSocket -----
@app.websocket("/ws/live")
async def ws_live(ws: WebSocket):
    await manager.connect(ws)
    try:
        await ws.send_json({"event": "hello", "ts": datetime.now(timezone.utc).isoformat()})
        while True:
            data = await ws.receive_text()
            # echo
            await ws.send_json({"event": "ack", "data": data})
    except WebSocketDisconnect:
        await manager.disconnect(ws)


# ----- Static -----
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
