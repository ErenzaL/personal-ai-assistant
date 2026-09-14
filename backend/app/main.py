import logging
import os
import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import chat, conversations, health, memories, settings as settings_api, tasks
from app.config import get_settings
from app.database import init_database
from app.services.llm import close_llm_service

# Uvicorn only configures its own loggers; make the app's lines visible too.
# The packaged app runs with DULLY_LOG_LEVEL=WARNING, so its log stays small.
logging.basicConfig(
    level=os.environ.get("DULLY_LOG_LEVEL", "INFO").upper(),
    format="%(levelname)s:     %(message)s",
)
log = logging.getLogger("app")

# Origins the desktop app's webview uses. The backend only ever listens on
# 127.0.0.1, so this is about letting the webview read responses, not about
# exposing anything to the network.
ALLOWED_ORIGINS = [
    "http://localhost:1420",  # Vite dev server loaded by `tauri dev`
    "http://127.0.0.1:1420",
    "tauri://localhost",  # packaged app on macOS (WKWebView custom scheme)
    "http://tauri.localhost",  # packaged app on Windows
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    key_present = {
        "gemini": settings.gemini_api_key is not None,
        "groq": settings.groq_api_key is not None,
    }.get(settings.llm_provider, False)
    # Logs whether a key exists, never the key itself.
    log.info("LLM provider: %s (API key %s)", settings.llm_provider, "set" if key_present else "MISSING")
    init_database(settings.database_path)
    log.info("database: %s", settings.database_path)
    yield
    await close_llm_service()


app = FastAPI(title="Personal AI Assistant API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Accept"],
)


# Failures the UI cannot do anything about still get a short, plain answer.
# The traceback goes to the server log only, never into a response.
@app.exception_handler(sqlite3.Error)
async def _database_error(_: Request, exc: sqlite3.Error) -> JSONResponse:
    log.error("database error: %s", type(exc).__name__)
    return JSONResponse(
        status_code=503,
        content={"detail": {"code": "database", "message": "The local database is not available right now. Please try again in a moment."}},
    )


@app.exception_handler(Exception)
async def _unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error: %s", type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content={"detail": {"code": "internal", "message": "Something went wrong on Dully's side. Please try again."}},
    )

app.include_router(health.router)
app.include_router(chat.router)
app.include_router(conversations.router)
app.include_router(memories.router)
app.include_router(settings_api.router)
app.include_router(tasks.router)
