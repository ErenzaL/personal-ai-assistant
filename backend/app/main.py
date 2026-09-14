import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat, conversations, health, memories, settings as settings_api, tasks
from app.config import get_settings
from app.database import init_database
from app.services.llm import close_llm_service

# Uvicorn only configures its own loggers; make the app's INFO lines visible too.
logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(message)s")
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
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(chat.router)
app.include_router(conversations.router)
app.include_router(memories.router)
app.include_router(settings_api.router)
app.include_router(tasks.router)
