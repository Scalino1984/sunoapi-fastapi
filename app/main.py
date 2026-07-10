import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.config import get_settings
from app.database import init_db
from app.services.startup_database_guard import create_initial_admin_if_needed, ensure_jwt_secret, prepare_initial_database_credentials
from app.services.startup_task_recovery import run_startup_task_recovery, run_startup_library_repair
from app.services.library_content_polling_service import run_library_content_polling
from app.services.portable_backup_service import run_portable_backup_scheduler
from app.services.task_lifecycle_service import run_periodic_task_watchdog
from app.routers import admin, ai_chat, archive, audio, audio_assets, assistant, auth, credits, daw, files, library, lyrics, music, notifications, production, songs_srt, srt, system, webhooks
from app.suno_client import SunoAPIError
from app.middleware import ActionStatusFallbackMiddleware, RequestContextMiddleware
from app.auth import get_current_active_user


settings = get_settings()
logger = logging.getLogger("songstudio.startup")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Vor DB-Initialisierung die konfigurierte SQLite-Datei prüfen.
    # Existiert sie noch nicht, wird im interaktiven Terminal ein erster Admin
    # abgefragt. In nicht-interaktiven Deployments muss INITIAL_ADMIN_EMAIL /
    # INITIAL_ADMIN_PASSWORD oder eine vorbereitete DB gesetzt werden.
    ensure_jwt_secret(settings)
    initial_admin = prepare_initial_database_credentials(settings)
    init_db()
    create_initial_admin_if_needed(initial_admin)

    background_tasks: list[asyncio.Task] = []

    if settings.suno_startup_recovery_enabled:
        logger.info("Plane Wiederherstellung offener Suno-Tasks nach FastAPI-Start.")
        background_tasks.append(asyncio.create_task(run_startup_task_recovery(), name="suno-startup-recovery"))

    if settings.task_watchdog_enabled:
        logger.info("Starte periodischen Watchdog für hängende lokale Background-Tasks.")
        background_tasks.append(asyncio.create_task(run_periodic_task_watchdog(), name="task-watchdog"))

    if getattr(settings, "startup_library_repair_enabled", True):
        logger.info("Plane einmalige Audio-Library-Reparatur nach FastAPI-Start.")
        background_tasks.append(asyncio.create_task(run_startup_library_repair(), name="startup-library-repair"))

    logger.info("Plane optionales Library-Content-Polling nach FastAPI-Start.")
    background_tasks.append(asyncio.create_task(run_library_content_polling(), name="library-content-polling"))

    logger.info("Plane optionalen Auto-Backup-Scheduler nach FastAPI-Start.")
    background_tasks.append(asyncio.create_task(run_portable_backup_scheduler(), name="portable-backup-scheduler"))

    try:
        yield
    finally:
        # Shutdown: laufende Loops sauber abbrechen statt hart killen. Die Loops
        # behandeln CancelledError und schließen ihre DB-Sessions selbst.
        for task in background_tasks:
            task.cancel()
        for task in background_tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass


app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    version="1.0.0-enterprise",
    lifespan=lifespan,
)

app.add_middleware(RequestContextMiddleware)
app.add_middleware(ActionStatusFallbackMiddleware)
if settings.trusted_hosts_list != ["*"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts_list)
if settings.cors_allow_origins_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")
settings.audio_storage_path.mkdir(parents=True, exist_ok=True)
app.mount(settings.suno_audio_public_route, StaticFiles(directory=settings.audio_storage_path), name="audio_media")
settings.cover_storage_path.mkdir(parents=True, exist_ok=True)
app.mount(settings.suno_cover_public_route, StaticFiles(directory=settings.cover_storage_path), name="cover_media")
settings.video_storage_path.mkdir(parents=True, exist_ok=True)
app.mount(settings.suno_video_public_route, StaticFiles(directory=settings.video_storage_path), name="video_media")
settings.transcript_storage_path.mkdir(parents=True, exist_ok=True)

react_dist_dir = Path(__file__).resolve().parents[1] / "frontend-react" / "dist"
if react_dist_dir.exists():
    react_assets_dir = react_dist_dir / "assets"
    if react_assets_dir.exists():
        app.mount("/react/assets", StaticFiles(directory=react_assets_dir), name="react_assets")
        app.mount("/assets", StaticFiles(directory=react_assets_dir), name="react_root_assets")


auth_dependency = [Depends(get_current_active_user)]

app.include_router(auth.router)
app.include_router(admin.router, dependencies=auth_dependency)
app.include_router(music.router, dependencies=auth_dependency)
app.include_router(archive.router, dependencies=auth_dependency)
app.include_router(library.router, dependencies=auth_dependency)
app.include_router(ai_chat.router, dependencies=auth_dependency)
app.include_router(assistant.router, dependencies=auth_dependency)
app.include_router(production.router, dependencies=auth_dependency)
app.include_router(notifications.router, dependencies=auth_dependency)
app.include_router(system.router, dependencies=auth_dependency)
app.include_router(lyrics.router, dependencies=auth_dependency)
app.include_router(audio.router, dependencies=auth_dependency)
app.include_router(audio_assets.router, dependencies=auth_dependency)
app.include_router(srt.router, dependencies=auth_dependency)
app.include_router(songs_srt.router, dependencies=auth_dependency)
app.include_router(files.router, dependencies=auth_dependency)
app.include_router(credits.router, dependencies=auth_dependency)
app.include_router(daw.router, dependencies=auth_dependency)
app.include_router(webhooks.router)


@app.exception_handler(SunoAPIError)
async def suno_api_error_handler(request: Request, exc: SunoAPIError) -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={
            "ok": False,
            "error": str(exc),
            "source": "sunoapi",
            "path": request.url.path,
        },
    )


@app.get("/")
def index() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/live")
def health_live() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/health/ready")
def health_ready() -> dict[str, str]:
    from app.database import engine
    from sqlalchemy import text
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ready"}


@app.get("/react")
def react_index() -> FileResponse:
    index_path = react_dist_dir / "index.html"
    if not index_path.exists():
        return FileResponse(static_dir / "index.html")
    return FileResponse(index_path)


@app.get("/react/{full_path:path}")
def react_spa(full_path: str) -> FileResponse:
    requested = react_dist_dir / full_path
    if requested.exists() and requested.is_file():
        return FileResponse(requested)
    index_path = react_dist_dir / "index.html"
    if not index_path.exists():
        return FileResponse(static_dir / "index.html")
    return FileResponse(index_path)
