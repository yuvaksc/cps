"""FastAPI application entry point for the CT-MIF Production System."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import settings
from api.routes import analyze, anomalies, stream


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm the CT-MIF models at startup so the first /analyze isn't slow.
    app.state.scorer_ready = False
    try:
        from core.ctmif import get_scorer

        get_scorer()
        app.state.scorer_ready = True
        print("[startup] CT-MIF models loaded.")
    except Exception as e:
        print(f"[startup] CT-MIF models NOT loaded: {e}")
    print(f"[startup] Supabase: {'enabled' if settings.supabase_enabled else 'DISABLED'}"
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
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analyze.router)
app.include_router(anomalies.router)
app.include_router(stream.router)


@app.get("/health", tags=["meta"])
def health():
    return {
        "status": "ok",
        "model_ready": getattr(app.state, "scorer_ready", False),
        "supabase": settings.supabase_enabled,
        "groq": settings.groq_enabled,
    }


@app.get("/", tags=["meta"])
def root():
    return {"service": "CT-MIF Production API", "docs": "/docs", "health": "/health"}
