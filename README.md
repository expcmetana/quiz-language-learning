# quiz-language-learning

A local, self-hosted Spanish → Russian language trainer with SM-2 spaced repetition
(FastAPI + SQLAlchemy + SQLite, server-rendered UI with HTMX).

## Features

- **Learning blocks with CEFR levels (A1–B2)**: Top-1000 frequency words split by
  level, verb conjugation drills (presente → subjuntivo/imperativo), and
  "word in sentence" gap-fill exercises (ser/estar, por/para, subjunctive contrasts, …)
- **Study modes**: flashcards (self-graded), multiple choice, typed answer
  (typo-tolerant), match pairs — grammar blocks use choice/typed
- **Multiple local profiles** (Netflix-style picker, no passwords) with independent
  SM-2 progress per word and per exercise, shared daily new-item budget
- **Custom decks**: create your own, CSV import/export (`es,ru,example`)
- **Stats**: reviews per day, accuracy by mode, hardest words/exercises

## Quick start (Docker)

```bash
docker compose up --build
```

The app is served at <http://localhost:8000>.

### User data is external to the container

All user data (profiles, progress, custom decks) lives in a single SQLite database
**outside** the image and is connected at container launch via a volume mount.
The default `docker-compose.yml` maps host `./data` → container `/data`
(database file `/data/app.db`):

```yaml
volumes:
  - ./data:/data
```

Point it at any host path or named volume to relocate the data. The `data/`
directory is git-ignored — user data never enters the repository or the image.
Migrations run automatically on startup, so upgrading the image keeps existing data.

Back up by copying `data/app.db` (stop the container first, or also copy the
`-wal`/`-shm` sidecar files).

## Configuration

| Env var | Default | Meaning |
| --- | --- | --- |
| `DATABASE_PATH` | `/data/app.db` (in container) | SQLite file location |
| `NEW_CARDS_PER_DAY` | `10` | Daily budget of new items per profile |
| `SESSION_SIZE` | `20` | Max cards per study session |
| `SEED_DIR` | `./seed` | Directory with `blocks.json` + content CSVs |

## Local development

```bash
uv sync
uv run uvicorn app.main:app --reload   # migrations + seeding run on startup
```

Run the test suite:

```bash
uv run pytest
```

## CI / releases

- `ci.yml` — tests + Docker build check on every push/PR to `main`
- `release.yml` — on tag `v*`: tests, image push to GHCR, GitHub Release
