"""SM-2 spaced repetition, pure functions.

Grades follow the classic 0-5 scale:
  0-2 = failure (card lapses, interval resets), 3-5 = success.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

MIN_EASE = 1.3
DEFAULT_EASE = 2.5


@dataclass(frozen=True)
class SrsState:
    ease_factor: float = DEFAULT_EASE
    interval_days: float = 0.0
    repetitions: int = 0
    lapses: int = 0


def review(state: SrsState, grade: int, now: datetime | None = None) -> tuple[SrsState, datetime]:
    """Apply one review with SM-2. Returns (new state, next due datetime)."""
    if not 0 <= grade <= 5:
        raise ValueError(f"grade must be 0-5, got {grade}")
    now = now or datetime.now(timezone.utc)

    ease = state.ease_factor + (0.1 - (5 - grade) * (0.08 + (5 - grade) * 0.02))
    ease = max(MIN_EASE, ease)

    if grade < 3:
        new = SrsState(
            ease_factor=ease,
            interval_days=0.0,
            repetitions=0,
            lapses=state.lapses + 1,
        )
        # Failed card comes back within the same session window.
        return new, now + timedelta(minutes=10)

    if state.repetitions == 0:
        interval = 1.0
    elif state.repetitions == 1:
        interval = 6.0
    else:
        interval = state.interval_days * ease

    new = SrsState(
        ease_factor=ease,
        interval_days=interval,
        repetitions=state.repetitions + 1,
        lapses=state.lapses,
    )
    return new, now + timedelta(days=interval)


def grade_multiple_choice(correct: bool) -> int:
    return 4 if correct else 1


def grade_typed(answer: str, expected: str) -> int:
    a, e = _normalize(answer), _normalize(expected)
    if a == e:
        return 5
    if levenshtein(a, e) <= 1:
        return 3
    return 0


def grade_match(correct: bool) -> int:
    # Matching right is easy, so never a strong "easy" grade. A miss is a real
    # failure: grade 1 (<3) lapses the card, resets the interval, and requeues it,
    # consistent with grade_multiple_choice's wrong=1.
    return 4 if correct else 1


def _normalize(s: str) -> str:
    return " ".join(s.lower().strip().split())


def levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]
