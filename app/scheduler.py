"""Builds study sessions: due cards first, then new cards up to the session size."""

import random
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CardState, Exercise, ExerciseState, Profile, Word


def build_session(
    db: Session,
    profile: Profile,
    deck_id: int,
    limit: int,
    now: datetime | None = None,
) -> list[Word]:
    """Return words to study: overdue cards (most overdue first), topped up with new words."""
    now = now or datetime.now(timezone.utc)

    due_rows = db.execute(
        select(Word)
        .join(CardState, CardState.word_id == Word.id)
        .where(
            CardState.profile_id == profile.id,
            Word.deck_id == deck_id,
            CardState.due_at <= now,
        )
        .order_by(CardState.due_at)
        .limit(limit)
    ).scalars().all()

    words = list(due_rows)

    new_slots = limit - len(words)
    if new_slots > 0:
        seen = select(CardState.word_id).where(CardState.profile_id == profile.id)
        new_words = db.execute(
            select(Word)
            .where(Word.deck_id == deck_id, Word.id.not_in(seen))
            .order_by(Word.id)
            .limit(new_slots)
        ).scalars().all()
        words.extend(new_words)

    return words


def build_exercise_session(
    db: Session,
    profile: Profile,
    deck_id: int,
    limit: int,
    now: datetime | None = None,
) -> list[Exercise]:
    """Return exercises to study: overdue first (most overdue first), topped up with new ones."""
    now = now or datetime.now(timezone.utc)

    due_rows = db.execute(
        select(Exercise)
        .join(ExerciseState, ExerciseState.exercise_id == Exercise.id)
        .where(
            ExerciseState.profile_id == profile.id,
            Exercise.deck_id == deck_id,
            ExerciseState.due_at <= now,
        )
        .order_by(ExerciseState.due_at)
        .limit(limit)
    ).scalars().all()

    exercises = list(due_rows)

    new_slots = limit - len(exercises)
    if new_slots > 0:
        seen = select(ExerciseState.exercise_id).where(ExerciseState.profile_id == profile.id)
        new_exercises = db.execute(
            select(Exercise)
            .where(Exercise.deck_id == deck_id, Exercise.id.not_in(seen))
            .order_by(Exercise.id)
            .limit(new_slots)
        ).scalars().all()
        exercises.extend(new_exercises)

    return exercises


def exercise_options(exercise: Exercise) -> list[str]:
    """Wrong options for choice mode come from the stored ";"-separated choices column."""
    if not exercise.choices:
        return []
    return [c.strip() for c in exercise.choices.split(";") if c.strip()]


def pick_distractors(db: Session, word: Word, count: int = 3) -> list[str]:
    """Wrong RU options from the same deck (falls back to any deck if too few)."""
    same_deck = db.execute(
        select(Word.ru).where(Word.deck_id == word.deck_id, Word.id != word.id, Word.ru != word.ru).distinct()
    ).scalars().all()
    pool = list(same_deck)
    if len(pool) < count:
        others = db.execute(
            select(Word.ru).where(Word.id != word.id, Word.ru != word.ru).distinct()
        ).scalars().all()
        pool = list({*pool, *others})
    # Accepted degenerate case: if the entire DB has no word with a different `ru`
    # than this one (e.g. a single-word database), the pool is empty and choice mode
    # shows only the correct answer. Not worth a fallback — it requires zero alternate
    # answers across all decks, which never happens with real seeded content.
    return random.sample(pool, min(count, len(pool)))
