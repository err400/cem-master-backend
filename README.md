# cem-master-backend

API, PostgreSQL database, and background **indexer** for the public CEM Master catalogue — the interactive, read-only biodiversity map at [cem-master](../cem-master).

This repository starts the entire master stack.

```text
frontend (nginx :8000) ──/api/──▶ backend (FastAPI :8001) ──▶ cem-database (PostgreSQL)
                                         │                          ▲
                                 streams 9s audio                   │
                                         ▼                          │
DATA_DIR/projects/ ─────────────▶ /data (read-only) ◀──reads── indexer (--watch)
```

The API answers requests from PostgreSQL and streams 9-second audio snippet clips directly from `DATA_DIR`. The indexer runs in the background, reading public project detections and updating the database.

---

## Quick start

Clone the two master repositories **side by side** — compose builds the frontend from `../cem-master` (or `../cem-master-frontend`):

```text
your-workspace/
├── cem-master-backend/     <- start here
└── cem-master/             <- frontend map
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

Application code, models, and data outputs live on the host and are bind-mounted at runtime:

| Host Folder | Container Path | Purpose & Lifecycle |
| :--- | :--- | :--- |
| `./app`, `./scripts` | `/app/app:ro`, `/app/scripts:ro` | Backend code and CLI tools. Live-mounted; update with `git pull` + restart. |
| `${MASTER_FRONTEND_CONTEXT:-../cem-master}` | `/usr/share/nginx/html:ro` | Frontend HTML/JS/CSS assets. Live-mounted. |
| `${CEM_DATA_DIR_HOST}` | `/data:ro` | Shared compute data directory (`cem-backend/data`). Mounted read-only for public indexing and audio streaming. |

---

## Configuration

`.env`, read automatically by Docker Compose:

| Variable | Default | Purpose & Meaning |
| :--- | :--- | :--- |
| `DATABASE_URL` | `postgresql+psycopg://cem_user:change-me@cem-database:5432/cem_master` | Container connection to PostgreSQL (`cem-database` service name). |
| `CEM_DATA_DIR_HOST` | `../cem-backend/data` | Host path to compute output folder, mounted read-only as `/data`. |
| `MASTER_FRONTEND_PORT` | `8000` | Host port for the public map frontend. |
| `BACKEND_PORT` | `8001` | Host port for the backend FastAPI service. |
| `MASTER_FRONTEND_CONTEXT` | `../cem-master` | Relative path to the frontend repository folder. |
| `FILEBROWSER_PUBLIC_URL` | `http://localhost:8097` | Base URL used to turn job share hashes into browser download links. |
| `INDEXER_POLL_SECONDS` | `30` | Polling interval for the background indexer watcher. |
| `CORS_ORIGINS` | `http://localhost:8000,http://127.0.0.1:8000` | Allowed CORS origins. |
| `CEM_MASTER_API_KEY` | *(blank)* | Optional key for administrative spot mutations (`POST /api/v1/spots`). |
| `TEST_DATABASE_URL` | `postgresql+psycopg://cem_user:change-me@localhost:5432/cem_master_test` | PostgreSQL URL for running pytest on your host machine. |

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

## Output Retention (`outputs.yaml`)

Output lifecycle and cleanup policies under `data/` follow [`outputs.yaml`](outputs.yaml):

- **`data/projects/`** (`mode: public`): Public ecological monitoring projects, detection CSVs, 9s audio snippet WAVs, and analysis assets.
- **`data/logs/cem-master-backend/`** (`mode: private_persistent`): Application and indexer logs.
- **`data/scratch/`** (`mode: delete`, `ttl_days: 7`): Temporary indexing files deleted after 7 days.

---

## Helpful Scripts

| Script | Purpose |
| :--- | :--- |
| `scripts/dev-up.sh` | Start, stop, or rebuild the master stack (`-d`, `down`, `down -v`). |
| `scripts/reindex.sh` | Trigger indexing on demand for all or specific projects. |
| `scripts/seed_spots.py` | Insert sample monitoring spots for testing without raw audio data. |
| `scripts/dev_compute_e2e.py` | End-to-end testing loop: raw audio → BirdNET → publish → index → map. |
| `tests/fixtures/build_fixture.py` | Generate a synthetic `DATA_DIR` fixture for automated tests. |
