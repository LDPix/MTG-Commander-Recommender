# MTG Commander Recommender

Analyzes a Magic: The Gathering card collection and recommends playable Commander decks built mostly from cards you already own.

The system imports a CSV collection, normalizes card identities, scores commanders by collection fit, generates legal 100-card decklists with role quotas and synergy-based card selection, and returns role breakdowns, package clusters, card explanations, and upgrade suggestions for missing cards.

---

## Status

MVP complete — backend and frontend both implemented.

| Phase | Status |
|---|---|
| Data pipeline (Scryfall ingest, card resolver, role taxonomy) | Done |
| Collection import and normalization | Done |
| Commander recommendation | Done |
| Synergy graph and package detection | Done |
| Deck generation (role quotas, owned-card priority) | Done |
| Upgrade suggestions and card explanations | Done |
| Plaintext deck export | Done |
| Saved deck persistence and retrieval | Done |
| Golden regression tests and performance gates | Done |
| Frontend (React/Vite) | Done |

**303 backend tests + 12 frontend tests passing.**

---

## Tech stack

- **Backend:** Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy v2
- **Frontend:** React, TypeScript, Vite, Vitest
- **Database:** PostgreSQL (production), SQLite (tests — no setup required)
- **Migrations:** Alembic

---

## Project structure

```
backend/
  app/
    api/v1/          # Route handlers — validation and response formatting only
    services/        # Business logic and use-case orchestration
    repositories/    # Database access
    models/          # SQLAlchemy ORM models and in-memory domain objects
    schemas/         # Pydantic request/response schemas
    recommendation/  # Scoring, tagging, graph, deck generation, explainability
    data_pipeline/   # Scryfall ingest and collection import (offline)
    db/              # Database engine and session setup
  tests/
    unit/
    integration/
    performance/
    fixtures/
frontend/
  src/
    api/             # API client
    components/      # React components
    types/           # TypeScript API types
  tests/
docs/
  SPEC.md            # Detailed technical specification
```

Architecture is strictly layered: `API → Service → Repository → Model`. No recommendation logic in API routes; no database access in recommendation modules.

---

## Backend setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Running the server

The server uses PostgreSQL by default. Set `DATABASE_URL` to override:

```bash
export DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/mtg_recommender
uvicorn app.main:app --reload
```

API docs available at `http://localhost:8000/docs`.

### Running backend tests

Tests use an in-memory SQLite database — no PostgreSQL required.

```bash
cd backend
python -m pytest                        # full suite
python -m pytest tests/unit/            # unit tests only
python -m pytest tests/integration/     # integration tests only
python -m pytest tests/performance/     # performance gates only
python -m pytest --tb=short -q          # compact output
```

---

## Frontend setup

```bash
cd frontend
npm install
npm run dev        # dev server at http://localhost:5173
npm test           # run Vitest suite
```

---

## API

### Import a collection

```
POST /api/v1/collections/import
Header: X-Session-Id: <session_id>
Body: multipart/form-data, field "file" = CSV file
```

CSV must have `name` and `quantity` columns (case-insensitive; common aliases accepted). Returns import summary with unknown cards, warnings, and change summary on reimport.

### Get a collection

```
GET /api/v1/collections/{session_id}
```

### Get commander recommendations

```
GET /api/v1/recommendations/{session_id}
```

Returns commanders ranked by collection fit score with explanation, owned support, and missing-card notes.

### Generate a deck

```
POST /api/v1/decks/generate
Content-Type: application/json

{
  "session_id": "...",
  "commander_oracle_id": "..."
}
```

Returns a 100-card Commander-legal deck with role breakdown, quota status, package clusters, per-card owned/missing status, card explanations, and upgrade suggestions. The deck is automatically persisted and retrievable by session.

### List saved decks

```
GET /api/v1/decks/saved?session_id=<session_id>
```

### Get saved deck detail

```
GET /api/v1/decks/saved/{deck_id}?session_id=<session_id>
```

### Export a deck

```
POST /api/v1/decks/export/plaintext
Content-Type: application/json

{ "deck_id": "...", "session_id": "..." }
```

Returns a plaintext decklist with commander and main deck sections.

---

## Health check

```
GET /health
```
