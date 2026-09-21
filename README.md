# cem-master-backend

API, PostgreSQL database, and background **indexer** for the public CEM Master catalogue — the interactive, read-only biodiversity map and bioacoustic intelligence dashboard at [cem-master-frontend](../cem-master-frontend).

This repository starts the entire master stack.

```text
frontend (nginx :8000) ──/api/──▶ backend (FastAPI :8001) ──▶ cem-database (PostgreSQL)
                                         │                          ▲
                                 streams 9s audio                   │
                                         ▼                          │
DATA_DIR/projects/ ─────────────▶ /data (read-only) ◀──reads── indexer (--watch)
```

---

## What the System Does

The master website is the central public showcase for continuous ecological and bioacoustic monitoring:

- **Interactive Spatial Map**: Explores monitoring spots across projects, color-coded by detection intensity, with cluster spiderfying for overlapping multi-project coordinates.
- **Species Discovery & Showcase**: Instant search across common and scientific names, showing species network occurrence, IUCN conservation status, migration classification, taxonomy, and the **global highest-confidence 9-second focal call snippet**.
- **Spot-Level Bioacoustics**:
  - **Species Richness & Bird Inventory**: Detection counts, active days, and row-level `[ 9s ]` audio call audition buttons.
  - **24-Hour Diurnal Activity Chart**: Hourly detection curves showing dawn/dusk calling patterns.
  - **24-Hour Species Heatmap Matrix**: Normalized hourly activity heatmap for the top 20 most active species.
  - **Soundscape Indices**: ACI (Acoustic Complexity), ADI (Diversity), AEI (Evenness), NDSI, Bioacoustic Index (BIO), and MFC.
  - **Seasonal & Solar Metrics**: Seasonal Concentration Index (SCI), Peak-to-Median Ratio (PMR), Kurtosis, and sunrise/weather correlations.
- **Raw Audio Recordings Browser**: Paginated raw audio files with visual waveform playback and time scrubbing.
- **Analysis Provenance & Downloads**: Links completed analysis runs directly to FileBrowser output downloads.
- **Master Indexer**: Continuously monitors `DATA_DIR/projects/`, automatically computes spot and species rollups from BirdNET detection tables, registers 9s audio snippets, and safely filters sensitive/endangered IUCN species (fail-closed).

---

## Quick start

Clone the two master repositories **side by side** — compose builds the frontend from `../cem-master-frontend`:

```text
your-workspace/
├── cem-master-backend/     <- start here
└── cem-master-frontend/    <- frontend map
```

```bash
cp .env.example .env        # set CEM_DATA_DIR_HOST to your compute data folder
./scripts/dev-up.sh -d      # starts database + API + indexer + frontend
```

- **Map page**: <http://localhost:8000>
- **API docs**: <http://localhost:8001/docs>
- **Health check**: <http://localhost:8000/backend-health> or <http://localhost:8001/health>
- **FileBrowser downloads**: <http://localhost:8097>

```bash
./scripts/dev-up.sh -d --build   # rebuild images
./scripts/dev-up.sh down         # stop containers, keep database
./scripts/dev-up.sh down -v      # stop AND DELETE the database
```

> **Why one owner**: This stack is managed centrally from `cem-master-backend` so that one `./scripts/dev-up.sh` brings up the whole system. The frontend repository defines no separate compose file to prevent configuration drift.
>
> **Live bind-mounts**: `./app` and `./scripts` in the backend, and `./index.html`, `./js`, `./styles`, `./leaflet` in the frontend are bind-mounted. Editing python or JavaScript source files only needs `docker compose restart backend` or `docker compose restart frontend`, not a full rebuild. Rebuild only when `requirements.txt`, `Dockerfile`, or `nginx.conf` changes.

---

## Directory Mounts & Volume Layout

Application code and data outputs live on the host and are bind-mounted at runtime:

| Host Folder | Container Path | Purpose & Lifecycle |
| :--- | :--- | :--- |
| `./app`, `./scripts` | `/app/app:ro`, `/app/scripts:ro` | Backend code and CLI tools. Live-mounted; update with `git pull` + restart. |
| `${MASTER_FRONTEND_CONTEXT:-../cem-master-frontend}` | `/usr/share/nginx/html:ro` | Frontend HTML/JS/CSS assets. Live-mounted. |
| `${CEM_DATA_DIR_HOST}` | `/data:ro` | Shared compute data directory (`cem-backend/data`). Mounted read-only for public indexing and audio streaming. |
| `${CEM_DATA_DIR_HOST}/logs/cem-master-backend` | `/data/logs/cem-master-backend:rw` | Persistent application log directory. |

---

## API Endpoints Reference

The FastAPI backend exposes the following REST routes (prefixed with `/api/v1`):

### 1. Spots & Spatial Discovery
| Method & Endpoint | Description |
| :--- | :--- |
| `GET /api/v1/spots` | GeoJSON FeatureCollection of public monitoring spots with coordinates, species richness, and total detections. Supports filtering by `species_id`, `migration_class`, `start_date`, and `end_date`. |
| `GET /api/v1/spots/{spot_id}` | Metadata for a single spot (ID, name, project ID, GPS coordinates). |
| `POST /api/v1/spots` | Administrative endpoint to register a spot (requires `X-API-Key`). |

### 2. Spot Analytics & Species Details
| Method & Endpoint | Description |
| :--- | :--- |
| `GET /api/v1/spots/{spot_id}/summary` | Comprehensive spot dossier: species richness, total detections, active days, soundscape indices (ACI, ADI, AEI, NDSI, BIO), 24h diurnal activity array, bird inventory with 9s call URLs, and analysis assets. |
| `GET /api/v1/spots/{spot_id}/species/{species_id}` | Detailed observation of a bird at a spot: detection count, active days, confidence metrics, 24h calling curve, daily time series, bioacoustic/solar metrics (SCI, PMR, Kurtosis, sunrise correlation), 9s focal call snippet, and analysis jobs with download links. |

### 3. Species Catalog & Global Showcase
| Method & Endpoint | Description |
| :--- | :--- |
| `GET /api/v1/species` | Search and list public bird species. Supports query search (`?search=`), migration class filter (`?migration_class=`), and returns each species with its global best 9s call snippet. |
| `GET /api/v1/species/{species_id}` | Global showcase for a species: common/scientific name, IUCN status, image & attribution, migration class, taxonomy, and the all-time highest confidence 9s audio snippet across all projects. |

### 4. Audio Streaming & Snippets
| Method & Endpoint | Description |
| :--- | :--- |
| `GET /api/v1/projects/{project}/snippets/{filename}` | Streams a 9-second focal call snippet `.wav` file with byte-range support (`Accept-Ranges: bytes`) for instant browser playback. |
| `GET /api/v1/recordings/{audio_id}/stream` | Streams a full raw audio recording `.wav` file from disk. |

### 5. Recordings Browser
| Method & Endpoint | Description |
| :--- | :--- |
| `GET /api/v1/spots/{spot_id}/recordings` | Paginated raw audio recordings captured at a spot with date/time filters, detection counts, and species tags. |
| `GET /api/v1/spots/{spot_id}/species/{species_id}/recordings` | Paginated raw audio recordings containing detections for a specific bird at a spot. |

### 6. Environment & System
| Method & Endpoint | Description |
| :--- | :--- |
| `GET /api/v1/spots/{spot_id}/environment` | Daily environmental history: sunrise/sunset times, rainfall mm, temperature min/max/mean, humidity, and severe weather indicators. |
| `GET /api/v1/rankings/threatened-spots` | Ranking of monitoring spots ordered by presence of vulnerable/threatened species (IUCN VU). |
| `POST /api/v1/indexer/projects/{project}` | Trigger on-demand re-indexing for a specific project. |
| `GET /health` | Database connection and API health status. |

---

## Configuration

Configure the stack via `.env` (copied from `.env.example`):

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `DATABASE_URL` | `postgresql+psycopg://cem_user:change-me@cem-database:5432/cem_master` | Container connection to PostgreSQL (`cem-database` service name). |
| `CEM_DATA_DIR_HOST` | `../cem-backend/data` | Host path to compute output folder, mounted read-only as `/data`. |
| `LOG_LEVEL` | `info` | Logging verbosity: `debug` (verbose traces), `info` (startup & completions), `error` (failures only). |
| `MASTER_FRONTEND_PORT` | `8000` | Host port for the public map frontend. |
| `BACKEND_PORT` | `8001` | Host port for the backend FastAPI service. |
| `MASTER_FRONTEND_CONTEXT` | `../cem-master-frontend` | Relative path to the frontend repository folder. |
| `FILEBROWSER_PUBLIC_URL` | `http://localhost:8097` | Base URL used to turn job share hashes into browser download links. |
| `INDEXER_POLL_SECONDS` | `30` | Polling interval for the background indexer watcher. |
| `CORS_ORIGINS` | `http://localhost:8000,http://127.0.0.1:8000` | Allowed CORS origins. |
| `CEM_MASTER_API_KEY` | *(blank)* | Optional key for administrative spot mutations (`POST /api/v1/spots`). |
| `DEBUG` | `false` | Legacy alias for `LOG_LEVEL=debug` (see `DEBUGGING.md`). |
| `TEST_DATABASE_URL` | `postgresql+psycopg://cem_user:change-me@localhost:5432/cem_master_test` | PostgreSQL URL for running pytest on your host machine. |

---

## Logging & Diagnostics

Logging is configured via `LOG_LEVEL` (`debug` | `info` | `error`):

```bash
# 1. Set LOG_LEVEL=debug (or LOG_LEVEL=info) in .env
# 2. Recreate containers to apply the environment change:
./scripts/dev-up.sh -d
docker compose logs -f backend indexer
```

- **Stdout & Persistent File**: Logs stream to stdout (`docker compose logs`) and are written persistently to `data/logs/cem-master-backend/app.log`.
- **Backend & Indexer Diagnostics**: Logs ASGI request timing/status, indexing inputs, spot rollups, and audio snippet stream events.
- **Frontend Diagnostics**: Injects `/runtime-debug.js` to surface network timing and snippet playback stalls in the browser console.
- For complete details, see [`DEBUGGING.md`](DEBUGGING.md).

---

## Architecture Diagram

```mermaid
flowchart TD
    subgraph Client ["Client Browser"]
        Browser["User Browser<br/>(http://localhost:8000)"]
    end

    subgraph MasterStack ["Master Stack (Docker)"]
        Frontend["Frontend (Nginx :8000)<br/>• Leaflet map & markers<br/>• Diurnal charts & heatmaps<br/>• /api/ proxy to backend"]
        Backend["Backend (FastAPI :8001)<br/>• Dashboard REST API (/api/v1)<br/>• 9-second WAV audio streaming"]
        Indexer["Master Indexer (--watch)<br/>• Reads public projects<br/>• Computes spot & species rollups<br/>• Updates global snippet registry"]
        DB[(PostgreSQL :5432<br/>Database: cem_master<br/>Owner: cem_user)]
    end

    subgraph Storage ["Host Data (Read-Only)"]
        DataDir[/"DATA_DIR/projects/<br/>• <project>/aggregate.csv<br/>• <project>/snippets/*.wav<br/>• <project>/snippets/species_snippets.json<br/>• <project>/jobs/*/job.json"/]
        FileBrowser["FileBrowser Service (:8097)<br/>(Downloadable results)"]
    end

    Browser -->|HTTP :8000| Frontend
    Frontend -->|Proxy /api/*| Backend
    Backend -->|Queries| DB
    Backend -->|Stream 9s audio| DataDir
    Indexer -->|Reads public data| DataDir
    Indexer -->|Writes rollups| DB
    Frontend -.->|Download link| FileBrowser
    DataDir --> FileBrowser
```

---

## Master Indexer & Data Flow

Species search and analytics span all public projects, so heavy aggregation happens during indexing, not during user page requests.

### What the Indexer Does:
1. Walks `DATA_DIR/projects/` and checks `project.json` (only indexing projects where `visibility == "public"`).
2. Reads detection aggregates (`aggregate.csv`), normalizes species names, and filters sensitive/endangered IUCN categories (fail-closed).
3. Computes:
   - **Spot Summaries**: Species richness, total detections, active recording days.
   - **Spot Species Summaries**: Per-bird detection counts, active days, 24-hour hourly activity array `[0..23]`, and daily/monthly time series.
   - **Multi-Project Spots**: When multiple projects monitor the same GPS location (e.g. `IITDELHI`), each project gets its own distinct `Spot` record with unmixed hourly counts (spiderfied cleanly on the map).
   - **9-Second Audio Snippets**: Ingests `snippets/species_snippets.json`, attaching spot-level snippets to each bird, and updating the global all-time highest-confidence showcase in `Species`.
   - **Soundscape & Ecological Indices**: Attaches ACI, ADI, AEI, NDSI, SCI, PMR, and Kurtosis metrics.
   - **Analysis Jobs**: Registers completed runs and FileBrowser download links.
4. **Idempotent & Pruning**: Re-indexing unchanged projects changes nothing; removed or unpublished projects are cleanly pruned from the database.

### Running the Indexer Manually:

```bash
./scripts/reindex.sh                     # index all public projects
./scripts/reindex.sh --dry-run           # dry run report (writes nothing)
./scripts/reindex.sh --project <name>    # index a single project
```

---

## Database & Schema Migrations

The database is PostgreSQL (`cem_master`), owned by `cem_user`. Schema definitions are managed via Alembic:

```bash
# Create a new migration revision
docker compose exec backend alembic revision --autogenerate -m "description"

# Apply pending migrations
docker compose exec backend alembic upgrade head
```

### Running Tests:

```bash
# In container
docker compose exec backend python -m pytest

# On host machine (requires TEST_DATABASE_URL)
set -a && source .env && set +a
python3 -m pytest
```

---

## Helpful Scripts

| Script | Purpose |
| :--- | :--- |
| `scripts/dev-up.sh` | Start, stop, or rebuild the master stack (`-d`, `down`, `down -v`). |
| `scripts/reindex.sh` | Trigger indexing on demand for all or specific projects. |
| `scripts/seed_spots.py` | Insert sample monitoring spots for testing without raw audio data. |
| `scripts/dev_compute_e2e.py` | End-to-end testing loop: raw audio → BirdNET → publish → index → map. |
| `tests/fixtures/build_fixture.py` | Generate a synthetic `DATA_DIR` fixture for automated tests. |
