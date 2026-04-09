import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import get_settings
from backend.database import create_db_and_tables


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    settings = get_settings()
    os.makedirs(settings.media_dir, exist_ok=True)
    create_db_and_tables()
    yield
    # Shutdown (nothing to clean up for now)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Video Translator API",
        description="POC backend for AI-powered video lecture translation",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from backend.api.jobs import router as jobs_router
    from backend.api.lectures import router as lectures_router
    from backend.api.segments import router as segments_router

    app.include_router(lectures_router, prefix="/api")
    app.include_router(segments_router, prefix="/api")
    app.include_router(jobs_router, prefix="/api")

    return app


app = create_app()
