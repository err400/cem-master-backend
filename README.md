# CEM Master Backend

FastAPI and SQLAlchemy API for the CEM Master bioacoustic discovery dashboard.
It provides canonical monitoring spots, species search, daily occurrence
filters, analysis summaries, conservation rankings, and job input/output links.

## How it fits together

```text
Frontend Nginx
  └─ /api proxy
       └─ FastAPI routes
            └─ SQLAlchemy
                 └─ SQLite for development / PostgreSQL for deployment
```

Latitude and longitude identify one canonical physical spot. Multiple source
projects can contribute to that location through `spot_sources` without creating
overlapping public map markers.

## Recommended connected setup

Keep this repository beside `cem-master` and run the combined stack from the
frontend repository:

```text
main-website/
├── cem-master/
└── cem-master-backend/
```

```bash
cd ../cem-master
docker compose up --build -d
```

See the frontend README for the full combined-stack, networking, persistence,
shutdown, and PostgreSQL instructions.

## Backend-only Docker setup

From this repository:

```bash
docker compose up --build -d
```

This starts only FastAPI at:

- API: `http://127.0.0.1:8001`
- Swagger documentation: `http://127.0.0.1:8001/docs`
- Health: `http://127.0.0.1:8001/health`

The standalone Compose file mounts `app/` and `scripts/` read-only and stores
SQLite at `/data/cem_master.db` in `cem_master_backend_data`.

Seed the standalone database with:

```bash
docker compose exec backend python scripts/seed_spots.py
```

Do not run the standalone and connected Compose stacks simultaneously because
both publish host port 8001.

## Local Python development

Create and activate a virtual environment, then install the backend dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --env-file .env --reload --port 8001
```

On Windows PowerShell, activation is:

```powershell
.\.venv\Scripts\Activate.ps1
```

## Configuration

- `DATABASE_URL`: SQLAlchemy connection URL; defaults to local SQLite.
- `CORS_ORIGINS`: comma-separated frontend origins.
- `CEM_MASTER_API_KEY`: optional key protecting `POST /api/v1/spots`.

Docker Compose accepts corresponding `BACKEND_` variables so its settings do not
collide with the backend-only `.env` file:

```dotenv
BACKEND_PORT=8001
BACKEND_DATABASE_URL=sqlite:////data/cem_master.db
BACKEND_CORS_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
BACKEND_API_KEY=
```

## Switching to PostgreSQL

No API route or query rewrite is required. `requirements.txt` already includes
`psycopg[binary]`, and SQLAlchemy selects PostgreSQL from `DATABASE_URL`.

For a PostgreSQL service named `postgres` on the same Docker bridge:

```dotenv
BACKEND_DATABASE_URL=postgresql+psycopg://cem_user:password@postgres:5432/cem_master
```

Requirements for the database container:

- Join the same Docker bridge as the backend.
- Persist `/var/lib/postgresql/data` in a named volume.
- Start and become healthy before the backend.
- Use credentials matching the connection URL.
- Back up the PostgreSQL volume/database independently.

The development SQLite volume is no longer used after switching the connection
URL, but it remains untouched until explicitly removed.

`Base.metadata.create_all()` can bootstrap an empty database. Add Alembic before
making schema changes against a populated shared or production database.

## Database tables

- `spots`: canonical coordinates and public spot metadata.
- `spot_sources`: contributing project/spot identifiers.
- `species`: taxonomy, common/scientific names, IUCN data, and species metrics.
- `spot_summaries`: spot richness, detections, acoustic indices, and assets.
- `spot_species_summaries`: all-date species-at-spot aggregates.
- `spot_species_daily`: exact daily totals used by date filters.
- `analysis_jobs`: job status, input/output URLs, filenames, and metadata.

The API stores public HTTP(S) or signed object-storage URLs. Private server paths
such as `DATA_DIR/projects/...` should be resolved inside backend/ETL code and
must not be exposed to the browser.

## Sample seed

```bash
python scripts/seed_spots.py
```

The seed is idempotent and supplies four Sanjay Van sample spots, five species,
daily detections, summaries, analysis files, and jobs. Running it again updates
those records without duplicating them. The URL values use `example.org` and are
placeholders until real object-storage or API URLs are ingested.

## Main endpoints

- `GET /health`
- `GET /api/v1/spots`
- `GET /api/v1/spots?species_id=<id>&start_date=YYYY-MM-DD&end_date=YYYY-MM-DD`
- `GET /api/v1/spots/{spot_id}`
- `POST /api/v1/spots`
- `GET /api/v1/species?search=<common-or-scientific-name>`
- `GET /api/v1/species/{species_id}`
- `GET /api/v1/spots/{spot_id}/summary`
- `GET /api/v1/spots/{spot_id}/species/{species_id}`
- `GET /api/v1/rankings/threatened-spots`

Spot catalogue responses are GeoJSON with coordinates ordered as
`[longitude, latitude]`.

## Git hygiene

The repository ignores local `.env`, virtual environments, SQLite databases,
Python caches, temporary output, logs, and editor settings. Do not
commit database files, credentials, generated analysis files, or private storage
paths.
