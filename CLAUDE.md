# Project instructions

- Order for shipping a change: tests pass -> deploy locally (docker compose up --build -d) -> verify live (Playwright or curl) -> only then commit and push to origin. Don't push before verification.
- After verification passes, push commits to origin (no need to ask each time).
- When a change adds/alters user-visible UI or a feature, update README.md and docs/ (including screenshots in docs/screenshots/) to match, in the same commit.
