from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from sqlalchemy import case, func, select

from app.deps import CurrentProfile, DbSession, templates
from app.models import CardState, Exercise, ExerciseState, ReviewLog, Word

router = APIRouter()

MODE_LABELS = {
    "flashcards": "Флэш-карты",
    "choice": "Выбор варианта",
    "typed": "Написать перевод",
    "match": "Найти пары",
}


@router.get("/stats")
def stats(request: Request, db: DbSession, profile: CurrentProfile):
    now = datetime.now(timezone.utc)
    today = now.date()
    since = today - timedelta(days=29)

    # (a) reviews per day, last 30 days
    day = func.date(ReviewLog.answered_at)
    rows = db.execute(
        select(
            day.label("d"),
            func.count().label("count"),
            func.sum(case((ReviewLog.grade >= 3, 1), else_=0)).label("correct"),
        )
        .where(ReviewLog.profile_id == profile.id, day >= since.isoformat())
        .group_by(day)
    ).all()
    by_day = {r.d: (r.count, r.correct or 0) for r in rows}

    per_day = []
    for i in range(30):
        d = since + timedelta(days=i)
        key = d.isoformat()
        count, correct = by_day.get(key, (0, 0))
        accuracy = (correct / count) if count else 0.0
        per_day.append({"date": d, "count": count, "accuracy": accuracy})
    max_count = max((p["count"] for p in per_day), default=0)

    # (b) accuracy by mode
    mode_rows = db.execute(
        select(
            ReviewLog.mode,
            func.count().label("count"),
            func.sum(case((ReviewLog.grade >= 3, 1), else_=0)).label("correct"),
        )
        .where(ReviewLog.profile_id == profile.id)
        .group_by(ReviewLog.mode)
    ).all()
    by_mode = []
    for m in mode_rows:
        by_mode.append(
            {
                "mode": m.mode,
                "label": MODE_LABELS.get(m.mode, m.mode),
                "count": m.count,
                "accuracy": (m.correct or 0) / m.count if m.count else 0.0,
            }
        )
    by_mode.sort(key=lambda x: x["count"], reverse=True)

    # (c) hardest words: top 10 by lapses desc, lapses > 0
    hardest_rows = db.execute(
        select(Word, CardState.lapses)
        .join(CardState, CardState.word_id == Word.id)
        .where(CardState.profile_id == profile.id, CardState.lapses > 0)
        .order_by(CardState.lapses.desc())
        .limit(10)
    ).all()
    hardest = [{"word": w, "lapses": lapses} for w, lapses in hardest_rows]

    # (d) hardest exercises: top 10 by lapses desc, lapses > 0
    hardest_ex_rows = db.execute(
        select(Exercise, ExerciseState.lapses)
        .join(ExerciseState, ExerciseState.exercise_id == Exercise.id)
        .where(ExerciseState.profile_id == profile.id, ExerciseState.lapses > 0)
        .order_by(ExerciseState.lapses.desc())
        .limit(10)
    ).all()
    hardest_ex = [{"exercise": e, "lapses": lapses} for e, lapses in hardest_ex_rows]

    total_reviews = sum(p["count"] for p in per_day)

    return templates.TemplateResponse(
        request,
        "stats.html",
        {
            "profile": profile,
            "per_day": per_day,
            "max_count": max_count,
            "by_mode": by_mode,
            "hardest": hardest,
            "hardest_ex": hardest_ex,
            "total_reviews": total_reviews,
        },
    )
