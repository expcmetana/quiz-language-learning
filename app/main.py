from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db import SessionLocal
from app.routers import blocks, decks, profiles, stats, study
from app.seed import seed_blocks, seed_if_empty

BASE_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    alembic_cfg = AlembicConfig(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "alembic"))
    alembic_command.upgrade(alembic_cfg, "head")
    with SessionLocal() as db:
        seed_blocks(db, settings.seed_dir)
        # Legacy fallback: seed the starter vocab deck when no blocks manifest ran.
        seed_if_empty(db, settings.seed_csv)
    yield


app = FastAPI(title="ES-RU Trainer", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

app.include_router(profiles.router)
app.include_router(blocks.router)
app.include_router(decks.router)
app.include_router(study.router)
app.include_router(stats.router)


@app.get("/")
def index(request: Request):
    if request.cookies.get("profile_id"):
        return RedirectResponse("/dashboard")
    return RedirectResponse("/profiles")
