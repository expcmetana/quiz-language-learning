"""Test harness.

DB isolation strategy
---------------------
`app.config.settings` and `app.db.engine` are built at import time, so the
target database is fixed the moment `app.db` is first imported. We therefore
point DATABASE_PATH (and the other env knobs) at a throwaway temp file *here*,
at conftest import time, which pytest guarantees runs before any test module is
imported. Project root is also injected onto sys.path so `import app` resolves
(conftest lives in tests/, which is the only dir pytest puts on the path).

Because the SQLite file is a single shared engine for the whole session, we get
isolation by wiping every table and re-seeding before each test (function-scoped
autouse `reset_db`). Re-seeding is cheap (~200 rows) and gives every test the
canonical seeded deck + words with a clean profile/card_state/review_log slate.
The schema itself is created once, by running the app lifespan (alembic upgrade)
in the session-scoped `_schema` fixture.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# --- must happen before any `app` import ---------------------------------
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

_TMPDIR = tempfile.mkdtemp(prefix="quiz-test-")
os.environ["DATABASE_PATH"] = str(Path(_TMPDIR) / "test.db")
os.environ["SEED_CSV"] = str(_ROOT / "seed" / "es_ru_basic.csv")
os.environ["NEW_CARDS_PER_DAY"] = "10"
os.environ["SESSION_SIZE"] = "20"
# -------------------------------------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import CardState, Deck, Profile, ReviewLog, Word  # noqa: E402
from app.routers import study  # noqa: E402
from app.seed import SEED_DECK_NAME, seed_if_empty  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema():
    """Run the app lifespan once so alembic creates the schema."""
    with TestClient(app):
        pass
    yield


@pytest.fixture(autouse=True)
def reset_db():
    """Clean slate + fresh seed before every test."""
    study._sessions.clear()
    with SessionLocal() as db:
        for tbl in (ReviewLog, CardState, Profile, Word, Deck):
            db.execute(delete(tbl))
        db.commit()
        seed_if_empty(db, settings.seed_csv)
    yield


@pytest.fixture
def db():
    """A raw SQLAlchemy session for DB-backed unit tests."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    """Fresh TestClient (own cookie jar) sharing the session-wide engine.

    No context manager => lifespan is not re-run (schema already exists).
    """
    return TestClient(app)


@pytest.fixture
def make_client():
    """Factory: TestClient optionally pre-registered with a profile cookie."""
    def _make(profile_name: str | None = None) -> TestClient:
        c = TestClient(app)
        if profile_name is not None:
            c.post("/profiles", data={"name": profile_name})
        return c
    return _make


# --- data helpers --------------------------------------------------------

@pytest.fixture
def seed_deck(db):
    from sqlalchemy import select

    return db.execute(select(Deck).where(Deck.name == SEED_DECK_NAME)).scalar_one()


@pytest.fixture
def make_deck(db):
    def _make(name: str, words: list[tuple[str, str]] | None = None) -> Deck:
        deck = Deck(name=name, description="")
        db.add(deck)
        db.flush()
        for es, ru in (words or []):
            db.add(Word(deck_id=deck.id, es=es, ru=ru))
        db.commit()
        db.refresh(deck)
        return deck
    return _make


@pytest.fixture
def make_profile(db):
    def _make(name: str = "tester", new_cards_per_day: int = 10) -> Profile:
        p = Profile(name=name, new_cards_per_day=new_cards_per_day)
        db.add(p)
        db.commit()
        db.refresh(p)
        return p
    return _make
