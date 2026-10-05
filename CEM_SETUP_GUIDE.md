# CEM first-time setup and deployment

For local setup, start with [the short local walkthrough](docs/local-setup.md).
This document contains the full configuration reference and production steps.

This guide matches the current Compose files. Run commands in **Bash** on Linux
or macOS (on Windows, use WSL with Docker integration). Production instructions
below cover a **single Linux server with a local PostgreSQL container**. An
existing cluster/database has a separate migration path below.

## 1. Files and prerequisites

Clone the four repositories into one parent folder as shown below. Use the
repository names consistently throughout deployment; do not use older zipped copies:

```text
cem-master/
├── cem-backend/          # compute API, pipeline, docker-compose.yml
├── cem-frontend/          # compute UI and Dockerfile
├── cem-master-backend/    # master API, indexer, migrations, compose files
└── cem-master-frontend/   # master static website
```

Repositories can also live elsewhere: set absolute paths in the two `.env` files. Both backends must use the **same physical data folder**.
Paths in `.env` refer to the Docker host, not paths inside a container.

Required: Docker Engine with Compose v2 on Linux, or running Docker Desktop
on a laptop; Git; Bash; Python 3 for generating configuration; curl. The first build
needs internet access to download images and Python dependencies. The compute
image includes large BirdNET/TensorFlow dependencies and can take time.

Verify before continuing:

```bash
docker version
docker compose version
docker info
git --version
python3 --version
curl --version
```

If Docker is missing, have the server administrator install Docker Engine and
the Compose plugin for the server OS. If Docker commands require privileges,
use an account authorized to run Docker. No host Python dependency installation
is needed for the Docker setup: each Dockerfile installs its requirements.

For a fresh installation, choose a new workspace path where your account can
write, then clone all four repositories. Replace the example path below:

```bash
export CEM_WORKSPACE="/absolute/path/to/cem-master"
mkdir -p "$CEM_WORKSPACE"
cd "$CEM_WORKSPACE"
git clone https://github.com/err400/cem-backend.git cem-backend
git clone https://github.com/err400/cem-frontend.git cem-frontend
git clone https://github.com/err400/cem-master-backend.git cem-master-backend
git clone https://github.com/err400/cem-master-frontend.git cem-master-frontend
```

If the repositories are already checked out, skip cloning and set
`CEM_WORKSPACE` to their parent directory. In a new terminal, set this path again.
Confirm the expected files exist:

```bash
export CEM_WORKSPACE="/absolute/path/to/cem-master"
cd "$CEM_WORKSPACE"
test -f cem-backend/docker-compose.yml
test -f cem-frontend/Dockerfile
test -f cem-master-backend/compose.yaml
test -f cem-master-frontend/index.html
```

Every `test` must succeed. On a first setup only, create `.env` files without
overwriting existing configuration:

```bash
cd "$CEM_WORKSPACE/cem-backend"
test -f .env || cp .env.example .env
mkdir -p data/projects logs
cd "$CEM_WORKSPACE/cem-master-backend"
test -f .env || cp .env.example .env
```

## 2. Configure the shared paths and database

The following command preserves unrelated settings and sets the paths for this
layout. It generates a matching database password and master API key for a **new** installation.
Do not run it to change credentials on an already initialized database: changing
`.env` does not change PostgreSQL's stored password.

```bash
cd "$CEM_WORKSPACE"
python3 - <<'CONFIG'
import os
import secrets
from pathlib import Path

root = Path(os.environ["CEM_WORKSPACE"]).resolve()
os.umask(0o077)
def update(path, values):
    lines = path.read_text().splitlines()
    lines = [line for line in lines if line.split("=", 1)[0] not in values]
    lines.extend(f"{key}={value}" for key, value in values.items())
    path.chmod(0o600)
    path.write_text("\n".join(lines) + "\n")

password = secrets.token_hex(24)
update(root / "cem-backend/.env", {
    "CEM_DATA_DIR_HOST": str(root / "cem-backend/data"),
    "COMPUTE_FRONTEND_CONTEXT": str(root / "cem-frontend"),
    "SERVER_BASE_URL": "http://localhost:8002",
    "ALLOWED_ORIGINS": "http://localhost:8080,http://127.0.0.1:8080",
    "FILEBROWSER_BASE_URL": "",
    "RETENTION_HOURS": "0",
})
update(root / "cem-master-backend/.env", {
    "CEM_DATA_DIR_HOST": str(root / "cem-backend/data"),
    "MASTER_FRONTEND_CONTEXT": str(root / "cem-master-frontend"),
    "POSTGRES_USER": "cem_user",
    "POSTGRES_PASSWORD": password,
    "BACKEND_API_KEY": secrets.token_hex(32),
    "POSTGRES_DB": "cem_master",
    "DATABASE_URL": f"postgresql+psycopg://cem_user:{password}@cem-database:5432/cem_master",
    "TEST_DATABASE_URL": f"postgresql+psycopg://cem_user:{password}@127.0.0.1:5432/cem_master_test",
    "BACKEND_CORS_ORIGINS": "http://localhost:8000,http://127.0.0.1:8000",
    "API_BASE_URL": "",
    "COMPUTE_FRONTEND_URL": "http://localhost:8080/",
    "FILEBROWSER_PUBLIC_URL": "",
})
CONFIG
chmod 600 cem-backend/.env cem-master-backend/.env
```

The configuration script writes generated secrets only to private `.env` files
with permissions `600`; it does not print them. The checked-in `.env.example`
files contain example defaults, not deployment credentials. Run this script
before Compose to replace the example database password and create an API key.
Never copy a populated `.env`, a generated credential, or database backup into the guide or
repository. Both backend repositories already ignore `.env` files in Git.

Optional integrations include example/default credentials. Current compute
Compose also has `admin` fallbacks for Airflow/FileBrowser passwords, so set
actual private credentials before enabling either integration; blank values are
not authentication configuration.

`RETENTION_HOURS=0` disables compute's automatic job-output deletion. The default
is 168 hours; choose a retention policy deliberately if this server should purge
old outputs. Google Drive, Airflow, Earth Engine and FileBrowser are optional;
leave their integrations disabled for the initial BirdNET setup.

For production, complete section 5 **now**, before starting services.
For a laptop, continue directly to section 3.

## 3. Build, migrate, then start

Run these commands in order. The explicit Alembic step ensures the schema exists
before the indexer starts. Stop if any build or migration command fails.

```bash
cd "$CEM_WORKSPACE/cem-backend"
docker compose config --quiet
docker compose up --build -d api frontend
docker compose ps
docker compose logs --tail=50 api
curl --fail http://localhost:8002/health

cd "$CEM_WORKSPACE/cem-master-backend"
docker network inspect cem_master_network >/dev/null 2>&1 || docker network create cem_master_network

# Laptop commands. For production use the cem_compose function from section 5.
cem_compose() { docker compose -f compose.yaml -f compose.local.yaml "$@"; }
cem_compose config --quiet
cem_compose build backend indexer
# Prepare only the writable master log directory for the image's cem user.
cem_compose run --rm --no-deps --user root backend sh -ec 'mkdir -p /data/logs/cem-master-backend; chown cem:cem /data/logs/cem-master-backend'
cem_compose up -d cem-database
```

Wait for PostgreSQL readiness (up to 60 seconds):

```bash
DB_READY=false
for attempt in $(seq 1 30); do
  if cem_compose exec -T cem-database pg_isready -U cem_user -d cem_master; then
    DB_READY=true
    break
  fi
  sleep 2
done
if [ "$DB_READY" != true ]; then
  echo "Database not ready; inspect logs before continuing."
  cem_compose logs --tail=100 cem-database
fi
```

Continue **only if `DB_READY` is `true`**:

```bash
cem_compose run --rm --no-deps backend python -m alembic upgrade head
cem_compose run --rm --no-deps backend python -m alembic current
cem_compose up -d backend indexer
cem_compose ps
cem_compose logs --tail=80 backend indexer
```

Alembic is already in `cem-master-backend/requirements.txt` and installed by its
Dockerfile. Run it **inside the backend image**, from the backend directory.
The local overlay also migrates on API startup; the base `compose.yaml` alone
does **not**. There is no need to create a new migration on first setup: apply
the checked-in migrations with `upgrade head`.

## 4. Verify the complete setup

```bash
curl --fail http://localhost:8000/health
curl --fail http://localhost:8000/api/v1/spots
cem_compose exec -T cem-database psql -U cem_user -d cem_master -c '\dt'
cem_compose exec -T backend python -m alembic current
cem_compose exec -T backend python -m alembic heads
cem_compose exec -T indexer ls -ld /data/projects
```

The health response should report `status: ok`; `current` and `heads` should
show the same revision. Health alone checks database connectivity, so also
check the tables and spots endpoint. An empty map is expected before publishing.

Open the master website at **http://localhost:8000**, API docs at
**http://localhost:8000/docs**, and compute at **http://localhost:8080**.
The master backend serves the frontend itself: do not start a separate master
frontend container. No separate master frontend `.env` is required in this path.

To verify real data: create a project and spot with coordinates in compute,
upload WAV audio, run **server** BirdNET analysis, wait for completion, then
Make Public. Use filenames such as `SPOT1_20261006_060000.wav`
(`SPOTNAME_YYYYMMDD_HHMMSS.wav`) and an analysis date range containing that date.
The map should update after the next indexer poll (default 30 seconds).

To force a refresh:

```bash
cem_compose exec -T backend python -m app.indexer --data-dir /data --all
cem_compose logs --tail=100 indexer
```

For publication API commands and diagnosing missing projects, see
[Publication and indexer setup](docs/first-time-local-publication.md).

## 5. Production on one Linux server

The deployment uses these confirmed website URLs:

- Master: https://www.cse.iitd.ernet.in/act4dws5/bio-master/
- Compute UI: https://www.cse.iitd.ernet.in/act4dws5/bio/
- Browser origin for both: `https://www.cse.iitd.ernet.in`

The website URLs have different paths but the **same origin**. CORS and Google
OAuth authorized JavaScript origins use only the scheme and hostname, not
`/act4dws5/bio/` or `/act4dws5/bio-master/`.

Before section 3, confirm the **compute API base URL** with the server
administrator. The supplied compute URL identifies the UI; it does not establish
where the proxy exposes the compute backend. Do not infer `SERVER_BASE_URL`
solely from the UI address.

Edit `.env` files:

| File | Setting | Production value |
|---|---|---|
| compute | `SERVER_BASE_URL` | Browser-accessible HTTPS compute API URL |
| compute | `ALLOWED_ORIGINS` | `https://www.cse.iitd.ernet.in` |
| compute | `COMPUTE_BACKEND_PORT` | `127.0.0.1:8002` when proxy is on this host |
| compute | `COMPUTE_FRONTEND_PORT` | `127.0.0.1:8080` when proxy is on this host |
| master | `PORT` | `127.0.0.1:8000` when proxy is on this host |
| master | `POSTGRES_PORT` | `127.0.0.1:5432` |
| master | `BACKEND_CORS_ORIGINS` | `https://www.cse.iitd.ernet.in` |
| master | `COMPUTE_FRONTEND_URL` | `https://www.cse.iitd.ernet.in/act4dws5/bio/` |
| master | `BACKEND_API_KEY` | A generated secret for protected master mutation endpoints |
| both | `DEBUG` | `false` |

Section 2 generates `BACKEND_API_KEY` directly into the private master `.env`
without printing it. This protects the relevant master API
endpoints; it does not provide authentication for the compute service. Use the
server's access controls for compute as required by the deployment.

Use the following deployment values in `cem-master-backend/.env` after section
2's initial configuration generation:

```dotenv
BACKEND_CORS_ORIGINS=https://www.cse.iitd.ernet.in
API_BASE_URL=https://www.cse.iitd.ernet.in/act4dws5/bio-master/api
COMPUTE_FRONTEND_URL=https://www.cse.iitd.ernet.in/act4dws5/bio/
```

In `cem-backend/.env`:

```dotenv
ALLOWED_ORIGINS=https://www.cse.iitd.ernet.in
# Set SERVER_BASE_URL to the confirmed public COMPUTE API base, not blindly to the UI URL.
```

Master API requests should reach
`https://www.cse.iitd.ernet.in/act4dws5/bio-master/api/api/v1/spots`.
The current deployment uses an extra `/api` proxy prefix before the backend's
own `/api/v1` routes; the repeated `/api/api/v1` is intentional for this proxy.
Strip `/act4dws5/bio-master/api/` when forwarding API traffic to the backend.
The website/static assets remain under `/act4dws5/bio-master/`.
Forward the runtime configuration route too; it supplies `API_BASE_URL` and
`COMPUTE_FRONTEND_URL` to the browser.

If the compute proxy exposes backend routes under the **same** `/act4dws5/bio/`
prefix as the UI, use:

```dotenv
SERVER_BASE_URL=https://www.cse.iitd.ernet.in/act4dws5/bio
```

This value is conditional: `/act4dws5/bio/health` must route to compute backend
`/health`, and `/act4dws5/bio/api/v1/...` must route to compute backend
`/api/v1/...`, while the remaining UI routes go to the compute frontend.
If the backend uses a different public prefix, set that base instead. The
frontend appends `/health` and `/api/v1/...`; do not append `/api/v1` to the base.

Verify after deployment:

```bash
curl --fail https://www.cse.iitd.ernet.in/act4dws5/bio-master/api/health
curl --fail https://www.cse.iitd.ernet.in/act4dws5/bio-master/api/api/v1/spots
curl --fail https://www.cse.iitd.ernet.in/act4dws5/bio-master/js/config.js
# Set this to the API base confirmed by the server administrator:
export COMPUTE_API_BASE="https://REPLACE_WITH_CONFIRMED_COMPUTE_API_BASE"
curl --fail "$COMPUTE_API_BASE/health"
```

Confirm the master config response contains the deployment values above, and
that API responses are JSON rather than an HTML frontend fallback. If `/docs`
is needed under the proxy prefix, also configure FastAPI/proxy root-path handling
so Swagger fetches the correctly prefixed OpenAPI URL.

Create a production command overlay to disable code reload and make migration
failure stop startup:

```bash
cd "$CEM_WORKSPACE/cem-master-backend"
cat > compose.production.yaml <<'YAML'
services:
  backend:
    command:
      - sh
      - -ec
      - |
        python -m alembic upgrade head
        exec uvicorn app.main:app --host 0.0.0.0 --port 8000
YAML
```

In section 3, **replace** the laptop `cem_compose` function with:

```bash
cem_compose() {
  docker compose -f compose.yaml -f compose.local.yaml -f compose.production.yaml "$@"
}
```

Continue sections 3 and 4 with this function. The local overlay is intentionally
used here to provision PostgreSQL on this single server; the production overlay
replaces its development API command. Do not run multiple API replicas with
startup migrations; use a separate migration job in that case.

Have the server proxy route master traffic to `127.0.0.1:8000`, compute UI traffic
to `127.0.0.1:8080`, and compute API traffic to `127.0.0.1:8002`. Enable HTTPS and
set the compute upload body limit/timeouts for your recording sizes. These
loopback bindings assume the proxy runs on the host; a containerized proxy needs
Docker network routing instead. Verify all three public URLs from another
machine, including an audio upload and publication, before handing over.

For Google Drive features, configure `GOOGLE_CLIENT_ID` and `PICKER_API_KEY` and
the authorized frontend origins in the Google project. FileBrowser is not
started by this guide; enable it separately with credentials/access controls
if download shares are needed.

### Environment reference: configure before deployment

The two authoritative files are `cem-backend/.env` (compute API and compute UI)
and `cem-master-backend/.env` (master API, static UI, database and indexer).
Compose reads these files for interpolation and passes only the variables listed
in each service's `environment` block. Adding an arbitrary variable to `.env`
does not automatically expose it to the application. Shell exports with the
same name override `.env`; unset stale exports when switching environments.

**Deployment order:** generate the initial configuration in section 2, edit the
production values below, then start section 3. Replace example URLs with actual
URLs; do not leave placeholder domains or browser-facing localhost values.

#### Master: `cem-master-backend/.env`

| Variable | Role | What to set before deployment |
|---|---|---|
| `DATABASE_URL` | Database connection for API, Alembic and indexer | Required. `postgresql+psycopg://cem_user:GENERATED_PASSWORD@cem-database:5432/cem_master` for the bundled database; actual reachable DB host for an external database. |
| `POSTGRES_USER` | Creates the bundled PostgreSQL role | `cem_user` for this guide. Used only by the local overlay. |
| `POSTGRES_PASSWORD` | Initial password of that database role | Generated secret matching `DATABASE_URL`. Applies only on first volume initialization. |
| `POSTGRES_DB` | Initial application database | `cem_master` for this guide; init SQL and verification commands assume this name. |
| `POSTGRES_PORT` | Publishes PostgreSQL on the host | `127.0.0.1:5432` with a host proxy; container DB URL still uses port 5432. |
| `CEM_DATA_DIR_HOST` | Host folder mounted at `/data` | Required absolute path to the same data folder compute writes. |
| `MASTER_FRONTEND_CONTEXT` | Host folder mounted at `/frontend` | Required absolute path to `cem-master-frontend`, containing `index.html`. |
| `PORT` | Publishes master API and UI on the host | `127.0.0.1:8000` for a proxy running on this host. |
| `BACKEND_CORS_ORIGINS` | Allowed browser origins, passed as `CORS_ORIGINS` | `https://www.cse.iitd.ernet.in`; both deployed websites share this origin. No path or trailing slash. |
| `BACKEND_API_KEY` | Secret passed as `CEM_MASTER_API_KEY` | Generate and set before exposing protected master mutation endpoints. Keep it out of browser configuration. |
| `API_BASE_URL` | Browser's master API base | `https://www.cse.iitd.ernet.in/act4dws5/bio-master/api` for the current deployed proxy. |
| `COMPUTE_FRONTEND_URL` | Destination of compute links in master | `https://www.cse.iitd.ernet.in/act4dws5/bio/`. |
| `INDEXER_POLL_SECONDS` | Public-project polling interval | `30` is a starting value; adjust for dataset size/load. |
| `FILEBROWSER_PUBLIC_URL` | Visitor-facing download-share URL | Blank when disabled; public HTTPS FileBrowser URL when shares are enabled. Passed by the local overlay, not the base Compose file. |
| `LOG_LEVEL` | Master logging verbosity | `info` normally; supported values are `debug`, `info`, `error`. |
| `DEBUG` | Debug logging alias | `false` in production. |
| `TEST_DATABASE_URL` | Separate database for host-run tests | Not needed for deployment. If testing, use `cem_master_test`, correct password and host port; never the production database. |
| `BACKEND_PORT` | Legacy fallback for `PORT` | Leave unset; set `PORT` explicitly. |
| `DATA_DIR_HOST` | Legacy data-folder fallback in local overlay | Leave unset; use `CEM_DATA_DIR_HOST` consistently in both stacks. |

Compose fixes master `DATA_DIR=/data`, `FRONTEND_DIR=/frontend`, and
`LOG_DIR=/data/logs/cem-master-backend`. These are container paths, not additional
host `.env` values. With Compose, use `BACKEND_CORS_ORIGINS` and `BACKEND_API_KEY`;
setting only `CORS_ORIGINS` or `CEM_MASTER_API_KEY` in `.env` does not replace those
Compose inputs. Direct host Python processes instead use the application names
`CORS_ORIGINS`, `CEM_MASTER_API_KEY`, `DATA_DIR`, `FRONTEND_DIR` and `LOG_DIR`.

#### Compute: `cem-backend/.env`

| Variable | Role | What to set before deployment |
|---|---|---|
| `CEM_DATA_DIR_HOST` | Persistent host data folder mounted at `/data` | Required absolute path, identical to master's data folder. |
| `COMPUTE_FRONTEND_CONTEXT` | Compute frontend build/mount source | Required absolute path to `cem-frontend`. |
| `COMPUTE_BACKEND_PORT` | Compute API host binding | `127.0.0.1:8002` for a host reverse proxy. |
| `COMPUTE_FRONTEND_PORT` | Compute UI host binding | `127.0.0.1:8080` for a host reverse proxy. |
| `SERVER_BASE_URL` | API URL written into browser configuration | Required actual HTTPS compute API URL. Explicitly set it when port values include a bind address. |
| `ALLOWED_ORIGINS` | Browser origins allowed to call compute API | `https://www.cse.iitd.ernet.in`; add other origins only if needed. No URL path. |
| `DEBUG` | Compute debug logging | `false` in production. |
| `MAX_UPLOAD_MB` | Application upload-size limit | Default `2048`; choose for expected uploads and match proxy limits. |
| `BIRDNET_MAX_WORKERS` | BirdNET parallel worker count | Start at `1` on limited RAM, otherwise `2`; each worker loads a model. |
| `INDICES_MAX_WORKERS` | Acoustic-index worker count | Blank for automatic selection; use a small explicit count if RAM is limited. |
| `HOST_LOG_DIR` | Host folder mounted at `/logs` | Defaults to `./logs`; choose an absolute writable persistent log path if needed. |
| `LOG_DIR` | Compute log path inside container | Keep `/logs` to match its mount. |
| `DATA_DIR` | Compute data path inside container | Keep `/data` to match the shared mount. |
| `HOST_DATA_DIR` | Legacy fallback for the host data folder | Leave at default/unset; explicit `CEM_DATA_DIR_HOST` takes precedence. |
| `RETENTION_HOURS` | Automatic deletion age for job directories | `0` disables deletion; otherwise choose a deliberate retention period (default `168`). |
| `RETENTION_SWEEP_MINUTES` | Cleanup scan interval | Default `60`; relevant when retention is enabled. |
| `API_VERSION` | Version recorded in outputs | Keep release value `1.1.0` unless releasing a changed API. |
| `STAC_ENABLED` | Generate STAC provenance sidecars | Default `true`. |
| `STAC_COLLECTION` | Collection identifier in sidecars | Default `cem-bioacoustics`; change only for your collection policy. |
| `STAC_ASSET_BASE_URL` | Base URL for absolute STAC asset links | Blank for relative links; otherwise the actual public asset URL. |

#### Optional compute integrations

These do not block the basic server-upload → BirdNET → Make Public flow.
Configure each group only when enabling its integration.

| Variable | Role | Value / requirement |
|---|---|---|
| `GOOGLE_CLIENT_ID` | Browser Google OAuth client | Blank to disable Drive features; otherwise actual web client ID with authorized compute UI origins. |
| `PICKER_API_KEY` | Google Drive Picker API key | Blank when unused; otherwise key configured for the Picker integration and intended browser origins. |
| `FILEBROWSER_BASE_URL` | Compute's internal share-creation endpoint | Blank disables shares; `http://filebrowser:80` when that service is enabled on the compute network. |
| `FILEBROWSER_USERNAME` | FileBrowser account used to create shares | Actual configured account (default account name `admin`). |
| `FILEBROWSER_PASSWORD` | Password for that account | Actual FileBrowser password; do not assume it is `admin`. A blank `.env` value falls back to `admin` in current Compose. |
| `FILEBROWSER_TIMEOUT` | Share-creation request timeout | Default `10` seconds. |
| `AIRFLOW_BASE_URL` | Internal Airflow API address | Blank runs compute locally; otherwise reachable internal scheduler URL. |
| `AIRFLOW_USERNAME` | Airflow API account | Actual account when Airflow is enabled; replace default `admin`. |
| `AIRFLOW_PASSWORD` | Airflow API password | Actual secret when enabled; replace default `admin`. |
| `AIRFLOW_DAG_ID` | Analysis DAG identifier | Default `cem_pipeline`; must match installed DAG. |
| `AIRFLOW_TIMEOUT` | Airflow request timeout | Default `10` seconds. |
| `AIRFLOW_TRIGGER_URL` | Optional browser-facing Airflow trigger configuration | Blank unless your frontend integration uses it; distinct from internal `AIRFLOW_BASE_URL`. |
| `GEE_PROJECT` | Earth Engine cloud project | Your authorized project when using Earth Engine; replace example `ee-geeapi`. |
| `GEE_SERVICE_ACCOUNT` | Earth Engine service-account identity | Actual account email for service-account authentication; blank for personal credentials. |
| `GEE_SERVICE_ACCOUNT_KEY` | Service-account JSON path inside container | Path to a separately mounted key; setting a host file path alone does not mount it. |
| `EARTHENGINE_CREDENTIALS` | Host personal-credentials directory mounted read-only | Defaults to `~/.config/earthengine`; set the actual directory when using personal authentication. |

FileBrowser must be started separately (`docker compose up -d filebrowser` from
compute) when enabled. Its current Compose file publishes port 8097 on all
interfaces; configure its binding/access controls before starting it publicly.
Set master `FILEBROWSER_PUBLIC_URL` too if visitors should receive download
links. Existing analyses without shares may need to be rerun.

The compute frontend generator also recognizes `ANALYSIS_REPO_URL` and
`CORS_PROXY_URL`, but current Compose does not pass them through. Likewise,
application-only compute settings such as `MAX_CONCURRENT_RUNS`, `PIPELINE_DIR`,
`PYTHON_BIN`, `STACD_WORKSPACE_ID`, `STACD_STAC_VERSION`, `STACD_ASSET_ID_PREFIX`,
`GEE_DEFAULT_YEAR`, `GEE_DEFAULT_SCALE`, `GEE_DEFAULT_NUM_PIXELS`, and
`GEE_MAX_CLUSTERS` are not inputs in the current Compose file. Changing them
requires an explicit service `environment` override; adding them only to `.env`
has no effect. They are not required for this guide's basic deployment.

The master frontend's `.env.example` contains legacy `FRONTEND_PORT`; it is not
used by this unified master deployment. Compute frontend configuration comes
from compute's `.env` and is generated on frontend container startup.

After edits, validate without printing secrets, then recreate affected services:

```bash
cd "$CEM_WORKSPACE/cem-backend"
docker compose config --quiet
docker compose up -d api frontend
cd "$CEM_WORKSPACE/cem-master-backend"
# Define the production cem_compose function above in this terminal first.
cem_compose config --quiet
cem_compose up -d backend indexer
```

On the initial deployment, follow the build/readiness/migration sequence in
section 3 instead of this short recreation sequence. Restart alone does not
apply changed container environment. Keep `.env` files private; the OAuth client
ID and Picker browser key are intentionally browser-visible, database passwords
and backend API secrets are not.

### Existing cluster or externally managed PostgreSQL

Use `compose.yaml` without `compose.local.yaml` only when the database is already
provisioned and reachable from both master services. Set `DATABASE_URL` to its
actual hostname and credentials; join/create `cem_master_network` as appropriate.
Provide the shared data and frontend mounts, and remove `--reload` through a
command overlay. Before starting API/indexer (or as a deployment migration job):

```bash
docker compose -f compose.yaml build backend indexer
docker compose -f compose.yaml run --rm --no-deps backend python -m alembic upgrade head
docker compose -f compose.yaml run --rm --no-deps backend python -m alembic current
```

Use your deployment's production command overlay when starting services. The
base file provides no database container and no automatic migrations.

## 6. If running the master backend without Docker

This is an alternative to the container API/indexer, not an additional service.
Use Python 3.12 (the Docker image's version) and an existing PostgreSQL database.
From `cem-master-backend`, with the container API/indexer stopped:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip check
export DATABASE_URL='postgresql+psycopg://cem_user:YOUR_PASSWORD@127.0.0.1:5432/cem_master'
export DATA_DIR="$CEM_WORKSPACE/cem-backend/data"
export FRONTEND_DIR="$CEM_WORKSPACE/cem-master-frontend"
python -m alembic upgrade head
python -m alembic current
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Replace `YOUR_PASSWORD` with the configured password. `.env` is read by Compose;
it is **not automatically loaded by these Python commands**. Host processes use
`127.0.0.1` for the published database; containers use `cem-database`.
In another terminal, activate the same virtualenv, export the same `DATABASE_URL`
and `DATA_DIR`, then run:

```bash
python -m app.indexer --data-dir "$DATA_DIR" --all --watch
```

Tests additionally require `requirements-dev.txt` and a separate test database;
they are not a production startup step. Compute's Python and native dependencies
are separate: use its Dockerfile for the supported compute installation.

## 7. Maintenance and troubleshooting

In a new terminal, set `CEM_WORKSPACE`, change into `cem-master-backend`, and
define the appropriate `cem_compose` function again.

```bash
cem_compose logs --tail=100 backend indexer cem-database
cem_compose exec -T backend python -m alembic current
cem_compose stop backend indexer
# After updating source/requirements, build and migrate before restarting:
cem_compose build backend indexer
cem_compose run --rm --no-deps backend python -m alembic upgrade head
cem_compose up -d backend indexer
# Stop the entire master stack, retaining the database:
cem_compose down
```

Back up the database and shared compute data before updating a production
installation. Example database backup (while PostgreSQL is running):

```bash
cem_compose exec -T cem-database pg_dump -U cem_user -d cem_master > cem_master_backup.sql
```

Store backups outside the server too. Do not use `down -v` as a troubleshooting
step: it deletes the database volume.

| Symptom | Check / fix |
|---|---|
| `alembic: command not found` | Rebuild the backend image; or activate the host virtualenv and install `requirements.txt`. Use `python -m alembic`. |
| Required `DATABASE_URL` missing | Create/configure master `.env` before any Compose command. |
| Database connection refused | Confirm PostgreSQL is ready and the URL uses the correct hostname and credentials. |
| Password authentication failed | `.env` and stored PostgreSQL credentials differ; restore the correct credentials or change the database role password deliberately. |
| Missing tables | Run `upgrade head`, then check `current` against `heads`. `/health` alone does not verify the schema. |
| Can't locate migration revision | Check the source/migration version against the database; restore matching files and investigate before changing schema state. |
| Permission denied writing logs | Both master services run as user `cem`; the shared `data/logs/cem-master-backend` directory must be writable by that container UID/GID. Inspect with `cem_compose run --rm --no-deps backend id` and have the administrator grant access to that log directory. |
| No public projects | Confirm both backends mount the same host folder and `project.json` is public. |
| Empty map after publication | Check server BirdNET outputs, analysis dates, spot coordinates and indexer logs. |
| Browser calls localhost in production | Fix compute `SERVER_BASE_URL` or master `COMPUTE_FRONTEND_URL`, then recreate the affected service with `up -d`. |

### Recording cards appear but audio does not play

The live deployment was checked on 6 October 2026. Its configuration uses
`API_BASE_URL=https://www.cse.iitd.ernet.in/act4dws5/bio-master/api`.

Two separate failures were observed for recording
`04213SPOT1_20260131_082409.wav`:

1. The old frontend `apiUrl()` resolves `/api/v1/recordings/.../stream` against
   the domain root, discarding the deployment prefix. Deploy the corrected
   `cem-master-frontend/js/main.js` which preserves the configured API base.
   This also fixes the same URL construction for bird snippets.
2. The correctly prefixed stream endpoint returns `404` with
   `{"detail":"Audio file not found"}`. Metadata is indexed, but the backend
   cannot find the WAV under its configured data root. Check the backend's
   mount separately from the indexer's mount; both must see the original WAV.

From the master backend directory, with the appropriate `cem_compose` function:

```bash
cem_compose exec -T backend find /data/projects -type f -name '04213SPOT1_20260131_082409.wav'
cem_compose exec -T indexer find /data/projects -type f -name '04213SPOT1_20260131_082409.wav'
curl --fail --range 0-31 -o /dev/null -D - \
  https://www.cse.iitd.ernet.in/act4dws5/bio-master/api/api/v1/recordings/aud_168a488f0c9abe602f6d8eb4/stream
```

The backend searches the database's relative audio path and the project's
`<spot>/audio/<filename>` folders. If the WAV is absent, restore/upload it into
the correct compute project/spot data folder shared with master. If the file is
present elsewhere, correct the shared mount or project layout. Recreate services
after mount changes and reindex if metadata paths changed. A successful stream
should return WAV bytes with an audio content type, not JSON or an HTML page.
