from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import chat, execution, global_config, job_records, job_seek_tasks
from app.bootstrap import container
from app.config import settings
from app.infrastructure.database.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if settings.worker_autostart:
        await container.job_seek_execution.start()
    try:
        yield
    finally:
        await container.job_seek_execution.shutdown()
        await container.browser.shutdown()
        await container.close_llm()


WEB_DIR = Path(__file__).parent / "web"
STATIC_DIR = WEB_DIR / "static"

app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(chat.router, prefix="/api")
app.include_router(job_seek_tasks.router, prefix="/api")
app.include_router(job_records.router, prefix="/api")
app.include_router(execution.router, prefix="/api")
app.include_router(global_config.router, prefix="/api")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "llm_model": settings.llm_model,
        "worker_autostart": settings.worker_autostart,
        "execution": container.job_seek_execution.get_state().model_dump(),
        "agent_tools": container.registry.names(),
    }
