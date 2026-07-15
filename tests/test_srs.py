"""Pure SM-2 unit tests (no DB)."""

from datetime import datetime, timedelta, timezone

import pytest

from app import srs
from app.srs import MIN_EASE, SrsState, levenshtein, review


NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)


def _ease_after(q: int, ef: float = 2.5) -> float:
    return max(MIN_EASE, ef + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)))


def test_canonical_sequence_grade4():
    # grade 4 keeps ease at 2.5 and walks intervals 1 -> 6 -> prev*ease
    state = SrsState()
    state, due = review(state, 4, NOW)
    assert state.repetitions == 1
    assert state.interval_days == 1.0
    assert state.ease_factor == pytest.approx(2.5)
    assert due == NOW + timedelta(days=1.0)

    state, due = review(state, 4, NOW)
    assert state.repetitions == 2
    assert state.interval_days == 6.0
    assert due == NOW + timedelta(days=6.0)

    prev = state.interval_days
    state, due = review(state, 4, NOW)
    assert state.repetitions == 3
    assert state.interval_days == pytest.approx(prev * 2.5)  # 15.0
    assert state.interval_days == pytest.approx(15.0)

    prev = state.interval_days
    state, _ = review(state, 4, NOW)
    assert state.interval_days == pytest.approx(prev * 2.5)  # 37.5


def test_ease_formula_grade5_and_grade3():
    # EF' = EF + (0.1 - (5-q)*(0.08+(5-q)*0.02))
    s5, _ = review(SrsState(), 5, NOW)
    assert s5.ease_factor == pytest.approx(2.6)  # +0.1
    s3, _ = review(SrsState(), 3, NOW)
    assert s3.ease_factor == pytest.approx(2.36)  # -0.14


def test_failure_resets_and_requeues():
    prior = SrsState(ease_factor=2.5, interval_days=15.0, repetitions=3, lapses=0)
    new, due = review(prior, 2, NOW)
    assert new.repetitions == 0
    assert new.interval_days == 0.0
    assert new.lapses == 1
    assert due == NOW + timedelta(minutes=10)


def test_ease_never_below_min():
    state = SrsState(ease_factor=MIN_EASE)
    for _ in range(5):
        state, _ = review(state, 0, NOW)
        assert state.ease_factor >= MIN_EASE
    assert state.ease_factor == MIN_EASE


@pytest.mark.parametrize("bad", [-1, 6, 7, 100])
def test_grade_out_of_bounds_raises(bad):
    with pytest.raises(ValueError):
        review(SrsState(), bad, NOW)


def test_grade_typed_exact_case_and_whitespace_insensitive():
    assert srs.grade_typed("Привет", "привет") == 5
    assert srs.grade_typed("  ПРИВЕТ  ", "привет") == 5
    assert srs.grade_typed("hola   mundo", "hola mundo") == 5


def test_grade_typed_one_typo():
    assert srs.grade_typed("privet", "prive") == 3  # one insertion
    assert srs.grade_typed("приветт", "привет") == 3  # one extra char


def test_grade_typed_wrong():
    assert srs.grade_typed("completely off", "привет") == 0


def test_grade_multiple_choice():
    assert srs.grade_multiple_choice(True) == 4
    assert srs.grade_multiple_choice(False) == 1


def test_grade_match():
    assert srs.grade_match(True) == 4
    # A miss is a real SRS failure (<3): lapses the card and resets the interval.
    assert srs.grade_match(False) == 1
    assert srs.grade_match(False) < 3


@pytest.mark.parametrize(
    "a,b,expected",
    [
        ("", "", 0),
        ("abc", "abc", 0),
        ("", "abc", 3),
        ("kitten", "sitting", 3),
        ("flaw", "lawn", 2),
        ("privet", "prive", 1),
    ],
)
def test_levenshtein(a, b, expected):
    assert levenshtein(a, b) == expected
