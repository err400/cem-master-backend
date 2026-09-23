# cem-master-backend

API, Web Dashboard, PostgreSQL database, and background **indexer** for the public CEM Master catalogue — the interactive, read-only biodiversity map and bioacoustic intelligence dashboard at [cem-master-frontend](../cem-master-frontend).

This repository starts the unified master stack (FastAPI serves both the UI and REST API in a single container):

```text
Browser (http://localhost:8000)
    │
    ▼
unified app (FastAPI :8000) ───────────────▶ cem-database (PostgreSQL)
  • Serves HTML/JS/CSS on /                         ▲
  • REST API on /api/v1                             │
  • Streams 9s bird audio                           │
    │                                               │
    ▼                                               │
DATA_DIR/projects/ ────────▶ /data (read-only) ◀──reads── indexer (--watch)
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

Clone the two master repositories **side by side** — compose mounts the frontend into the backend container from `../cem-master-frontend`:

```text
your-workspace/
├── cem-master-backend/     <- start here
└── cem-master-frontend/    <- frontend map
```

```bash
cp .env.example .env        # set CEM_DATA_DIR_HOST to your compute data folder
./scripts/dev-up.sh -d      # starts database + app + indexer
```

- **Interactive Map & Dashboard**: <http://localhost:8000>
- **API Interactive Docs**: <http://localhost:8000/docs>
- **Service Health check**: <http://localhost:8000/health> or <http://localhost:8000/backend-health>
- **FileBrowser downloads**: <http://localhost:8097>

```bash
./scripts/dev-up.sh -d --build   # rebuild images
./scripts/dev-up.sh down         # stop containers, keep database
./scripts/dev-up.sh down -v      # stop AND DELETE the database
```

> **Single Web Container**: In alignment with cluster standards (CoreStack Item #6), backend and frontend run in a single container on port `8000`. FastAPI serves the static frontend assets on `/` and the REST API on `/api/v1/`.
>
> **Live bind-mounts**: The entire repo (`.`) and frontend assets (`${MASTER_FRONTEND_CONTEXT}`) are bind-mounted read-only. Editing Python, Alembic migrations, or JavaScript source files takes effect immediately without rebuilding the container.

---

## Directory Mounts & Volume Layout (CoreStack Checklist §1)

In alignment with cluster service standards (Checklist §1 and Runbook §2), the Docker image contains runtime dependencies only (`requirements.txt`). Code, frontend assets, and data live on the host and are bind-mounted at runtime:

| Host Folder | Container Path | Purpose & Lifecycle |
| :--- | :--- | :--- |
| `.` (repo checkout) | `/app:ro` | Backend code, scripts, and Alembic migrations. Live-mounted; update with `git pull` + restart without rebuilding the Docker image. |
| `${MASTER_FRONTEND_CONTEXT:-../cem-master-frontend}` | `/app/frontend:ro` | Frontend HTML/JS/CSS assets, served directly by FastAPI on `/`. |
| `${CEM_DATA_DIR_HOST}` | `/data:ro` | Shared compute datasets (`/data/projects/`). Mounted read-only for public catalog indexing and 9s audio streaming. |
| `${CEM_DATA_DIR_HOST}/logs/cem-master-backend` | `/data/logs/cem-master-backend:rw` | Application and ASGI diagnostic logs (`app.log`). |
| *(models)* | *N/A* | The master catalog performs database indexing and aggregation; no AI/ML weight checkpoints (.pt / .onnx) are used. |

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
| `PORT` | `8000` | Host port on which the unified container (UI + REST API) is published. |
| `DATABASE_URL` | `postgresql+psycopg://cem_user:change-me@cem-database:5432/cem_master` | Container connection to PostgreSQL (`cem-database` service name). |
| `CEM_DATA_DIR_HOST` | `../cem-backend/data` | Host path to compute output folder, mounted read-only as `/data`. |
| `LOG_LEVEL` | `info` | Logging verbosity: `debug` (verbose traces), `info` (startup & completions), `error` (failures only). |
| `MASTER_FRONTEND_CONTEXT` | `../cem-master-frontend` | Relative path to the frontend assets folder (mounted at `/app/frontend`). |
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
- **Frontend Diagnostics**: Dynamic `/runtime-debug.js` surfaces network timing and snippet playback stalls in the browser console.
- For complete details, see [`DEBUGGING.md`](DEBUGGING.md).

---

## Architecture Diagram

```mermaid
flowchart LR
    Browser["User browser<br/>http://localhost:8000"]

    subgraph Runtime["Docker runtime"]
        App["backend service<br/>FastAPI on port 8000<br/>serves UI and API<br/>no separate frontend container"]
        Indexer["indexer service<br/>watch mode<br/>builds catalog rollups"]
    end

    subgraph MountedCode["Mounted code"]
        BackendCode["cem-master-backend<br/>mounted at /app<br/>read only"]
        FrontendCode["cem-master-frontend<br/>mounted at /frontend<br/>read only"]
    end

    subgraph HostData["Host data"]
        Projects["data/projects<br/>public project outputs<br/>snippet audio<br/>job metadata"]
        Logs["data/logs/cem-master-backend<br/>app.log"]
        Retention["outputs.yaml<br/>public<br/>private persistent<br/>delete"]
    end

    subgraph SharedServices["Shared services"]
        DB[("central PostgreSQL<br/>cem_master")]
        FileBrowser["FileBrowser<br/>download UI"]
        DataService["host data service<br/>retention worker"]
    end

    Browser -->|"same origin UI"| App
    Browser -->|"same origin API"| App

    BackendCode -->|"application code"| App
    BackendCode -->|"indexer code"| Indexer
    FrontendCode -->|"static assets"| App

    App -->|"read audio and job metadata"| Projects
    App -->|"write application logs"| Logs
    App -->|"query catalog"| DB

    Indexer -->|"read public projects"| Projects
    Indexer -->|"write rollup tables"| DB
    Indexer -->|"write indexer logs"| Logs

    Browser -.->|"download links"| FileBrowser
    FileBrowser -->|"serves project outputs"| Projects

    Retention -->|"policy file"| DataService
    DataService -->|"publish or keep or delete"| Projects
    DataService -->|"preserve logs"| Logs

    classDef client fill:#f5f7ff,stroke:#6d77c8,color:#1f2555
    classDef container fill:#e8f2ff,stroke:#2f6fed,color:#10233f
    classDef code fill:#f3ecff,stroke:#7d4cc2,color:#291642
    classDef storage fill:#edf7ed,stroke:#4d9f4d,color:#173817
    classDef service fill:#fff4df,stroke:#c47f00,color:#3f2a00

    class Browser client
    class App,Indexer container
    class BackendCode,FrontendCode code
    class Projects,Logs,Retention storage
    class DB,FileBrowser,DataService service
```

---

## Output Retention (`outputs.yaml`)

Output lifecycle policies under `data/` are declared in [`outputs.yaml`](outputs.yaml) and enforced by the cluster's **Host Data Service**:

- **`data/projects/`** (`mode: public`, `ttl_days: null`): Public project datasets, detection summaries, acoustic indices, and 9-second bird call audio snippets.
- **`data/logs/cem-master-backend/`** (`mode: private_persistent`, `ttl_days: null`): Persistent application and ASGI diagnostic log files (`app.log`).
- **`data/scratch/`** (`mode: delete`, `ttl_days: 7`): Ephemeral working files and temporary data; automatically deleted by the host data service after 7 days.


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

The service requires PostgreSQL (no SQLite is used). In production/cluster deployments, it connects to the central PostgreSQL server instance:

| Property | Value | Description |
| :--- | :--- | :--- |
| **Database Name** | `cem_master` | Production master catalog database. |
| **Owner / Role** | `cem_user` | Database user owning the tables and schema. |
| **Connection String** | `DATABASE_URL` in `.env` | e.g. `postgresql+psycopg://cem_user:password@cem-database:5432/cem_master` |
| **Migrations** | Alembic | Version-controlled schema migrations executed against the central instance. |
| **Access Provisioning** | Cluster DBA | Request database creation and credentials from the cluster database administrator. |

### Schema Management with Alembic:

```bash
# Create a new migration revision
docker compose exec backend alembic revision --autogenerate -m "description"

# Apply pending migrations against the database
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
