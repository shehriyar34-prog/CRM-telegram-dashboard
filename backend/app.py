from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .config import settings, BASE_DIR
from .routes import router
from .service import service
from .logger import activity_logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: log application launch and auto-start worker if enabled
    activity_logger.info("FastAPI Web Server initialized.", "SYSTEM")
    if settings.auto_start_service:
        activity_logger.info("Auto-start enabled. Launching CRM-Telegram background service...", "SYSTEM")
        service.start()
    yield
    # Shutdown: stop the background service cleanly
    activity_logger.info("Shutting down web application and stopping background worker...", "SYSTEM")
    service.stop()


def create_app() -> FastAPI:
    app = FastAPI(
        title="CRM Telegram Bridge Hub",
        description="Professional Dashboard and Control Center for SMS CRM & Telegram Bot",
        version="2.0.0",
        lifespan=lifespan,
    )

    # Enable CORS for flexibility
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include REST API routes
    app.include_router(router)

    # Static files directory
    static_dir = BASE_DIR / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

        @app.get("/", include_in_schema=False)
        async def serve_index():
            return FileResponse(static_dir / "index.html")

    return app


app = create_app()
