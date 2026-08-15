# CEM Master Backend

FastAPI/SQLAlchemy API for the public CEM Master bioacoustic dashboard. This
backend is PostgreSQL-only and expects an independently managed Docker service
named `cem-database` to contain the schema and indexed analysis data.

## Request path

```text
Browser -> frontend Nginx /api proxy -> FastAPI -> SQLAlchemy -> cem-database
```

The backend reads indexed records from PostgreSQL and returns JSON/GeoJSON. It
does not scan `aggregate.csv` or analysis-result folders during an API request.
An external ingestion/indexing process is responsible for loading and updating
the database from those files.

## Prerequisites

- Docker with Compose
- A running PostgreSQL container whose Docker service/container DNS name is
  `cem-database`
- The external bridge network `cem_master_network`
- The tables and columns represented by `app/models.py`

Create the shared network once if the database deployment has not already done
so:

```bash
docker network create cem_master_network
```

Both `cem-database` and the backend must join that network.

## Configuration

Copy the example file and replace the credentials:

```bash
cp .env.example .env
```

```dotenv
DATABASE_URL=postgresql+psycopg://cem_user:strong-password@cem-database:5432/cem_master
CORS_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
CEM_MASTER_API_KEY=
```

`DATABASE_URL` is required. Startup rejects SQLite and other database URLs.
Keep the real `.env` outside Git.

## Run the backend container

```bash
docker compose up --build -d
docker compose logs -f backend
```

Open:

- API: `http://127.0.0.1:8001`
- Swagger: `http://127.0.0.1:8001/docs`
- Database-aware health check: `http://127.0.0.1:8001/health`

A healthy response is:

```json
{"status":"ok","database":"postgresql"}
```

If PostgreSQL cannot be queried, health returns HTTP 503.

## Existing-schema contract

The database owner must create and migrate the schema. Backend startup does not
run `create_all()` and does not alter the shared database.

Required tables:

- `spots`: one canonical physical location per latitude/longitude.
- `spot_sources`: project/spot source IDs contributing to a canonical spot.
- `species`: searchable names, IUCN status, image, migration, activity hours,
  seasonality, taxonomy, and network metrics.
- `spot_summaries`: `recording_count`, `species_richness`, `total_detections`,
  `active_days`, `job_count`, recording dates, acoustic indices, and assets.
- `spot_species_summaries`: detection count, active days, activity rank,
  migration class, occurrence dates, hourly/monthly series, metrics, and assets.
- `spot_species_daily`: one daily detection total per spot/species/date.
- `analysis_jobs`: analysis status and public input/output filenames and URLs.
- `spot_environment_daily`: solar, rainfall, temperature, humidity, and severe
  weather observations.

The exact SQLAlchemy column types, lengths, keys, and indexes are defined in
`app/models.py`. PostgreSQL JSON documents use `JSONB`.
Additional PostgreSQL search/index recommendations are provided in
`docs/postgres-indexes.sql`; the database owner should apply and manage them.

Important meanings:

- `recording_count` is the number of audio recordings/files.
- `active_days` is the number of distinct dates with data.
- `species_richness` is the number of distinct species.
- Job totals come from `analysis_jobs`; they are not inferred from migration
  results.

## API endpoints

- `GET /health`
- `GET /api/v1/spots`
- `GET /api/v1/spots?species_id=<id>`
- `GET /api/v1/spots?species_id=<id>&start_date=YYYY-MM-DD&end_date=YYYY-MM-DD`
- `GET /api/v1/spots?migration_class=resident`
- `GET /api/v1/spots/{spot_id}`
- `POST /api/v1/spots`
- `GET /api/v1/species?search=<common-or-scientific-name>`
- `GET /api/v1/species?migration_class=migratory`
- `GET /api/v1/species/{species_id}`
- `GET /api/v1/spots/{spot_id}/summary`
- `GET /api/v1/spots/{spot_id}/species/{species_id}`
- `GET /api/v1/spots/{spot_id}/environment`
- `GET /api/v1/rankings/threatened-spots`

Spot catalogue responses are GeoJSON with `[longitude, latitude]` coordinates.
Date filters use `YYYY-MM-DD`. Invalid ranges return HTTP 422, missing records
return HTTP 404, and failed protected writes return HTTP 401/409 as appropriate.

For compatibility with the current frontend, summary responses contain both
`active_days` and the temporary alias `recording_days`.

## Local Python process

The backend can run outside Docker, but its PostgreSQL hostname must then be
reachable from the host. For example, if the database publishes port 5432:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --env-file .env --reload --port 8001
```

When running on the host, the URL normally uses `127.0.0.1` instead of the
Docker-only hostname `cem-database`.

## Optional sample loader

`scripts/seed_spots.py` remains an optional demonstration loader. It assumes the
PostgreSQL schema already exists and writes to the configured `DATABASE_URL`.
It is not run by Compose and should not be used against the real master database.
