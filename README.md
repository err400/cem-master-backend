# CEM Master — Continuous Ecological Monitoring Catalogue

Public biodiversity catalogue, bioacoustic indexer, and interactive map interface for the Continuous Ecological Monitoring (CEM) network.

---

## 1. Directory Mounts & Volume Layout (§1)

Code, models, and data are strictly separated. No application code, ML model weights, or compute outputs are baked into the Docker image. Everything is bind-mounted at runtime:

| Host Folder | Container Path | Purpose & Lifecycle |
| :--- | :--- | :--- |
| `code/` (`./app`, `./scripts`, `../cem-master-frontend`) | `/app` (or `/usr/share/nginx/html`) | Git checkout. Updated via `git pull` + container restart. |
| `models/` (`./models`) | `/app/models` | ML model weights, classifiers, checkpoints (`.pt`, `.onnx`, `.joblib`). Preserved across restarts. |
| `data/` (`../cem-backend/data`) | `/data` (or `/app/data`) | Input audio recordings, BirdNET detection tables, 9s audio snippets, acoustic indices, caches, and compute outputs. Mounted read-only for public indexing. |

- **Job Outputs**: Written under `data/` only (never inside the container layer).
- **Git Ignore**: `.gitignore` excludes large audio files, model weights, and generated outputs.
- **Acceptance**: Restarting or recreating containers preserves all data, logs, and models; `git pull` updates application code without modifying `data/` or `models/`.

---

## 2. Compute Orchestration: Airflow vs Local (§2)

The master stack handles detection indexing and data aggregation either locally or through Apache Airflow based strictly on `AIRFLOW_API_BASE` in `.env`:

| `AIRFLOW_API_BASE` in `.env` | Behavior |
| :--- | :--- |
| **Set (non-empty)** (e.g. `http://airflow:8080`) | Triggers and polls Airflow DAG (`/api/v1/dags/cem_indexing_pipeline/...`). Same-origin proxy prevents direct browser exposure to Airflow. |
| **Empty / Unset** | Runs indexing and rollups locally within the container process (`python -m app.indexer --data-dir /data --watch`). |

- **Airflow DAG ID**: Configured via `AIRFLOW_DAG_ID=cem_indexing_pipeline`.
- **Worker Callback**: Configured via `CORESTACK_API_BASE=http://backend:8001`.
- **Acceptance**: The exact same Docker image runs on a developer laptop (local compute) and on the cluster (Airflow orchestration) by changing `.env` alone.

---

## 3. Docker Registry & Image Pull (§3)

Production images are published to GitHub Container Registry (GHCR) and Docker Hub with dependency layers pre-cached:

```bash
# Pull backend & indexer image
docker pull ghcr.io/corestack-org/cem-master-backend:latest

# Pull unified frontend map image
docker pull ghcr.io/corestack-org/cem-master-frontend:latest
```

---

## 4. Authentication & Google SSO (§4)

- **Public Catalog Access**: Spot viewing, species search, diurnal heatmaps, and 9s audio snippet streaming are open and read-only.
- **Protected APIs & Spot Mutations**: Administrative operations (`POST /api/v1/spots`) and compute triggers require either:
  1. Google Single Sign-On (OAuth 2.0 / Google Identity token), or
  2. Administrative API key (`X-API-Key: $BACKEND_API_KEY`).
- **Environment Variables**: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_REDIRECT_URI` are loaded exclusively from `.env`. No secrets are committed to git.

---

## 5. Logging & Observability (§5)

All services write structured application logs to host-mounted storage under `data/logs/<application_name>/`:

- **Host Path**: `data/logs/cem-master-backend/` (Backend & Indexer) and `data/logs/cem-master-frontend/` (Nginx/UI).
- **Log Granularity (`LOG_LEVEL` in `.env`)**:
  - `debug`: Verbose request/response traces, Airflow polling logs, and indexer traversal details.
  - `info` *(Default)*: Startup notices, auth validation, indexing progress, and job summaries.
  - `error`: Unhandled exceptions, failed jobs, Airflow connection failures, and database errors.

```bash
# Tail backend logs directly on host
tail -f data/logs/cem-master-backend/app.log

# Stream container logs via Docker Compose
docker compose logs -f backend indexer
```

---

## 6. Unified Single-Origin Service (§6) & Frontend API Configuration (§7)

- **Single Origin / Single Port**: The public frontend (Nginx on port `8000`) acts as the single entry point, serving static assets and reverse-proxying `/api/*` requests to the FastAPI backend (`backend:8001`) over the internal Docker network.
- **No Hardcoded URLs**: `API_BASE_URL` in `.env` configures the backend target. It defaults to relative `/` (same-origin), ensuring the application runs out-of-the-box in local development, staging, or production without code edits.

---

## 8. Architecture Diagram (§8)

```mermaid
flowchart TD
    subgraph Client ["Client Browser"]
        Browser["User Browser<br/>(http://localhost:8000)"]
    end

    subgraph AppStack ["CEM Master Stack (Docker)"]
        Frontend["Frontend (Nginx :8000)<br/>• Static HTML/CSS/JS<br/>• Same-origin /api/ proxy"]
        Backend["Backend (FastAPI :8001)<br/>• REST API & Auth<br/>• 9s Audio Snippet Streamer"]
        Indexer["Master Indexer (--watch)<br/>• Detection Rollups<br/>• Species Showcase Sync"]
    end

    subgraph ComputeChoice ["Compute & Indexing Orchestration"]
        AirflowCheck{"AIRFLOW_API_BASE set?"}
        Airflow["Airflow-STACD Docker<br/>(DAG Trigger & Poll)"]
        LocalWorker["Local Indexer Process<br/>(pandas in-container)"]
    end

    subgraph Storage ["Persistent Host Mounts"]
        CentralDB[(Central PostgreSQL<br/>cem_master DB)]
        DataDir[/"Host data/<br/>• projects/<br/>• snippets/<br/>• detections.csv"/]
        LogsDir[/"Host data/logs/cem-master-backend/"/]
        FileBrowser["FileBrowser Service<br/>(Artifact Download UI)"]
        HostDataService["Host Data Service<br/>(Enforces outputs.yaml retention)"]
    end

    Browser -->|HTTP :8000| Frontend
    Frontend -->|Proxy /api/*| Backend
    Backend -->|Read/Write| CentralDB
    Backend -->|Stream 9s audio| DataDir

    Indexer --> AirflowCheck
    AirflowCheck -->|Yes| Airflow
    AirflowCheck -->|No| LocalWorker
    Airflow -->|Write Rollups| CentralDB
    LocalWorker -->|Write Rollups| CentralDB
    LocalWorker -->|Read Detections| DataDir

    Backend -.->|Write logs| LogsDir
    Indexer -.->|Write logs| LogsDir

    DataDir --> FileBrowser
    DataDir --> HostDataService
```

---

## 9. Central PostgreSQL Database (§9)

The master stack connects to the central PostgreSQL cluster instance via standard connection strings:

```env
DATABASE_URL=postgresql+psycopg://cem_user:change-me@cem-database:5432/cem_master
```

- **Database Name**: `cem_master`
- **Role Owner**: `cem_user` (Access provisioned by Server DBA)
- **Migrations**: Managed via Alembic (`alembic upgrade head`). No SQLite is used in production.
- **Persistence**: Recreating containers preserves all catalog data since rows reside in the central Postgres instance.

---

## 10. Output Retention Policy (`outputs.yaml`) (§10)

Output lifecycle and cleanup policies under `data/` are governed by [`outputs.yaml`](outputs.yaml), enforced automatically by the host data service:

```yaml
application: cem-master
outputs:
  - path: data/projects/
    mode: public
    ttl_days: null
    description: Public ecological monitoring projects, detections, audio snippets, and indices
  - path: data/logs/cem-master-backend/
    mode: private_persistent
    ttl_days: null
    description: Master backend and indexer application logs
  - path: data/scratch/
    mode: delete
    ttl_days: 7
    description: Temporary extraction and indexing files; host data service deletes after 7 days
```

- **`public`**: Shareable catalog assets, 9s audio snippets, and public project detections.
- **`private_persistent`**: Application log files kept on disk across container recreations.
- **`delete`**: Ephemeral scratch data deleted automatically after `ttl_days`.

---

## Quick Start & Operations

### 1. Configuration Setup
```bash
cp .env.example .env
# Edit .env and verify DATABASE_URL and CEM_DATA_DIR_HOST
```

### 2. Start the Stack
```bash
# Start backend, indexer, and frontend
./scripts/dev-up.sh -d

# Check running status
docker compose ps
```

- **Frontend Map**: <http://localhost:8000>
- **API Documentation**: <http://localhost:8001/docs>
- **Health Check**: <http://localhost:8000/backend-health>

### 3. Database Migrations & Testing
```bash
# Run migrations
docker compose exec backend alembic upgrade head

# Run test suite
docker compose exec backend pytest
```

### 4. On-Demand Indexing
```bash
# Index all public projects
./scripts/reindex.sh

# Re-index specific project
./scripts/reindex.sh --project <project_name>
```
