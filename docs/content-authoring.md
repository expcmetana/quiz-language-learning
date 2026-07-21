# Adding learning content

All content is plain CSV under `seed/`, registered in `seed/blocks.json`. The
seeder (`app/seed.py`) is idempotent and additive: on every app startup it
reads the manifest and creates any deck whose **name** isn't already in the
database. Existing decks are never touched, so shipping new content is just
adding files and restarting — no migration, no code change.

## `seed/blocks.json`

An array of block entries:

```json
{
  "name": "Imperativo con pronombres",
  "kind": "gap",
  "level": "B2",
  "file": "imperativo_pronombres.csv",
  "description": "Место и слияние местоимений с повелительным наклонением"
}
```

| Field | Meaning |
| --- | --- |
| `name` | Deck name shown in the UI. Must be unique — this is the idempotency key. |
| `kind` | `vocab` \| `tenses` \| `gap` — picks the CSV schema below and which study modes are offered (see `MODES_BY_KIND` in `app/routers/study.py`). |
| `level` | CEFR level (`A1`–`B2`) or `null` for a themed/non-leveled deck. |
| `file` | CSV filename, relative to `seed/`. |
| `description` | One-line blurb shown under the deck name. |

A manifest entry with a missing file, or a `kind` the seeder doesn't
recognize, is skipped with a warning log — it never crashes startup, so it's
safe to land a manifest entry slightly ahead of its CSV.

## CSV schemas by `kind`

### `vocab` — word ↔ translation pairs

```csv
es,ru,example
hola,привет,¡Hola! ¿Cómo estás?
```

- `es`, `ru` — required. Rows missing either, or exact `(es, ru)` duplicates
  within the file, are skipped.
- `example` — optional Spanish sentence containing the word; the study UI
  highlights the matching span automatically (case-insensitive substring
  match against `es`).
- Modes offered: flashcards, choice, typed, match.

### `tenses` — verb conjugation drills

```csv
verb,tense,person,answer,choices,hint
hablar,Imperativo afirmativo,tú,habla,no hables;hablad;hable,говори
```

- `verb`, `answer` — required.
- `tense`, `person` — free text, concatenated into the on-screen prompt as
  `{verb} · {tense} · {person}`. Reuse the same `tense` string across a
  verb's rows to group them; distinct `tense` values (e.g. "Imperativo
  afirmativo" vs "Imperativo negativo") render as separate cards, which is
  the usual way to drill a contrast.
- `choices` — `;`-separated wrong options for choice mode. Must not contain
  the `answer` itself and must not repeat an option (both are silent content
  bugs, not enforced by the loader — verify before committing, see below).
- `hint` — optional gloss shown under the prompt.
- Modes offered: choice, typed (no flashcards/match — conjugation drills
  don't have a natural "front/back" or pairing shape).

### `gap` — fill-in-the-blank sentences

```csv
sentence,answer,choices,hint
Este libro es interesante. ___ (leer).,Léelo,Lee;Lo leo;Léela,"Эта книга интересная. Прочитай её."
```

- `sentence`, `answer` — required. `___` marks the blank; the parenthesized
  infinitive is a hint to the learner about which verb/word to inflect, not
  parsed by the app.
- `choices`, `hint` — same as `tenses`.
- Modes offered: choice, typed.

## Verifying new content before committing

The loader is lenient (skips bad rows silently), so validate CSVs yourself
before shipping — a bad row won't crash anything, it'll just silently produce
a worse card. At minimum, check for the answer leaking into its own
distractor list and duplicate distractors:

```bash
python3 -c "
import csv
for f in ['seed/your_new_file.csv']:
    rows = list(csv.DictReader(open(f, encoding='utf-8-sig')))
    print(f, len(rows), 'rows')
    for r in rows:
        ans = r.get('answer', '').strip()
        ch = [c.strip() for c in r.get('choices', '').split(';')]
        assert ans, r
        assert ans not in ch, ('answer in choices', r)
        assert len(ch) == len(set(ch)), ('dup choices', r)
"
```

Then load it into a throwaway database and confirm the deck seeds with the
expected row count — **never point this at your real data directory**:

```bash
rm -f /tmp/seedcheck.db
DATABASE_PATH=/tmp/seedcheck.db uv run python -c "
from app.db import engine, SessionLocal
from app.models import Base, Deck, Exercise, Word
from app.seed import seed_blocks
from pathlib import Path
Base.metadata.create_all(engine)
db = SessionLocal()
seed_blocks(db, Path('seed'))
deck = db.query(Deck).filter_by(name='Your New Deck Name').one()
print(deck.kind, db.query(Exercise if deck.kind != 'vocab' else Word).filter_by(deck_id=deck.id).count())
"
```

Finally run the test suite (`uv run pytest`) — it seeds and exercises the
real seeder against a throwaway test DB on every run, so a manifest/CSV
mismatch that breaks startup will fail there too.
