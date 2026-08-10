# CEM Master Backend

FastAPI backend for the public CEM Master discovery website. Phase 1 exposes a database-backed catalogue of public monitoring spots as GeoJSON.

## Local Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --env-file .env --reload --port 8001
```

The local API will be available at `http://127.0.0.1:8001`.

## Configuration

Environment variables:

- `DATABASE_URL`: SQLAlchemy database URL. Defaults to `sqlite:///./cem_master.db`.
- `CORS_ORIGINS`: comma-separated allowed frontend origins.
- `CEM_MASTER_API_KEY`: optional development API key. When set, `POST /api/v1/spots` requires `X-API-Key`.

For Render PostgreSQL, set `DATABASE_URL` to the managed database URL.

## Endpoints

- `GET /health`
- `GET /api/v1/spots`
- `POST /api/v1/spots`

`GET /api/v1/spots` returns a GeoJSON `FeatureCollection` with point coordinates in `[longitude, latitude]` order.

## Seed Sample Spots

With the virtualenv active:

```bash
python scripts/seed_spots.py
```

Or insert a spot manually:

```bash
curl -X POST http://127.0.0.1:8001/api/v1/spots \
  -H "Content-Type: application/json" \
  -d '{
    "source_project_id": "sanjay-van",
    "source_spot_id": "s1",
    "name": "Sanjay Van Site 1",
    "description": "Sample monitoring location",
    "latitude": 28.533,
    "longitude": 77.176
  }'
```

If `CEM_MASTER_API_KEY` is set, include `-H "X-API-Key: your-key"`.

## Tests

```bash
pytest
```

## Render

Suggested settings:

- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Environment: set `DATABASE_URL`, `CORS_ORIGINS`, and optionally `CEM_MASTER_API_KEY`.
