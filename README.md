# MTG Commander Recommender

Analyzes a Magic: The Gathering card collection and recommends playable Commander decks built mostly from cards you already own.

The system imports a CSV collection, normalizes card identities, scores commanders by collection fit, generates legal 100-card decklists with role quotas and synergy-based card selection, and returns role breakdowns, package clusters, and upgrade suggestions for missing cards.

---

## Status

Backend complete. Frontend not yet started.

| Phase | Status |
|---|---|
| Data pipeline (Scryfall ingest, card resolver, role taxonomy) | Done |
| Collection import and normalization | Done |
| Commander recommendation | Done |
| Synergy graph and package detection | Done |
| Deck generation (role quotas, owned-card priority) | Done |
| Deck generation API | Done |
| Upgrade suggestions, card explanations, export | Planned |
| Frontend | Planned |

**216 backend tests passing.**

---

## Tech stack

- **Backend:** Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy v2
- **Database:** PostgreSQL (production), SQLite (tests — no setup required)
- **Migrations:** Alembic
- **Tests:** pytest

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
    recommendation/  # Scoring, tagging, graph, and deck generation logic
    data_pipeline/   # Scryfall ingest and collection import (offline)
    db/              # Database engine and session setup
  tests/
    unit/
    integration/
    fixtures/
docs/
  SPEC.md            # Detailed technical specification
```

Architecture is strictly layered: `API → Service → Repository → Model`. No recommendation logic in API routes; no database access in recommendation modules.

---

## Setup

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

---

## Running tests

Tests use an in-memory SQLite database — no PostgreSQL required.

```bash
cd backend
python -m pytest
```

```bash
python -m pytest tests/unit/          # unit tests only
python -m pytest tests/integration/   # integration tests only
python -m pytest --tb=short -q        # compact output
```

---

## API

### Import a collection

```
POST /api/v1/collections/import
Header: X-Session-Id: <session_id>
Body: multipart/form-data, field "file" = CSV file
```

CSV must have `name` and `quantity` columns (case-insensitive; common aliases accepted).

### Get a collection

```
GET /api/v1/collections/{session_id}
```

### Get commander recommendations

```
GET /api/v1/recommendations/{session_id}
```

Returns commanders ranked by collection fit score with explanation.

### Generate a deck

```
POST /api/v1/decks/generate
Content-Type: application/json

{
  "session_id": "...",
  "commander_oracle_id": "..."
}
```

Returns a 100-card Commander-legal deck with role breakdown, quota status, package clusters, owned/missing status per card, and upgrade suggestions.

---

## Health check

```
GET /health
```
