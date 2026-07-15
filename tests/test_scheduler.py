"""DB-backed scheduler unit tests (use SessionLocal directly via `db`)."""

from datetime import datetime, timedelta, timezone

from app.models import CardState
from app.scheduler import (
    build_session,
    new_cards_introduced_today,
    pick_distractors,
)

NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)


def _deck(make_deck, n=15):
    words = [(f"es{i}", f"ru{i}") for i in range(n)]
    return make_deck("Scheduler Deck", words)


def test_new_words_capped_by_new_cards_per_day(db, make_deck, make_profile):
    deck = _deck(make_deck, n=15)
    profile = make_profile("sched", new_cards_per_day=5)

    words = build_session(db, profile, deck.id, limit=20, now=NOW)

    assert len(words) == 5  # capped by new_cards_per_day, not by 15 available
    assert all(w.deck_id == deck.id for w in words)


def test_new_words_capped_by_limit(db, make_deck, make_profile):
    deck = _deck(make_deck, n=15)
    profile = make_profile("sched", new_cards_per_day=10)

    words = build_session(db, profile, deck.id, limit=3, now=NOW)
    assert len(words) == 3


def test_due_cards_first_most_overdue_first(db, make_deck, make_profile):
    deck = _deck(make_deck, n=15)
    profile = make_profile("sched", new_cards_per_day=10)
    ids = [w.id for w in deck.words]

    # Two overdue cards, different due_at; the older one must come first.
    less_overdue, more_overdue = ids[0], ids[1]
    db.add(CardState(profile_id=profile.id, word_id=less_overdue, due_at=NOW - timedelta(hours=1)))
    db.add(CardState(profile_id=profile.id, word_id=more_overdue, due_at=NOW - timedelta(days=3)))
    db.commit()

    words = build_session(db, profile, deck.id, limit=20, now=NOW)

    assert words[0].id == more_overdue
    assert words[1].id == less_overdue
    # due cards precede any topped-up new words
    assert {words[0].id, words[1].id} == {more_overdue, less_overdue}


def test_new_budget_shrinks_with_cards_introduced_today(db, make_deck, make_profile):
    deck = _deck(make_deck, n=15)
    profile = make_profile("sched", new_cards_per_day=10)
    ids = [w.id for w in deck.words]

    assert new_cards_introduced_today(db, profile.id, NOW) == 0

    # 4 cards first_seen today (not due -> due in the future so they don't reappear)
    for wid in ids[:4]:
        db.add(
            CardState(
                profile_id=profile.id,
                word_id=wid,
                first_seen_at=NOW,
                due_at=NOW + timedelta(days=5),
            )
        )
    db.commit()

    assert new_cards_introduced_today(db, profile.id, NOW) == 4

    words = build_session(db, profile, deck.id, limit=20, now=NOW)
    # budget = 10 - 4 = 6 new words (none due)
    assert len(words) == 6
    assert all(w.id not in ids[:4] for w in words)


def test_new_budget_zero_when_all_used_today(db, make_deck, make_profile):
    deck = _deck(make_deck, n=15)
    profile = make_profile("sched", new_cards_per_day=3)
    ids = [w.id for w in deck.words]
    for wid in ids[:3]:
        db.add(
            CardState(
                profile_id=profile.id,
                word_id=wid,
                first_seen_at=NOW,
                due_at=NOW + timedelta(days=5),
            )
        )
    db.commit()

    words = build_session(db, profile, deck.id, limit=20, now=NOW)
    assert words == []


def test_pick_distractors_count_and_excludes_own_ru(db, make_deck):
    deck = _deck(make_deck, n=15)
    word = deck.words[0]

    distractors = pick_distractors(db, word, count=3)
    assert len(distractors) == 3
    assert word.ru not in distractors


def test_pick_distractors_prefers_same_deck(db, make_deck):
    same = _deck(make_deck, n=15)
    make_deck("Other Deck", [(f"o{i}", f"otherru{i}") for i in range(15)])

    word = same.words[0]
    same_ru = {w.ru for w in same.words if w.id != word.id}
    distractors = pick_distractors(db, word, count=3)

    assert len(distractors) == 3
    assert all(d in same_ru for d in distractors)  # never fell back to other deck


def test_pick_distractors_falls_back_when_deck_too_small(db, make_deck):
    small = make_deck("Small", [("uno", "один"), ("dos", "два")])
    make_deck("Big", [(f"b{i}", f"bigru{i}") for i in range(10)])

    word = small.words[0]
    distractors = pick_distractors(db, word, count=3)
    assert len(distractors) == 3
    assert word.ru not in distractors
