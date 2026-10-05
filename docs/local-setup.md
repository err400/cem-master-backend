# Local setup: start here

For a fresh local installation, use Docker Desktop (running) or Docker Engine
with Compose v2, Git, Python 3 and Bash. On Windows use WSL with Docker
integration. These commands use a new `cem-master` folder in your current
directory; choose a different location if that folder already exists.

## 1. Clone the repositories

```bash
mkdir cem-master
cd cem-master
export CEM_WORKSPACE="$PWD"
git clone https://github.com/err400/cem-backend.git cem-backend
git clone https://github.com/err400/cem-frontend.git cem-frontend
git clone https://github.com/err400/cem-master-backend.git cem-master-backend
git clone https://github.com/err400/cem-master-frontend.git cem-master-frontend
docker info
docker compose version
```

All four repositories must be siblings. For existing checkouts, skip cloning,
set `CEM_WORKSPACE` to their parent folder, and retain existing credentials.

## 2. Configure once

For a fresh database, create the private configuration files:

```bash
cd "$CEM_WORKSPACE/cem-backend"
test -f .env || cp .env.example .env
mkdir -p data/projects logs
cd "$CEM_WORKSPACE/cem-master-backend"
test -f .env || cp .env.example .env
```

Run this block once to set shared-data paths, generate matching private database
credentials, and set local browser URLs. Do not run it against an existing
configured PostgreSQL volume; retain that database's credentials.

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

**No production configuration is needed for this local setup.**

Local URL settings are:

| File | Setting | Local value |
|---|---|---|
| compute `.env` | `SERVER_BASE_URL` | `http://localhost:8002` |
| compute `.env` | `ALLOWED_ORIGINS` | `http://localhost:8080,http://127.0.0.1:8080` |
| master `.env` | `API_BASE_URL` | Blank (same-origin API on port 8000) |
| master `.env` | `COMPUTE_FRONTEND_URL` | `http://localhost:8080/` |
| master `.env` | `BACKEND_CORS_ORIGINS` | `http://localhost:8000,http://127.0.0.1:8000` |

Do not put the deployed IITD URL/prefix into a local environment. Both data
mounts must name the same compute data folder.

## 3. Build, migrate and start

Run in order and stop on any failed command:

```bash
cd "$CEM_WORKSPACE/cem-backend"
docker compose config --quiet
docker compose up --build -d api frontend

cd "$CEM_WORKSPACE/cem-master-backend"
docker network inspect cem_master_network >/dev/null 2>&1 || docker network create cem_master_network
cem_compose() { docker compose -f compose.yaml -f compose.local.yaml "$@"; }
cem_compose config --quiet
cem_compose build backend indexer
cem_compose run --rm --no-deps --user root backend sh -ec 'mkdir -p /data/logs/cem-master-backend; chown cem:cem /data/logs/cem-master-backend'
cem_compose up -d cem-database
```

Check readiness; repeat until PostgreSQL reports `accepting connections`:

```bash
cem_compose exec -T cem-database pg_isready -U cem_user -d cem_master
```

Then apply the existing migrations before starting the indexer:

```bash
cem_compose run --rm --no-deps backend python -m alembic upgrade head
cem_compose up -d backend indexer
cem_compose ps
```

Docker installs Python dependencies, including Alembic. No host pip installation
or new migration generation is required.

## 4. Open and verify

- [Compute website](http://localhost:8080)
- [Compute API docs](http://localhost:8002/docs)
- [Master website](http://localhost:8000)
- [Master API docs](http://localhost:8000/docs)

```bash
curl --fail http://localhost:8002/health
curl --fail http://localhost:8000/health
curl --fail http://localhost:8000/api/v1/spots
cem_compose exec -T backend python -m alembic current
```

An empty master map is normal before publication. The master backend serves the
frontend; no separate master frontend container is needed.

Use [HOW_TO_TEST.md](../HOW_TO_TEST.md) to upload audio, run server BirdNET and
publish. See [publication troubleshooting](first-time-local-publication.md) if
data is missing. Use [CEM_SETUP_GUIDE.md](../CEM_SETUP_GUIDE.md) for the full
production environment reference and server-specific proxy configuration.

## Later starts and logs

In a new terminal, set `CEM_WORKSPACE` to the cloned parent folder again:

```bash
cd "$CEM_WORKSPACE/cem-backend"
docker compose up -d api frontend
cd "$CEM_WORKSPACE/cem-master-backend"
cem_compose() { docker compose -f compose.yaml -f compose.local.yaml "$@"; }
cem_compose up -d
cem_compose logs --tail=100 backend indexer
```

For source/dependency updates, use the build and migration sequence in the full
guide. Stop with `docker compose down` in compute and `cem_compose down` in
master; omit `-v` to retain the database.
