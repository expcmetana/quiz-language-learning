from datetime import datetime, timezone

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select

from app.deps import CurrentProfile, DbSession, templates
from app.models import CardState, Deck, Exercise, ExerciseState, Profile, ReviewLog, Word

router = APIRouter()

LEVEL_ORDER = {"A1": 0, "A2": 1, "B1": 2, "B2": 3}


def block_stats(db, profile_id: int, deck: Deck, now: datetime) -> dict:
    """Per-profile counters for one learning block (vocab deck or exercise deck)."""
    if deck.kind == "vocab":
        total = db.scalar(select(func.count()).select_from(Word).where(Word.deck_id == deck.id)) or 0
        started = db.scalar(
            select(func.count())
            .select_from(CardState)
            .join(Word, Word.id == CardState.word_id)
            .where(CardState.profile_id == profile_id, Word.deck_id == deck.id)
        ) or 0
        due = db.scalar(
            select(func.count())
            .select_from(CardState)
            .join(Word, Word.id == CardState.word_id)
            .where(CardState.profile_id == profile_id, Word.deck_id == deck.id, CardState.due_at <= now)
        ) or 0
    else:
        total = db.scalar(select(func.count()).select_from(Exercise).where(Exercise.deck_id == deck.id)) or 0
        started = db.scalar(
            select(func.count())
            .select_from(ExerciseState)
            .join(Exercise, Exercise.id == ExerciseState.exercise_id)
            .where(ExerciseState.profile_id == profile_id, Exercise.deck_id == deck.id)
        ) or 0
        due = db.scalar(
            select(func.count())
            .select_from(ExerciseState)
            .join(Exercise, Exercise.id == ExerciseState.exercise_id)
            .where(
                ExerciseState.profile_id == profile_id,
                Exercise.deck_id == deck.id,
                ExerciseState.due_at <= now,
            )
        ) or 0
    return {"deck": deck, "total": total, "started": started, "due": due, "kind": deck.kind, "level": deck.level}


@router.get("/profiles")
def profile_picker(request: Request, db: DbSession):
    profiles = db.execute(select(Profile).order_by(Profile.name)).scalars().all()
    return templates.TemplateResponse(request, "profiles.html", {"profiles": profiles})


@router.post("/profiles")
def create_profile(db: DbSession, name: str = Form(...)):
    name = name.strip()
    if name and db.scalar(select(Profile.id).where(Profile.name == name)) is None:
        profile = Profile(name=name)
        db.add(profile)
        db.commit()
        resp = RedirectResponse("/dashboard", status_code=303)
        resp.set_cookie("profile_id", str(profile.id), max_age=365 * 24 * 3600)
        return resp
    return RedirectResponse("/profiles", status_code=303)


@router.post("/profiles/{profile_id}/select")
def select_profile(profile_id: int, db: DbSession):
    if db.get(Profile, profile_id) is None:
        return RedirectResponse("/profiles", status_code=303)
    resp = RedirectResponse("/dashboard", status_code=303)
    resp.set_cookie("profile_id", str(profile_id), max_age=365 * 24 * 3600)
    return resp


@router.post("/profiles/logout")
def logout():
    resp = RedirectResponse("/profiles", status_code=303)
    resp.delete_cookie("profile_id")
    return resp


@router.get("/dashboard")
def dashboard(request: Request, db: DbSession, profile: CurrentProfile):
    now = datetime.now(timezone.utc)
    decks = db.execute(select(Deck).order_by(Deck.name)).scalars().all()

    blocks = [block_stats(db, profile.id, deck, now) for deck in decks]
    blocks.sort(key=lambda b: (b["kind"], LEVEL_ORDER.get(b["level"], 99), b["deck"].name))

    # Legacy key, kept until the UI agent switches the template to `blocks`.
    deck_stats = [{k: b[k] for k in ("deck", "total", "started", "due")} for b in blocks]

    reviews_today = db.scalar(
        select(func.count())
        .select_from(ReviewLog)
        .where(
            ReviewLog.profile_id == profile.id,
            func.date(ReviewLog.answered_at) == now.date().isoformat(),
        )
    ) or 0

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"profile": profile, "blocks": blocks, "deck_stats": deck_stats, "reviews_today": reviews_today},
    )
