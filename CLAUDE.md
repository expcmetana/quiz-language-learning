# Project instructions

- Order for shipping a change: tests pass -> deploy locally (docker compose up --build -d) -> verify live (Playwright or curl) -> only then commit and push to origin. Don't push before verification.
- After verification passes, push commits to origin (no need to ask each time).
