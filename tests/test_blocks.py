"""Learning-blocks feature: seeding, exercise scheduler, study API, dashboard, stats.

Seeding strategy
----------------
conftest's `reset_db` re-seeds ONLY the legacy vocab deck (`seed_if_empty`), so the
canonical clean slate has no exercise decks. Re-seeding the real 1800-item blocks
manifest on every test would be slow and coupled to shifting content files, so we
build a *minimal* blocks manifest in a tmp dir (`blocks_dir`) and drive
`seed_blocks` against it. That keeps this module hermetic and fast while exercising
the exact same code path as production startup.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import app
from app.models import CardState, Deck, Exercise, ExerciseState, ReviewLog, Word
from app.routers import study
from app.scheduler import (
    build_exercise_session,
    build_session,
    exercise_options,
    new_cards_introduced_today,
)
from app.seed import seed_blocks

NOW = None  # scheduler defaults to datetime.now(utc); block tests don't pin time


# --- minimal seed manifest ----------------------------------------------

CONJ_ROWS = [
    ("hablar", "Presente", "yo", "hablo", "hablas;habla;hablamos", "я говорю"),
    ("hablar", "Presente", "tú", "hablas", "hablo;habla;habláis", "ты говоришь"),
    ("comer", "Presente", "yo", "como", "comes;come;comemos", "я ем"),
    ("comer", "Presente", "tú", "comes", "como;come;coméis", "ты ешь"),
    ("vivir", "Presente", "yo", "vivo", "vives;vive;vivimos", "я живу"),
    ("vivir", "Presente", "tú", "vives", "vivo;vive;vivís", "ты живёшь"),
    ("ser", "Presente", "yo", "soy", "eres;es;somos", "я есть"),
    ("estar", "Presente", "yo", "estoy", "estás;está;estamos", "я нахожусь"),
    ("tener", "Presente", "yo", "tengo", "tienes;tiene;tenemos", "у меня есть"),
    ("ir", "Presente", "yo", "voy", "vas;va;vamos", "я иду"),
    ("hacer", "Presente", "yo", "hago", "haces;hace;hacemos", "я делаю"),
    ("poder", "Presente", "yo", "puedo", "puedes;puede;podemos", "я могу"),
]

GAP_ROWS = [
    ("Yo ___ estudiante.", "soy", "estoy;eres;está", "Я студент."),
    ("Ella ___ muy cansada hoy.", "está", "es;soy;están", "Она уставшая."),
    ("Nosotros ___ en Madrid.", "estamos", "somos;están;es", "Мы в Мадриде."),
    ("___ un libro en la mesa.", "Hay", "Está;Es;Son", "На столе книга."),
    ("Ellos ___ profesores.", "son", "están;es;soy", "Они учителя."),
    ("Tú ___ mi amigo.", "eres", "estás;es;soy", "Ты мой друг."),
]

VOCAB_ROWS = [
    ("uno", "один", "Tengo uno."),
    ("dos", "два", "Dos casas."),
    ("tres", "три", "Tres gatos."),
    ("cuatro", "четыре", ""),
    ("cinco", "пять", ""),
    ("seis", "шесть", ""),
    ("siete", "семь", ""),
    ("ocho", "восемь", ""),
]


@pytest.fixture
def blocks_dir(tmp_path):
    """A minimal blocks seed dir: one vocab, one tenses, one gap deck + a bad entry."""
    (tmp_path / "conj.csv").write_text(
        "verb,tense,person,answer,choices,hint\n"
        + "\n".join(",".join(r) for r in CONJ_ROWS)
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "gap.csv").write_text(
        "sentence,answer,choices,hint\n"
        + "\n".join(",".join(r) for r in GAP_ROWS)
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "vocab.csv").write_text(
        "es,ru,example\n" + "\n".join(",".join(r) for r in VOCAB_ROWS) + "\n",
        encoding="utf-8",
    )
    manifest = [
        {"name": "TB Vocab", "kind": "vocab", "level": "A1", "file": "vocab.csv", "description": "тест-слова"},
        {"name": "TB Tenses", "kind": "tenses", "level": "A1", "file": "conj.csv", "description": "тест-спряжение"},
        {"name": "TB Gap", "kind": "gap", "level": "A2", "file": "gap.csv", "description": "тест-пропуски"},
        # entry whose file does not exist -> must be skipped without crashing
        {"name": "TB Missing", "kind": "vocab", "level": None, "file": "nope.csv", "description": ""},
    ]
    (tmp_path / "blocks.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return tmp_path


@pytest.fixture
def blocks(db, blocks_dir):
    """Seed the minimal manifest into the shared DB and return decks keyed by kind."""
    seed_blocks(db, blocks_dir)
    db.commit()
    rows = db.execute(select(Deck).where(Deck.name.like("TB %"))).scalars().all()
    by_kind = {d.kind: d for d in rows}
    return by_kind


def _deck_id(db, name):
    return db.scalar(select(Deck.id).where(Deck.name == name))


# --- 1. seed_blocks ------------------------------------------------------

def test_seed_blocks_creates_decks_and_skips_missing_file(db, blocks_dir):
    seed_blocks(db, blocks_dir)
    db.commit()
    names = set(db.scalars(select(Deck.name)).all())
    assert {"TB Vocab", "TB Tenses", "TB Gap"} <= names
    assert "TB Missing" not in names  # missing file entry skipped, no crash


def test_seed_blocks_idempotent(db, blocks_dir):
    seed_blocks(db, blocks_dir)
    db.commit()
    decks_1 = db.scalar(select(func.count()).select_from(Deck))
    ex_1 = db.scalar(select(func.count()).select_from(Exercise))

    seed_blocks(db, blocks_dir)  # second call must add nothing
    db.commit()
    decks_2 = db.scalar(select(func.count()).select_from(Deck))
    ex_2 = db.scalar(select(func.count()).select_from(Exercise))

    assert decks_1 == decks_2
    assert ex_1 == ex_2


def test_seed_blocks_missing_manifest_no_crash(db, tmp_path):
    # empty dir -> no blocks.json -> returns quietly
    seed_blocks(db, tmp_path)
    db.commit()  # nothing to commit, but must not raise


def test_seed_blocks_conj_row_builds_conj_exercise(db, blocks):
    ex = db.execute(
        select(Exercise).where(Exercise.deck_id == blocks["tenses"].id).order_by(Exercise.id)
    ).scalars().first()
    assert ex.type == "conj"
    assert ex.prompt == "hablar · Presente · yo"
    assert ex.answer == "hablo"
    assert ex.choices == "hablas;habla;hablamos"


def test_seed_blocks_gap_row_builds_gap_exercise(db, blocks):
    ex = db.execute(
        select(Exercise).where(Exercise.deck_id == blocks["gap"].id).order_by(Exercise.id)
    ).scalars().first()
    assert ex.type == "gap"
    assert ex.prompt == "Yo ___ estudiante."
    assert ex.answer == "soy"


# --- 2. scheduler --------------------------------------------------------

def test_build_exercise_session_returns_new_up_to_budget(db, blocks, make_profile):
    profile = make_profile("ex-budget", new_cards_per_day=5)
    exs = build_exercise_session(db, profile, blocks["tenses"].id, limit=20)
    assert len(exs) == 5  # capped by daily new-item budget, not the 12 available
    assert all(e.deck_id == blocks["tenses"].id for e in exs)


def test_build_exercise_session_due_first_ordering(db, blocks, make_profile):
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)
    profile = make_profile("ex-order", new_cards_per_day=10)
    ex_ids = db.scalars(
        select(Exercise.id).where(Exercise.deck_id == blocks["tenses"].id).order_by(Exercise.id)
    ).all()
    less, more = ex_ids[0], ex_ids[1]
    db.add(ExerciseState(profile_id=profile.id, exercise_id=less, due_at=now - timedelta(hours=1)))
    db.add(ExerciseState(profile_id=profile.id, exercise_id=more, due_at=now - timedelta(days=3)))
    db.commit()

    exs = build_exercise_session(db, profile, blocks["tenses"].id, limit=20, now=now)
    assert exs[0].id == more  # most overdue first
    assert exs[1].id == less


def test_shared_budget_words_reduce_exercise_budget(db, blocks, make_profile):
    """Words introduced today shrink the exercise new-item budget (shared pool)."""
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)
    profile = make_profile("shared-a", new_cards_per_day=5)

    # Introduce 3 words from the vocab block today.
    from app.models import Word

    vocab_word_ids = db.scalars(
        select(Word.id).where(Word.deck_id == blocks["vocab"].id).order_by(Word.id).limit(3)
    ).all()
    for wid in vocab_word_ids:
        db.add(CardState(profile_id=profile.id, word_id=wid, first_seen_at=now, due_at=now + timedelta(days=5)))
    db.commit()

    assert new_cards_introduced_today(db, profile.id, now) == 3
    exs = build_exercise_session(db, profile, blocks["tenses"].id, limit=20, now=now)
    assert len(exs) == 2  # budget 5 - 3 words used = 2 exercises


def test_shared_budget_exercises_reduce_word_budget(db, blocks, make_profile):
    """And the reverse: exercises introduced today shrink the word new-item budget."""
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)
    profile = make_profile("shared-b", new_cards_per_day=5)

    ex_ids = db.scalars(
        select(Exercise.id).where(Exercise.deck_id == blocks["tenses"].id).order_by(Exercise.id).limit(4)
    ).all()
    for eid in ex_ids:
        db.add(ExerciseState(profile_id=profile.id, exercise_id=eid, first_seen_at=now, due_at=now + timedelta(days=5)))
    db.commit()

    assert new_cards_introduced_today(db, profile.id, now) == 4
    words = build_session(db, profile, blocks["vocab"].id, limit=20, now=now)
    assert len(words) == 1  # budget 5 - 4 exercises used = 1 word


def test_exercise_options_splits_on_semicolon(db, blocks):
    ex = db.execute(
        select(Exercise).where(Exercise.deck_id == blocks["tenses"].id).order_by(Exercise.id)
    ).scalars().first()
    assert exercise_options(ex) == ["hablas", "habla", "hablamos"]


def test_exercise_options_empty_when_no_choices(db, blocks):
    ex = db.execute(
        select(Exercise).where(Exercise.deck_id == blocks["tenses"].id).order_by(Exercise.id)
    ).scalars().first()
    ex.choices = None
    assert exercise_options(ex) == []


# --- 3. study API --------------------------------------------------------

def _start(client, deck_id, mode):
    r = client.post("/study/start", data={"deck_id": deck_id, "mode": mode}, follow_redirects=False)
    return r


def _first_exercise(db, sid):
    sess = study._sessions[sid]
    return db.get(Exercise, sess.queue[sess.index])


def test_block_page_vocab_shows_all_modes(db, blocks, make_client):
    c = make_client("Alice")
    r = c.get(f"/blocks/{blocks['vocab'].id}")
    assert r.status_code == 200
    # vocab kind => all four modes present
    for label in ("Флэш-карты", "Выбор варианта", "Написать ответ", "Найти пары"):
        assert label in r.text


def test_block_page_tenses_hides_flashcards_and_match(db, blocks, make_client):
    c = make_client("Alice")
    r = c.get(f"/blocks/{blocks['tenses'].id}")
    assert r.status_code == 200
    assert "Выбор варианта" in r.text
    assert "Написать ответ" in r.text
    assert "Флэш-карты" not in r.text  # not an allowed mode for tenses
    assert "Найти пары" not in r.text


def test_start_flashcards_on_tenses_deck_400(db, blocks, make_client):
    c = make_client("Alice")
    r = _start(c, blocks["tenses"].id, "flashcards")
    assert r.status_code == 400


def test_choice_on_gap_deck_has_four_options(db, blocks, make_client):
    c = make_client("Alice")
    r = _start(c, blocks["gap"].id, "choice")
    assert r.status_code == 303
    sid = r.headers["location"].rsplit("/", 1)[-1]
    assert c.get(f"/study/{sid}").status_code == 200

    card = c.get(f"/study/{sid}/card")
    assert card.status_code == 200
    assert card.text.count(f"/study/{sid}/answer") == 4  # 3 distractors + correct


def test_choice_correct_writes_exercise_state_and_log(db, blocks, make_client):
    c = make_client("Alice")
    profile_id = int(c.cookies["profile_id"])
    r = _start(c, blocks["gap"].id, "choice")
    sid = r.headers["location"].rsplit("/", 1)[-1]
    ex = _first_exercise(db, sid)

    resp = c.post(f"/study/{sid}/answer", data={"answer": ex.answer})
    assert resp.status_code == 200
    assert "Верно!" in resp.text

    db.expire_all()
    es = db.get(ExerciseState, (profile_id, ex.id))
    assert es is not None
    assert es.repetitions == 1  # choice-correct => grade 4 => first success
    assert es.interval_days == 1.0  # SM-2 first interval, same as words

    log = db.execute(
        select(ReviewLog).where(ReviewLog.profile_id == profile_id, ReviewLog.exercise_id == ex.id)
    ).scalar_one()
    assert log.exercise_id == ex.id
    assert log.word_id is None
    assert log.mode == "choice"
    assert log.grade == 4


def test_typed_wrong_exercise_lapses_and_requeues(db, blocks, make_client):
    c = make_client("Alice")
    profile_id = int(c.cookies["profile_id"])
    r = _start(c, blocks["tenses"].id, "typed")
    sid = r.headers["location"].rsplit("/", 1)[-1]
    ex = _first_exercise(db, sid)
    before = len(study._sessions[sid].queue)

    resp = c.post(f"/study/{sid}/answer", data={"answer": "zzzzzzzz"})
    assert resp.status_code == 200
    assert "Неверно" in resp.text
    assert len(study._sessions[sid].queue) == before + 1  # requeued

    db.expire_all()
    es = db.get(ExerciseState, (profile_id, ex.id))
    assert es.lapses == 1
    assert es.repetitions == 0
    assert es.last_grade == 0


def test_exercise_state_sm2_grade4_interval_one(db, blocks, make_client):
    """A correct exercise (grade 4) walks SM-2 exactly like a word: interval 1.0."""
    c = make_client("Alice")
    profile_id = int(c.cookies["profile_id"])
    r = _start(c, blocks["tenses"].id, "typed")
    sid = r.headers["location"].rsplit("/", 1)[-1]
    ex = _first_exercise(db, sid)

    c.post(f"/study/{sid}/answer", data={"answer": ex.answer})  # exact => grade 5
    db.expire_all()
    es = db.get(ExerciseState, (profile_id, ex.id))
    assert es.repetitions == 1
    assert es.interval_days == 1.0


# --- 4. dashboard --------------------------------------------------------

def test_dashboard_shows_three_sections(db, blocks, make_client):
    c = make_client("Alice")
    r = c.get("/dashboard")
    assert r.status_code == 200
    assert "Слова" in r.text
    assert "Спряжение глаголов" in r.text
    assert "Слово в предложении" in r.text


def test_dashboard_block_card_counts_match(db, blocks, make_client):
    c = make_client("Alice")
    r = c.get("/dashboard")
    assert r.status_code == 200
    # tenses deck: 12 exercises, none started
    assert f"0 / {len(CONJ_ROWS)}" in r.text
    # gap deck: 6 exercises
    assert f"0 / {len(GAP_ROWS)}" in r.text


def test_blocks_404_on_nonexistent_deck(db, blocks, make_client):
    c = make_client("Alice")
    r = c.get("/blocks/999999")
    assert r.status_code == 404


# --- 5. stats ------------------------------------------------------------

def test_stats_200_after_exercise_reviews(db, blocks, make_client):
    c = make_client("Alice")
    r = _start(c, blocks["tenses"].id, "typed")
    sid = r.headers["location"].rsplit("/", 1)[-1]
    ex = _first_exercise(db, sid)
    c.post(f"/study/{sid}/answer", data={"answer": ex.answer})

    stats = c.get("/stats")
    assert stats.status_code == 200


def test_stats_hardest_ex_populated_after_lapse(db, blocks, make_client):
    c = make_client("Alice")
    r = _start(c, blocks["tenses"].id, "typed")
    sid = r.headers["location"].rsplit("/", 1)[-1]
    ex = _first_exercise(db, sid)
    c.post(f"/study/{sid}/answer", data={"answer": "zzzzzzzz"})  # lapse

    stats = c.get("/stats")
    assert stats.status_code == 200
    assert "Сложные упражнения" in stats.text  # hardest_ex section rendered
    assert ex.prompt in stats.text


# --- 6. empty-budget redirect (regression) -------------------------------
#
# Bug: the shared per-profile new-card budget is global across ALL decks. A user
# who drains it on one deck then opens a never-touched second deck used to be
# bounced all the way to /dashboard?empty=<id> (looked like "the block won't
# open"). The fix keeps them on /blocks/<id>?empty=1 with a visible notice.

def _client_for(profile) -> TestClient:
    """A TestClient authenticated as an existing profile (bypasses /profiles POST
    so we can pre-set new_cards_per_day via make_profile)."""
    c = TestClient(app)
    c.cookies.set("profile_id", str(profile.id))
    return c


def _drain_budget_on_vocab(db, profile, deck, now):
    """Consume the whole daily new-item budget by first-seeing `new_cards_per_day`
    vocab words today (mirrors what a real study session would record)."""
    wids = db.scalars(
        select(Word.id).where(Word.deck_id == deck.id).order_by(Word.id).limit(profile.new_cards_per_day)
    ).all()
    assert len(wids) == profile.new_cards_per_day, "test vocab deck too small to drain budget"
    for wid in wids:
        db.add(CardState(profile_id=profile.id, word_id=wid, first_seen_at=now, due_at=now + timedelta(days=5)))
    db.commit()


def test_exhausted_budget_redirects_to_block_not_dashboard(db, blocks, make_profile):
    profile = make_profile("exhausted", new_cards_per_day=5)
    now = datetime.now(timezone.utc)
    _drain_budget_on_vocab(db, profile, blocks["vocab"], now)
    assert new_cards_introduced_today(db, profile.id, now) == 5

    c = _client_for(profile)
    # tenses deck is completely untouched: no due items + zero budget => empty session
    r = c.post(
        "/study/start",
        data={"deck_id": blocks["tenses"].id, "mode": "typed"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == f"/blocks/{blocks['tenses'].id}?empty=1"  # NOT /dashboard

    page = c.get(r.headers["location"])
    assert page.status_code == 200
    # distinctive substring, not exact copy, so wording tweaks don't break the test
    assert "лимит новых карточек исчерпан" in page.text


def test_exhausted_budget_gap_deck_also_stays_on_block(db, blocks, make_profile):
    """Gap-fill blocks were the user's reported symptom (last in seed ordering)."""
    profile = make_profile("exhausted-gap", new_cards_per_day=5)
    now = datetime.now(timezone.utc)
    _drain_budget_on_vocab(db, profile, blocks["vocab"], now)

    c = _client_for(profile)
    r = c.post(
        "/study/start",
        data={"deck_id": blocks["gap"].id, "mode": "choice"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == f"/blocks/{blocks['gap'].id}?empty=1"


def test_block_page_no_notice_without_empty_flag(db, blocks, make_client):
    """The notice must only render when ?empty=1 is present, not on a normal visit."""
    c = make_client("Alice")
    r = c.get(f"/blocks/{blocks['tenses'].id}")
    assert r.status_code == 200
    assert "лимит новых карточек исчерпан" not in r.text


# --- 7. full-deck walkthrough (content round-trip) -----------------------
#
# Drives an ENTIRE deck end-to-end (start -> loop card/answer until summary),
# asserting every response is 200. Defends against a bad CSV row silently
# breaking a deck mid-way, which a single-card smoke test would miss.

def _answer_for(db, sess):
    item = db.get(Exercise if sess.item_kind == "exercise" else Word, sess.queue[sess.index])
    return item.answer if sess.item_kind == "exercise" else item.ru


def _walk_whole_deck(db, c, deck_id, mode) -> tuple[int, int]:
    """Start a session and answer every card correctly until the summary renders.
    Returns (cards_answered, distinct_items). Asserts 200 on every hop."""
    r = c.post("/study/start", data={"deck_id": deck_id, "mode": mode}, follow_redirects=False)
    assert r.status_code == 303, r.text
    loc = r.headers["location"]
    assert loc.startswith("/study/"), loc  # a real session, not an empty-redirect
    sid = loc.rsplit("/", 1)[-1]
    assert c.get(f"/study/{sid}").status_code == 200

    answered = 0
    seen_items: set[int] = set()
    for _ in range(500):  # generous bound; correct answers never requeue
        card = c.get(f"/study/{sid}/card")
        assert card.status_code == 200
        if "Сессия завершена" in card.text:
            return answered, len(seen_items)
        sess = study._sessions[sid]
        seen_items.add(sess.queue[sess.index])
        resp = c.post(f"/study/{sid}/answer", data={"answer": _answer_for(db, sess)})
        assert resp.status_code == 200, resp.text
        answered += 1
    raise AssertionError("deck walkthrough did not terminate")


@pytest.mark.parametrize(
    "kind,expected_items",
    [
        ("vocab", len(VOCAB_ROWS)),
        ("tenses", len(CONJ_ROWS)),
        ("gap", len(GAP_ROWS)),
    ],
)
def test_full_deck_walkthrough_all_content_round_trips(db, blocks, make_profile, kind, expected_items):
    # budget high enough to introduce every item in one session
    profile = make_profile(f"walk-{kind}", new_cards_per_day=100)
    c = _client_for(profile)
    answered, distinct = _walk_whole_deck(db, c, blocks[kind].id, "typed")
    # every item in the deck was served and answered exactly once (correct => no requeue)
    assert distinct == expected_items
    assert answered == expected_items
