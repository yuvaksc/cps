"""FastAPI application entry point for the CT-MIF Production System."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import settings
from api.database import init_db
from api.routes import anomalies, stream


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create the SQLite schema if needed.
    init_db()
    # Warm the CT-MIF models at startup so the first scored reading isn't slow.
    app.state.scorer_ready = False
    try:
        from core.ctmif import get_scorer

        get_scorer()
        app.state.scorer_ready = True
        print("[startup] CT-MIF models loaded.")
    except Exception as e:
        print(f"[startup] CT-MIF models NOT loaded: {e}")
    print(f"[startup] DB: {settings.database_url}"
          f" | Groq: {'enabled' if settings.groq_enabled else 'DISABLED'}")
    yield


app = FastAPI(
    title="CT-MIF Production API",
    description="Multi-view Isolation-Forest anomaly detection with a "
    "4-agent LangGraph reasoning pipeline.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    # The Streamlit dashboard embeds a browser component that calls the API
    # directly (WebSocket + POST /replay/jump) from a sandboxed iframe whose
    # Origin is "null", so we allow any origin. No credentials/cookies are used.
    allow_origins=settings.cors_origins_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(anomalies.router)
app.include_router(stream.router)


@app.get("/health", tags=["meta"])
def health():
    return {
        "status": "ok",
        "model_ready": getattr(app.state, "scorer_ready", False),
        "groq": settings.groq_enabled,
    }


@app.get("/", tags=["meta"])
def root():
    return {"service": "CT-MIF Production API", "docs": "/docs", "health": "/health"}
