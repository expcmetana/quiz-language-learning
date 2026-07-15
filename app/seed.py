import csv
import json
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Deck, Exercise, Word

logger = logging.getLogger(__name__)

SEED_DECK_NAME = "Básico ES-RU"


def seed_if_empty(db: Session, csv_path: Path) -> None:
    """Legacy vocab seeder: create the starter deck from a single CSV if the DB has no decks."""
    if db.scalar(select(Deck.id).limit(1)) is not None:
        return
    if not csv_path.exists():
        return
    deck = Deck(name=SEED_DECK_NAME, description="Стартовый набор частотных испанских слов")
    db.add(deck)
    db.flush()
    _load_vocab(db, deck, csv_path)
    db.commit()


def seed_blocks(db: Session, seed_dir: Path) -> None:
    """Idempotent block seeder driven by ``seed_dir/blocks.json``.

    Manifest is an array of {"name", "kind", "level", "file", "description"}.
    For each entry whose deck name is not already in the DB, create the deck and
    load rows from its file. Entries with a missing file are skipped (logged),
    so a content agent still writing files never crashes startup.
    """
    manifest_path = seed_dir / "blocks.json"
    if not manifest_path.exists():
        logger.info("seed_blocks: no manifest at %s, skipping", manifest_path)
        return

    try:
        entries = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("seed_blocks: cannot read manifest %s: %s", manifest_path, exc)
        return

    existing = set(db.scalars(select(Deck.name)).all())
    for entry in entries:
        name = (entry.get("name") or "").strip()
        kind = (entry.get("kind") or "vocab").strip()
        level = (entry.get("level") or None)
        file_name = (entry.get("file") or "").strip()
        description = (entry.get("description") or "").strip()

        if not name or name in existing:
            continue
        if not file_name:
            logger.warning("seed_blocks: entry %r has no file, skipping", name)
            continue
        path = seed_dir / file_name
        if not path.exists():
            logger.warning("seed_blocks: file %s for deck %r missing, skipping", path, name)
            continue

        deck = Deck(name=name, description=description, kind=kind, level=level)
        db.add(deck)
        db.flush()
        try:
            if kind == "vocab":
                _load_vocab(db, deck, path)
            elif kind == "tenses":
                _load_tenses(db, deck, path)
            elif kind == "gap":
                _load_gap(db, deck, path)
            else:
                logger.warning("seed_blocks: unknown kind %r for deck %r, skipping", kind, name)
                db.rollback()  # undo the flushed INSERT for this deck
                continue
        except (KeyError, OSError) as exc:
            logger.warning("seed_blocks: failed loading %s for deck %r: %s", path, name, exc)
            db.rollback()
            continue

        db.commit()  # commit this deck now so a later failure can't roll it back
        existing.add(name)
        logger.info("seed_blocks: created deck %r (kind=%s, level=%s)", name, kind, level)


def _load_vocab(db: Session, deck: Deck, path: Path) -> None:
    with path.open(newline="", encoding="utf-8-sig") as f:
        seen: set[tuple[str, str]] = set()
        for row in csv.DictReader(f):
            es, ru = (row.get("es") or "").strip(), (row.get("ru") or "").strip()
            if not es or not ru or (es, ru) in seen:
                continue
            seen.add((es, ru))
            db.add(Word(deck_id=deck.id, es=es, ru=ru, example=(row.get("example") or "").strip() or None))


def _load_tenses(db: Session, deck: Deck, path: Path) -> None:
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            verb = (row.get("verb") or "").strip()
            tense = (row.get("tense") or "").strip()
            person = (row.get("person") or "").strip()
            answer = (row.get("answer") or "").strip()
            if not verb or not answer:
                continue
            db.add(
                Exercise(
                    deck_id=deck.id,
                    type="conj",
                    prompt=f"{verb} · {tense} · {person}",
                    answer=answer,
                    choices=(row.get("choices") or "").strip() or None,
                    hint=(row.get("hint") or "").strip() or None,
                )
            )


def _load_gap(db: Session, deck: Deck, path: Path) -> None:
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            sentence = (row.get("sentence") or "").strip()
            answer = (row.get("answer") or "").strip()
            if not sentence or not answer:
                continue
            db.add(
                Exercise(
                    deck_id=deck.id,
                    type="gap",
                    prompt=sentence,
                    answer=answer,
                    choices=(row.get("choices") or "").strip() or None,
                    hint=(row.get("hint") or "").strip() or None,
                )
            )
