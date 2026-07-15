import csv
import io
from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.deps import CurrentProfile, DbSession, templates
from app.models import Deck, Word

router = APIRouter(prefix="/decks")


def _get_deck(db, deck_id: int) -> Deck:
    deck = db.get(Deck, deck_id, options=[selectinload(Deck.words)])
    # Exercise decks (tenses/gap) are driven by the Exercise table and managed via
    # the seed pipeline / /blocks, not this vocab editor. Present them as not found
    # so users can't add orphan Word rows to them.
    if deck is None or deck.kind != "vocab":
        raise HTTPException(404, "Deck not found")
    return deck


@router.get("")
def list_decks(request: Request, db: DbSession, profile: CurrentProfile):
    decks = db.execute(
        select(Deck)
        .where(Deck.kind == "vocab")
        .options(selectinload(Deck.words))
        .order_by(Deck.name)
    ).scalars().all()
    return templates.TemplateResponse(request, "decks.html", {"profile": profile, "decks": decks})


@router.post("")
def create_deck(db: DbSession, profile: CurrentProfile, name: str = Form(...), description: str = Form("")):
    name = name.strip()
    if name and db.scalar(select(Deck.id).where(Deck.name == name)) is None:
        deck = Deck(name=name, description=description.strip())
        db.add(deck)
        db.commit()
        return RedirectResponse(f"/decks/{deck.id}", status_code=303)
    return RedirectResponse("/decks", status_code=303)


@router.get("/{deck_id}")
def deck_detail(deck_id: int, request: Request, db: DbSession, profile: CurrentProfile):
    deck = _get_deck(db, deck_id)
    return templates.TemplateResponse(request, "deck_detail.html", {"profile": profile, "deck": deck})


@router.post("/{deck_id}/delete")
def delete_deck(deck_id: int, db: DbSession, profile: CurrentProfile):
    deck = _get_deck(db, deck_id)
    db.delete(deck)
    db.commit()
    return RedirectResponse("/decks", status_code=303)


@router.post("/{deck_id}/words")
def add_word(
    deck_id: int,
    db: DbSession,
    profile: CurrentProfile,
    es: str = Form(...),
    ru: str = Form(...),
    example: str = Form(""),
):
    deck = _get_deck(db, deck_id)
    es, ru = es.strip(), ru.strip()
    exists = db.scalar(select(Word.id).where(Word.deck_id == deck.id, Word.es == es, Word.ru == ru))
    if es and ru and exists is None:
        db.add(Word(deck_id=deck.id, es=es, ru=ru, example=example.strip() or None))
        db.commit()
    return RedirectResponse(f"/decks/{deck_id}", status_code=303)


@router.post("/{deck_id}/words/{word_id}/delete")
def delete_word(deck_id: int, word_id: int, db: DbSession, profile: CurrentProfile):
    deck = _get_deck(db, deck_id)
    word = db.get(Word, word_id)
    if word and word.deck_id == deck.id:
        db.delete(word)
        db.commit()
    return RedirectResponse(f"/decks/{deck_id}", status_code=303)


@router.post("/{deck_id}/import")
async def import_csv(deck_id: int, db: DbSession, profile: CurrentProfile, file: UploadFile):
    deck = _get_deck(db, deck_id)
    content = (await file.read()).decode("utf-8-sig")
    existing = {
        (w.es, w.ru) for w in deck.words
    }
    added = 0
    reader = csv.DictReader(io.StringIO(content))
    if reader.fieldnames is None or "es" not in reader.fieldnames or "ru" not in reader.fieldnames:
        raise HTTPException(400, "CSV must have header: es,ru[,example]")
    for row in reader:
        es, ru = (row.get("es") or "").strip(), (row.get("ru") or "").strip()
        if not es or not ru or (es, ru) in existing:
            continue
        existing.add((es, ru))
        db.add(Word(deck_id=deck.id, es=es, ru=ru, example=(row.get("example") or "").strip() or None))
        added += 1
    db.commit()
    return RedirectResponse(f"/decks/{deck_id}?imported={added}", status_code=303)


@router.get("/{deck_id}/export")
def export_csv(deck_id: int, db: DbSession, profile: CurrentProfile):
    deck = _get_deck(db, deck_id)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["es", "ru", "example"])
    for w in deck.words:
        writer.writerow([w.es, w.ru, w.example or ""])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="deck-{deck.id}.csv"; '
                f"filename*=UTF-8''{quote(deck.name)}.csv"
            )
        },
    )
