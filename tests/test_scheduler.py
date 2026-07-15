"""DB-backed scheduler unit tests (use SessionLocal directly via `db`)."""

from datetime import datetime, timedelta, timezone

from app.models import CardState
from app.scheduler import (
    build_session,
    pick_distractors,
)

NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)


def _deck(make_deck, n=15):
    words = [(f"es{i}", f"ru{i}") for i in range(n)]
    return make_deck("Scheduler Deck", words)


def test_new_words_fill_up_to_available(db, make_deck, make_profile):
    deck = _deck(make_deck, n=15)
    profile = make_profile("sched")

    words = build_session(db, profile, deck.id, limit=20, now=NOW)

    assert len(words) == 15  # all available new words, no daily cap
    assert all(w.deck_id == deck.id for w in words)


def test_new_words_capped_by_limit(db, make_deck, make_profile):
    deck = _deck(make_deck, n=15)
    profile = make_profile("sched")

    words = build_session(db, profile, deck.id, limit=3, now=NOW)
    assert len(words) == 3


def test_due_cards_first_most_overdue_first(db, make_deck, make_profile):
    deck = _deck(make_deck, n=15)
    profile = make_profile("sched")
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


def test_cards_introduced_today_do_not_starve_later_sessions(db, make_deck, make_profile):
    """No cross-session daily ceiling: items already introduced earlier today do not
    reduce how many new items a later session may add — the user can keep studying."""
    deck = _deck(make_deck, n=15)
    profile = make_profile("sched")
    ids = [w.id for w in deck.words]

    # Simulate an earlier session today that first-saw 10 words (not due again).
    for wid in ids[:10]:
        db.add(
            CardState(
                profile_id=profile.id,
                word_id=wid,
                first_seen_at=NOW,
                due_at=NOW + timedelta(days=5),
            )
        )
    db.commit()

    # A later session the same day still tops up with the remaining new words.
    words = build_session(db, profile, deck.id, limit=20, now=NOW)
    assert len(words) == 5  # the 5 words never seen, no daily budget subtraction
    assert all(w.id not in ids[:10] for w in words)


def test_repeated_sessions_keep_serving_fresh_new_words(db, make_deck, make_profile):
    """Two build_session calls in the same day both return fresh new items until the
    deck is genuinely exhausted — no artificial per-day starvation of the second call."""
    deck = _deck(make_deck, n=15)
    profile = make_profile("sched")

    first = build_session(db, profile, deck.id, limit=5, now=NOW)
    assert len(first) == 5
    # Record them as introduced (what a real session does on first sight).
    for w in first:
        db.add(CardState(profile_id=profile.id, word_id=w.id, first_seen_at=NOW, due_at=NOW + timedelta(days=5)))
    db.commit()

    second = build_session(db, profile, deck.id, limit=5, now=NOW)
    assert len(second) == 5  # second same-day session is NOT starved
    assert {w.id for w in second}.isdisjoint({w.id for w in first})  # a genuinely fresh batch


def test_session_empty_when_deck_fully_exhausted(db, make_deck, make_profile):
    """A session is empty only when the deck genuinely has no due items and no new
    (never-seen) items left — every word already seen and not yet due."""
    deck = _deck(make_deck, n=15)
    profile = make_profile("sched")
    for wid in [w.id for w in deck.words]:
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
