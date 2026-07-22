"""End-to-end tests through the FastAPI TestClient."""

import io
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from app.models import CardState, Deck, Exercise, Profile, ReviewLog, Word
from app.routers import study
from app.seed import SEED_DECK_NAME


# --- helpers -------------------------------------------------------------

def _seed_deck_id(db):
    return db.scalar(select(Deck.id).where(Deck.name == SEED_DECK_NAME))


def _naive(dt):
    return dt.replace(tzinfo=None) if dt and dt.tzinfo else dt


def _start(client, deck_id, mode):
    r = client.post("/study/start", data={"deck_id": deck_id, "mode": mode}, follow_redirects=False)
    assert r.status_code == 303, r.text
    loc = r.headers["location"]
    assert loc.startswith("/study/")
    return loc.rsplit("/", 1)[-1]


def _first_word(db, sid):
    sess = study._sessions[sid]
    return db.get(Word, sess.queue[sess.index])


# --- index / profiles ----------------------------------------------------

def test_index_redirects_to_profiles_without_cookie(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/profiles"


def test_create_profile_sets_cookie_and_dashboard_shows_seed_deck(client):
    r = client.post("/profiles", data={"name": "Alice"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/dashboard"
    assert client.cookies.get("profile_id")

    dash = client.get("/dashboard")
    assert dash.status_code == 200
    assert SEED_DECK_NAME in dash.text


def test_index_redirects_to_dashboard_with_cookie(make_client):
    c = make_client("Bob")
    r = c.get("/", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/dashboard"


def test_delete_profile_cascades_and_clears_cookie(make_client, db):
    c = make_client("ToDelete")
    profile_id = int(c.cookies["profile_id"])
    deck_id = _seed_deck_id(db)

    sid = _start(c, deck_id, "typed")
    word = _first_word(db, sid)
    c.post(f"/study/{sid}/answer", data={"answer": word.ru})
    db.expire_all()
    assert db.get(CardState, (profile_id, word.id)) is not None
    assert db.scalar(select(func.count()).select_from(ReviewLog).where(ReviewLog.profile_id == profile_id)) == 1

    r = c.post(f"/profiles/{profile_id}/delete", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/profiles"
    assert "profile_id" not in r.cookies

    db.expire_all()
    assert db.get(Profile, profile_id) is None
    assert db.get(CardState, (profile_id, word.id)) is None
    assert db.scalar(select(func.count()).select_from(ReviewLog).where(ReviewLog.profile_id == profile_id)) == 0

    picker = c.get("/profiles")
    assert "ToDelete" not in picker.text


def test_delete_profile_does_not_clear_other_profiles_cookie(make_client, db):
    keep = make_client("Keep")
    victim = make_client("Victim")
    keep_id = int(keep.cookies["profile_id"])
    victim_id = int(victim.cookies["profile_id"])

    r = keep.post(f"/profiles/{victim_id}/delete", follow_redirects=False)
    assert r.status_code == 303
    assert keep.cookies.get("profile_id") == str(keep_id)
    assert db.get(Profile, victim_id) is None


# --- deck CRUD -----------------------------------------------------------

def test_deck_crud_and_word_dedupe(make_client, db):
    c = make_client("Alice")

    # create deck
    r = c.post("/decks", data={"name": "Mi Deck", "description": "d"}, follow_redirects=False)
    assert r.status_code == 303
    deck_id = int(r.headers["location"].rsplit("/", 1)[-1])

    # add word
    c.post(f"/decks/{deck_id}/words", data={"es": "gato", "ru": "кот", "example": ""})
    # duplicate (same es,ru) not added twice
    c.post(f"/decks/{deck_id}/words", data={"es": "gato", "ru": "кот", "example": ""})
    n = db.scalar(
        select(func.count()).select_from(Word).where(Word.deck_id == deck_id, Word.es == "gato", Word.ru == "кот")
    )
    assert n == 1

    word_id = db.scalar(select(Word.id).where(Word.deck_id == deck_id, Word.es == "gato"))

    # delete word
    c.post(f"/decks/{deck_id}/words/{word_id}/delete")
    assert db.get(Word, word_id) is None

    # delete deck
    r = c.post(f"/decks/{deck_id}/delete", follow_redirects=False)
    assert r.status_code == 303
    db.expire_all()
    assert db.get(Deck, deck_id) is None


# --- CSV import / export -------------------------------------------------

def test_csv_import_dedupe_and_redirect(make_client, db):
    c = make_client("Alice")
    r = c.post("/decks", data={"name": "Import Deck"}, follow_redirects=False)
    deck_id = int(r.headers["location"].rsplit("/", 1)[-1])

    csv_bytes = b"es,ru,example\nperro,\xd1\x81\xd0\xbe\xd0\xb1\xd0\xb0\xd0\xba\xd0\xb0,un ejemplo\nperro,\xd1\x81\xd0\xbe\xd0\xb1\xd0\xb0\xd0\xba\xd0\xb0,dup\ncasa,\xd0\xb4\xd0\xbe\xd0\xbc,\n"
    files = {"file": ("words.csv", io.BytesIO(csv_bytes), "text/csv")}
    r = c.post(f"/decks/{deck_id}/import", files=files, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == f"/decks/{deck_id}?imported=2"  # dup row skipped

    count = db.scalar(select(func.count()).select_from(Word).where(Word.deck_id == deck_id))
    assert count == 2


def test_csv_import_bad_header_400(make_client):
    c = make_client("Alice")
    r = c.post("/decks", data={"name": "Bad Deck"}, follow_redirects=False)
    deck_id = int(r.headers["location"].rsplit("/", 1)[-1])

    files = {"file": ("bad.csv", io.BytesIO(b"foo,bar\n1,2\n"), "text/csv")}
    r = c.post(f"/decks/{deck_id}/import", files=files)
    assert r.status_code == 400


def test_csv_export(make_client, db):
    # NOTE: uses an ASCII deck name on purpose. Exporting the seeded deck
    # ("Básico ES-RU") triggers an app bug: the non-ASCII filename in the
    # Content-Disposition header breaks decoding (see final report).
    c = make_client("Alice")
    r = c.post("/decks", data={"name": "Export Deck"}, follow_redirects=False)
    deck_id = int(r.headers["location"].rsplit("/", 1)[-1])
    c.post(f"/decks/{deck_id}/words", data={"es": "hola", "ru": "привет", "example": ""})

    r = c.get(f"/decks/{deck_id}/export")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "hola" in r.text
    assert "привет" in r.text
    assert r.text.splitlines()[0] == "es,ru,example"


# --- study: typed --------------------------------------------------------

def test_typed_correct_answer_writes_state_and_log(make_client, db):
    c = make_client("Alice")
    deck_id = _seed_deck_id(db)
    profile_id = int(c.cookies["profile_id"])

    sid = _start(c, deck_id, "typed")
    assert c.get(f"/study/{sid}").status_code == 200

    word = _first_word(db, sid)
    card = c.get(f"/study/{sid}/card")
    assert card.status_code == 200
    assert word.es in card.text

    r = c.post(f"/study/{sid}/answer", data={"answer": word.ru})
    assert r.status_code == 200
    assert "Верно!" in r.text
    assert "verdict ok" in r.text

    db.expire_all()
    cs = db.get(CardState, (profile_id, word.id))
    assert cs is not None
    assert cs.repetitions == 1
    assert cs.interval_days == 1.0
    expected = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=1)
    assert abs(_naive(cs.due_at) - expected) < timedelta(minutes=5)

    log = db.execute(
        select(ReviewLog).where(ReviewLog.profile_id == profile_id, ReviewLog.word_id == word.id)
    ).scalar_one()
    assert log.mode == "typed"
    assert log.grade == 5


def test_typed_wrong_answer_requeues_and_lapses(make_client, db):
    c = make_client("Alice")
    deck_id = _seed_deck_id(db)
    profile_id = int(c.cookies["profile_id"])

    sid = _start(c, deck_id, "typed")
    word = _first_word(db, sid)
    before = len(study._sessions[sid].queue)

    r = c.post(f"/study/{sid}/answer", data={"answer": "zzzzzzzz"})
    assert r.status_code == 200
    assert "Неверно" in r.text

    assert len(study._sessions[sid].queue) == before + 1  # requeued

    db.expire_all()
    cs = db.get(CardState, (profile_id, word.id))
    assert cs.lapses == 1
    assert cs.repetitions == 0
    assert cs.last_grade == 0


# --- study: flashcards ---------------------------------------------------

def test_flashcards_returns_next_card_not_feedback(make_client, db):
    c = make_client("Alice")
    deck_id = _seed_deck_id(db)
    sid = _start(c, deck_id, "flashcards")
    # prime first card
    c.get(f"/study/{sid}/card")

    r = c.post(f"/study/{sid}/answer", data={"grade": 4})
    assert r.status_code == 200
    assert "quiz-grades" in r.text  # next flashcard rendered
    assert "verdict" not in r.text    # not the feedback partial


# --- study: choice -------------------------------------------------------

def test_choice_card_has_four_options_including_correct(make_client, db):
    c = make_client("Alice")
    deck_id = _seed_deck_id(db)
    sid = _start(c, deck_id, "choice")
    word = _first_word(db, sid)

    card = c.get(f"/study/{sid}/card")
    assert card.status_code == 200
    assert word.ru in card.text
    assert card.text.count(f"/study/{sid}/answer") == 4  # 4 option buttons

    r = c.post(f"/study/{sid}/answer", data={"answer": word.ru})
    assert r.status_code == 200
    assert "Верно!" in r.text


def test_choice_correct_answer_marks_autoadvance(make_client, db):
    c = make_client("Alice")
    deck_id = _seed_deck_id(db)
    sid = _start(c, deck_id, "choice")
    word = _first_word(db, sid)

    r = c.post(f"/study/{sid}/answer", data={"answer": word.ru})
    assert "Верно!" in r.text
    assert 'data-autoadvance="1200"' in r.text


def test_choice_wrong_answer_has_no_autoadvance(make_client, db):
    c = make_client("Alice")
    deck_id = _seed_deck_id(db)
    sid = _start(c, deck_id, "choice")
    word = _first_word(db, sid)

    r = c.post(f"/study/{sid}/answer", data={"answer": word.ru + "_wrong"})
    assert "Неверно" in r.text
    assert "data-autoadvance" not in r.text


def test_typed_correct_answer_has_no_autoadvance(make_client, db):
    c = make_client("Alice")
    deck_id = _seed_deck_id(db)
    sid = _start(c, deck_id, "typed")
    word = _first_word(db, sid)

    r = c.post(f"/study/{sid}/answer", data={"answer": word.ru})
    assert "Верно!" in r.text
    assert "data-autoadvance" not in r.text


# --- study: summary / continue --------------------------------------------

def _finish_typed_session(c, db, sid):
    """Answer every card correctly until the queue is drained, then fetch the
    summary partial (only a GET /card renders it, never the answer POST)."""
    while True:
        sess = study._sessions.get(sid)
        if sess is None or sess.index >= len(sess.queue):
            break
        word = _first_word(db, sid)
        c.post(f"/study/{sid}/answer", data={"answer": word.ru})
    return c.get(f"/study/{sid}/card")


def test_summary_offers_continue_when_deck_has_more_words(make_client, db):
    c = make_client("Alice")
    deck_id = _seed_deck_id(db)  # seed deck has ~223 words, SESSION_SIZE=20 in tests
    sid = _start(c, deck_id, "typed")

    r = _finish_typed_session(c, db, sid)

    assert "Сессия завершена" in r.text
    assert "Продолжить обучение" in r.text
    assert f'value="{deck_id}"' in r.text
    assert 'value="typed"' in r.text


def test_summary_hides_continue_when_deck_fully_exhausted(make_client, db):
    c = make_client("Alice")
    r = c.post("/decks", data={"name": "Tiny Deck"}, follow_redirects=False)
    deck_id = int(r.headers["location"].rsplit("/", 1)[-1])
    c.post(f"/decks/{deck_id}/words", data={"es": "gato", "ru": "кот", "example": ""})
    c.post(f"/decks/{deck_id}/words", data={"es": "perro", "ru": "собака", "example": ""})

    sid = _start(c, deck_id, "typed")
    r = _finish_typed_session(c, db, sid)

    assert "Сессия завершена" in r.text
    assert "Продолжить обучение" not in r.text


# --- study: random mode ---------------------------------------------------

def test_block_detail_offers_random_mode_button(make_client, db):
    c = make_client("Alice")
    deck_id = _seed_deck_id(db)
    r = c.get(f"/blocks/{deck_id}")
    assert r.status_code == 200
    assert 'value="random"' in r.text
    assert "Случайный режим" in r.text


def test_random_mode_resolves_to_an_allowed_vocab_mode(make_client, db):
    c = make_client("Alice")
    deck_id = _seed_deck_id(db)

    seen = set()
    for _ in range(15):
        r = c.post("/study/start", data={"deck_id": deck_id, "mode": "random"}, follow_redirects=False)
        assert r.status_code == 303
        sid = r.headers["location"].rsplit("/", 1)[-1]
        sess = study._sessions[sid]
        assert sess.mode in study.MODES_BY_KIND["vocab"]
        seen.add(sess.mode)
        study._sessions.pop(sid, None)

    assert len(seen) > 1  # actually varies across runs, not hardcoded to one mode


def test_random_mode_resolves_within_deck_kind_only(make_client, db):
    c = make_client("Alice")
    r = c.post("/decks", data={"name": "Conj Deck"}, follow_redirects=False)
    deck_id = int(r.headers["location"].rsplit("/", 1)[-1])
    deck = db.get(Deck, deck_id)
    deck.kind = "tenses"
    db.add(Exercise(deck_id=deck_id, type="conj", prompt="hablar · Presente · yo", answer="hablo", choices="habla;hablas;hablamos"))
    db.commit()

    for _ in range(10):
        r = c.post("/study/start", data={"deck_id": deck_id, "mode": "random"}, follow_redirects=False)
        assert r.status_code == 303
        sid = r.headers["location"].rsplit("/", 1)[-1]
        sess = study._sessions[sid]
        assert sess.mode in {"choice", "typed"}  # tenses decks never offer flashcards/match
        study._sessions.pop(sid, None)


def test_start_random_picks_among_available_decks(make_client, db):
    c = make_client("Alice")
    r = c.post("/decks", data={"name": "Second Deck"}, follow_redirects=False)
    deck2_id = int(r.headers["location"].rsplit("/", 1)[-1])
    c.post(f"/decks/{deck2_id}/words", data={"es": "gato", "ru": "кот", "example": ""})

    seen_decks = set()
    for _ in range(20):
        r = c.post("/study/start-random", follow_redirects=False)
        assert r.status_code == 303
        sid = r.headers["location"].rsplit("/", 1)[-1]
        sess = study._sessions[sid]
        seen_decks.add(sess.deck_id)
        study._sessions.pop(sid, None)

    assert len(seen_decks) > 1  # both the seed deck and the new one get picked eventually


def test_start_random_redirects_to_dashboard_when_nothing_available(make_client, db):
    c = make_client("Alice")
    db.execute(delete(Deck))
    db.commit()

    r = c.post("/study/start-random", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/dashboard?empty=1"


# --- study: match --------------------------------------------------------

def test_match_flow_writes_logs_for_all_queue_words(make_client, db):
    c = make_client("Alice")
    deck_id = _seed_deck_id(db)
    profile_id = int(c.cookies["profile_id"])

    sid = _start(c, deck_id, "match")
    page = c.get(f"/study/{sid}")
    assert page.status_code == 200

    queue = list(study._sessions[sid].queue)
    assert len(queue) == study.MATCH_PAIRS  # capped to 6

    misses = {str(queue[0]): 1}  # one word missed, rest matched
    r = c.post(f"/study/{sid}/match-results", json={"misses": misses})
    assert r.status_code == 200
    assert "Сессия завершена" in r.text

    db.expire_all()
    logs = db.execute(
        select(ReviewLog).where(ReviewLog.profile_id == profile_id, ReviewLog.mode == "match")
    ).scalars().all()
    assert {l.word_id for l in logs} == set(queue)
    assert len(logs) == len(queue)


# --- isolation between profiles -----------------------------------------

def test_review_isolated_between_profiles(make_client, db):
    a = make_client("A")
    b = make_client("B")
    deck_id = _seed_deck_id(db)
    pa = int(a.cookies["profile_id"])
    pb = int(b.cookies["profile_id"])

    sid = _start(a, deck_id, "typed")
    word = _first_word(db, sid)
    a.post(f"/study/{sid}/answer", data={"answer": word.ru})

    db.expire_all()
    assert db.get(CardState, (pa, word.id)) is not None
    assert db.get(CardState, (pb, word.id)) is None


def test_study_session_404_for_other_profile(make_client, db):
    a = make_client("A")
    b = make_client("B")
    deck_id = _seed_deck_id(db)

    sid = _start(a, deck_id, "typed")
    r = b.get(f"/study/{sid}")
    assert r.status_code == 404
