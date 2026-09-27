# CEM Setup & Deployment Guide

> **Who is this for?**
> Anyone setting up the CEM system — whether on a **personal laptop** for development/testing, or on a **Linux server** for production deployment.

## How to Use This Guide

Parts 1–4 are identical for both scenarios. Part 5 covers what changes for a production server deployment.

| I am… | Follow… |
|-------|---------|
| A developer running this on my own machine | Parts 1 → 4, then **Part 5 is optional** |
| Deploying to a Linux server / VM for production | Parts 1 → 4 *(same steps, different machine)*, then **Part 5 is required** |

---

## What You're Setting Up

The CEM system is made of **two independent stacks** that work together:

| Stack | What it does | Default local URL |
|-------|--------------|-------------------|
| **Compute** (`cem-compute`) | Field researchers upload audio, run BirdNET analysis, and publish projects | `http://localhost:8080` |
| **Main Website** (`main-website`) | Public-facing map and biodiversity dashboard that indexes and displays published data | `http://localhost:8000` |

**Data flows one way:** Compute → (Make Public) → Main Website indexes and displays it.

---

## Expected Folder Layout

Clone / unzip both repos so they sit **side by side** in the same parent folder. The compose files rely on relative sibling paths.

```
your-workspace/
├── cem-compute/
│   ├── cem-backend/        <- compute API + pipeline
│   └── cem-frontend/       <- compute UI (Nginx)
└── main-website/
    ├── cem-master-backend/ <- master API + indexer (start from here)
    └── cem-master-frontend/<- public map UI (served by backend container)
```

> [!IMPORTANT]
> If the two repos are NOT siblings, override `COMPUTE_FRONTEND_CONTEXT` (in `cem-compute/cem-backend/.env`) and `MASTER_FRONTEND_CONTEXT` (in `main-website/cem-master-backend/.env`).

---

## Prerequisites

### Local Development (your laptop)

| Tool | Minimum Version | Install Link | Notes |
|------|----------------|-------------|-------|
| **Docker Desktop** | Latest stable | https://www.docker.com/products/docker-desktop | Must be running before any `docker compose` command |
| **Git** | Any | https://git-scm.com | For cloning repos |
| **Python 3.10+** | 3.10+ | https://www.python.org | Only needed for tests or the local watcher |
| **A modern browser** | Chrome / Edge | — | For Google OAuth popup support |
| **A Google account** | — | — | Needed for Sign-In on the compute frontend |

### Server / Production

| Tool | Install | Notes |
|------|---------|-------|
| **Docker Engine + Compose plugin** | `curl -fsSL https://get.docker.com | sh` | Use Docker Engine on Linux, **not** Docker Desktop |
| **Git** | `apt install git` | For cloning repos |
| **Nginx** *(optional)* | `apt install nginx` | Recommended reverse proxy for HTTPS + custom domain |
| **A domain name** *(optional)* | DNS A-record → server IP | Required for HTTPS via Let's Encrypt |
| **Certbot** *(optional)* | https://certbot.eff.org | For free TLS certificates |

### Verify Docker is working

```bash
# Linux server:
sudo docker version
sudo docker compose version

# Windows / Docker Desktop:
docker version
docker info
```

---

## Part 1 — Compute Stack (`cem-compute`)

The compute stack is where audio is uploaded, BirdNET runs, and projects are published. **Start here first**, because the main website reads data from it.

### Step 1.1 — Create the `.env` file

```powershell
cd cem-compute\cem-backend
Copy-Item .env.example .env
```

Open `.env` in a text editor. Set these variables:

| Variable | Default | What to do |
|----------|---------|-----------|
| `CEM_DATA_DIR_HOST` | `./data` | Where audio uploads and job results are stored. The default works locally. |
| `COMPUTE_BACKEND_PORT` | `8002` | Port for the compute API. Change only if 8002 is already in use. |
| `COMPUTE_FRONTEND_PORT` | `8080` | Port for the compute UI. Change only if 8080 is already in use. |
| `COMPUTE_FRONTEND_CONTEXT` | `../cem-frontend` | Path to the compute frontend repo. Leave as-is if using the sibling layout. |
| `SERVER_BASE_URL` | `http://localhost:8002` | The URL the **browser** uses to talk to the API. Must match `COMPUTE_BACKEND_PORT`. |
| `GOOGLE_CLIENT_ID` | *(blank)* | Optional. Blank disables Google Drive features; server-compute mode still works. |
| `PICKER_API_KEY` | *(blank)* | Optional. Only needed for Google Drive integration. |
| `BIRDNET_MAX_WORKERS` | `2` | Lower to `1` if you get `BrokenProcessPool` errors (low RAM machine). |
| `ALLOWED_ORIGINS` | `*` | Leave as `*` for local dev. In production, set to exact frontend URL. |
| `FILEBROWSER_BASE_URL` | *(blank)* | Optional. Enables download links on the main website. See FileBrowser section below. |
| `DEBUG` | `false` | Set `true` for verbose logging. |

> [!NOTE]
> Everything else (Airflow, GEE, STAC, FileBrowser) can be left at defaults for a basic local setup. Airflow and GEE are optional cluster/cloud features.

### Step 1.2 — Create the data and logs directories

The backend writes audio files and job results into `data/`. Create them if they don't exist:

```powershell
New-Item -ItemType Directory -Force -Path ".\data"
New-Item -ItemType Directory -Force -Path ".\data\projects"
New-Item -ItemType Directory -Force -Path ".\logs"
```

### Step 1.3 — Build and start the compute stack

From `cem-compute/cem-backend/`:

```powershell
docker compose up --build -d
```

This starts three services:
- **`api`** — FastAPI compute backend on `http://localhost:8002`
- **`frontend`** — Nginx serving the compute UI on `http://localhost:8080`
- **`filebrowser`** — FileBrowser UI on `http://localhost:8097` *(optional — only needed if you want download links on the main website)*

> [!NOTE]
> FileBrowser password setup is **not required** for a basic local setup. `FILEBROWSER_BASE_URL` is blank by default, which disables the feature entirely. The API and UI work fine without it.

### Step 1.4 — Verify the compute stack is running

```powershell
docker compose ps
docker compose logs --tail 30 api
```

Open in browser:
- **Compute UI:** http://localhost:8080
- **Compute API health:** http://localhost:8002/health

### Step 1.5 — Understanding `docker-compose.yml` (Compute)

You don't edit `docker-compose.yml` directly — all its tuneable values come from your `.env` file. Here's what each service does and which `.env` variables control it:

| Service | Image | Host Port (`.env` var) | What it does |
|---------|-------|------------------------|--------------|
| `api` | `hridayansh/cem-backend` | `COMPUTE_BACKEND_PORT` (default `8002`) | FastAPI backend — handles uploads, triggers BirdNET pipeline, stores results in `DATA_DIR` |
| `frontend` | `cem-frontend` (built from `cem-frontend/`) | `COMPUTE_FRONTEND_PORT` (default `8080`) | Nginx serving the compute web UI. Reads `SERVER_BASE_URL`, `GOOGLE_CLIENT_ID`, `PICKER_API_KEY` from `.env` to generate `js/core/Config.js` at container startup |
| `filebrowser` | `filebrowser/filebrowser` | `8097` (fixed) | Optional. Serves `DATA_DIR` as a downloadable file browser |

Key volume mounts set by `.env`:

| `.env` Variable | Mounted into container as | Purpose |
|-----------------|--------------------------|--------|
| `CEM_DATA_DIR_HOST` | `/data` | Shared project data (audio uploads, job results) |
| `COMPUTE_FRONTEND_CONTEXT` | Build context for `frontend` service | Where to find `cem-frontend/` source |

---

## Part 2 — Main Website (`main-website`)

The main website reads **public** project data from the compute stack's `data/` folder. It has its own PostgreSQL database and a background indexer.

### Step 2.1 — Create the shared Docker network

This must exist before the main website starts:

```powershell
# Check if it exists first
docker network inspect cem_master_network 2>$null

# If the above showed an error, create it:
docker network create cem_master_network
```

Or in one PowerShell block:

```powershell
$null = docker network inspect cem_master_network 2>&1
if ($LASTEXITCODE -ne 0) {
    docker network create cem_master_network
}
```

### Step 2.2 — Create the `.env` file

```powershell
cd main-website\cem-master-backend
Copy-Item .env.example .env
```

Open `.env` and configure these variables:

| Variable | Default | What to do |
|----------|---------|-----------|
| `CEM_DATA_DIR_HOST` | `../cem-backend/data` | **Critical.** Path to `cem-compute/cem-backend/data`. This is how the main website reads compute outputs. Use forward slashes on Windows with Docker. |
| `MASTER_FRONTEND_CONTEXT` | `../cem-master-frontend` | Path to `main-website/cem-master-frontend`. Leave as-is with sibling layout. |
| `PORT` | `8000` | Host port for the main website. Change if 8000 is in use. |
| `DATABASE_URL` | `postgresql+psycopg://cem_user:change-me@cem-database:5432/cem_master` | Container-internal DB URL. **Do not change** the hostname (`cem-database`) — it's the compose service name. |
| `CORS_ORIGINS` | `http://localhost:8000,http://127.0.0.1:8000` | Leave as-is for local dev. |
| `COMPUTE_FRONTEND_URL` | `http://127.0.0.1:8080/` | URL for the "Do Your Own CEM" button. Should point to the compute UI. |
| `FILEBROWSER_PUBLIC_URL` | `http://localhost:8097` | URL visitors use to download analysis outputs. Leave blank for private setups. |
| `INDEXER_POLL_SECONDS` | `30` | How often the indexer checks for new/changed projects. |
| `LOG_LEVEL` | `info` | `debug` for verbose logs, `info` for normal, `error` for failures only. |
| `CEM_MASTER_API_KEY` | *(blank)* | Optional API key for admin spot mutations. Leave blank for local dev. |

> [!IMPORTANT]
> **The most important variable is `CEM_DATA_DIR_HOST`.**
>
> If your folder layout is exactly the sibling layout shown above, the default `../cem-backend/data` resolves correctly from within the backend container. If you placed things differently, set an absolute path:
> ```dotenv
> CEM_DATA_DIR_HOST=C:/your-workspace/cem-compute/cem-backend/data
> ```
> Always use forward slashes on Windows when setting paths for Docker.

### Step 2.3 — Understanding `compose.yaml` + `compose.local.yaml` (Main Website)

The main website uses **two compose files layered together** — you always pass both with `-f`:

| File | Purpose |
|------|---------|
| `compose.yaml` | Production definition. Assumes an external PostgreSQL at hostname `cem-database` on `cem_master_network`. No database container included. |
| `compose.local.yaml` | Local development overlay. Adds the `cem-database` PostgreSQL container and fills in missing defaults so the stack can start on a laptop. |

Services and what controls them:

| Service | Host Port (`.env` var) | What it does |
|---------|-----------------------|--------------|
| `cem-database` | `5432` (fixed locally) | PostgreSQL. Added by `compose.local.yaml`. Stores the CEM catalogue. |
| `backend` | `PORT` (default `8000`) | FastAPI — serves the map UI on `/` and REST API on `/api/v1/`. Runs `alembic upgrade head` automatically on startup. |
| `indexer` | *(no port)* | Background process. Polls `DATA_DIR/projects/` every `INDEXER_POLL_SECONDS` seconds and syncs public projects into the database. |

Key volume mounts set by `.env`:

| `.env` Variable | Mounted into container as | Purpose |
|-----------------|--------------------------|--------|
| `CEM_DATA_DIR_HOST` | `/data` (read-only) | Compute project outputs — the indexer reads from here |
| `MASTER_FRONTEND_CONTEXT` | `/frontend` (read-only) | Frontend HTML/JS/CSS — served directly by FastAPI on `/` |

### Step 2.4 — Build and start the main website stack

From `main-website/cem-master-backend/`:

```powershell
docker compose -f compose.yaml -f compose.local.yaml up --build -d
```

This starts:
- **`cem-database`** — PostgreSQL on port `5432`
- **`backend`** — FastAPI (automatically runs Alembic migrations on startup, then serves on port `8000`)
- **`indexer`** — Background indexer, watches `data/projects/` every 30s

> [!NOTE]
> The backend automatically runs `alembic upgrade head` on startup to create/migrate the database schema. You do **not** need to run migrations manually.

### Step 2.5 — Verify the main website is running

```powershell
docker compose -f compose.yaml -f compose.local.yaml ps
docker compose -f compose.yaml -f compose.local.yaml logs --tail 30 backend
```

Open in browser:
- **Main website:** http://localhost:8000
- **API docs (Swagger):** http://localhost:8000/docs
- **Health check:** http://localhost:8000/health

---

## Part 3 — Load Test Data (Optional)

If you don't have real audio data yet, you can populate the main website with synthetic fixture data for testing.

### Option A — Use the test fixture generator

From `main-website/cem-master-backend/`:

```powershell
# Generate a synthetic DATA_DIR inside the compute data folder
python tests/fixtures/build_fixture.py --out "C:/your-workspace/cem-compute/cem-backend/data"
```

Then trigger the indexer to pick it up:

```powershell
docker compose -f compose.yaml -f compose.local.yaml exec backend python -m app.indexer --data-dir /data --all
```

### Option B — Seed sample spots

```powershell
docker compose -f compose.yaml -f compose.local.yaml exec backend python scripts/seed_spots.py
```

### Option C — Dry-run the indexer (no writes)

See what would be indexed without committing anything:

```powershell
docker compose -f compose.yaml -f compose.local.yaml exec backend python -m app.indexer --data-dir /data --all --dry-run
```

---

## Part 4 — Full End-to-End Test Flow

Once both stacks are running, follow this workflow to verify everything works together:

1. **Open compute UI** → http://localhost:8080
2. **Sign in with Google** — click "Sign in with Google" in the left sidebar
3. **Initialize Storage** — select a local folder when prompted (browser uses the Native File System API; falls back to IndexedDB automatically)
4. **Create a Project** → give it any name
5. **Add a Spot** → enter a name + coordinates (uncheck "Use current location" to type manually)
6. **Import Media** → upload `.wav` files; they **must** be named:

   ```
   SPOTNAME_YYYYMMDD_HHMMSS.wav
   ```

   Examples:
   | Filename | Spot | Date | Time |
   |----------|------|------|------|
   | `RIVERBANK_20260101_183000.wav` | RIVERBANK | 2026-01-01 | 18:30:00 |
   | `SPOT1_20251215_060000.wav` | SPOT1 | 2025-12-15 | 06:00:00 |

   > [!WARNING]
   > Files that don't match this naming convention are **silently ignored** — BirdNET will appear to find nothing, but it's actually never seeing your files.

7. **Run Analysis** → click "Analysis" → select **"BirdNET Species Detection"** → select your spot → click **"Queue Job"**
8. **Monitor Jobs** → click "Jobs" → wait for status "completed"
9. **Make Public** → in the Project section, toggle **"Make Public"**
10. **Check main website** → http://localhost:8000 — your spot should appear on the map within ~30 seconds (one indexer poll cycle)

---

## Common Commands Reference

### Compute Stack (`cem-compute/cem-backend/`)

```powershell
# Start (first time, or after changing Dockerfile)
docker compose up --build -d

# Start without rebuilding
docker compose up -d

# View logs
docker compose logs -f api
docker compose logs -f frontend

# Stop (keeps data in ./data)
docker compose down

# Stop and delete all volumes (clears FileBrowser DB)
docker compose down -v

# Check service status
docker compose ps
```

### Main Website (`main-website/cem-master-backend/`)

```powershell
# Start
docker compose -f compose.yaml -f compose.local.yaml up --build -d

# Start without rebuilding
docker compose -f compose.yaml -f compose.local.yaml up -d

# View logs
docker compose -f compose.yaml -f compose.local.yaml logs -f backend
docker compose -f compose.yaml -f compose.local.yaml logs -f indexer

# Stop (keeps database data)
docker compose -f compose.yaml -f compose.local.yaml down

# DESTRUCTIVE: stop and delete the entire database volume
docker compose -f compose.yaml -f compose.local.yaml down -v

# Rebuild only
docker compose -f compose.yaml -f compose.local.yaml up --build -d

# Restart a single service (e.g. after editing Python code)
docker compose -f compose.yaml -f compose.local.yaml restart backend

# Run indexer manually — re-index all public projects
docker compose -f compose.yaml -f compose.local.yaml exec backend python -m app.indexer --data-dir /data --all

# Dry-run: report what would be indexed without writing
docker compose -f compose.yaml -f compose.local.yaml exec backend python -m app.indexer --data-dir /data --all --dry-run

# Re-index a single project
docker compose -f compose.yaml -f compose.local.yaml exec backend python -m app.indexer --data-dir /data --project <project_name>
```

### Database & Migrations (Main Website)

```powershell
# Apply pending Alembic migrations manually (normally done automatically on startup)
docker compose -f compose.yaml -f compose.local.yaml exec backend alembic upgrade head

# Create a new migration after editing models
docker compose -f compose.yaml -f compose.local.yaml exec backend alembic revision --autogenerate -m "description"

# Run tests in the container
docker compose -f compose.yaml -f compose.local.yaml exec backend python -m pytest

# Run tests on the host machine (requires TEST_DATABASE_URL set in .env)
python -m pytest
```

---

## Part 5 — Production Deployment

> [!NOTE]
> Skip this section if you are only running the system locally on your own machine. Parts 1–4 are sufficient for local dev.

Production deployment follows the **exact same Parts 1–4 steps** on a Linux server, with the additional changes described below.

### 5.1 — Use Docker Engine, not Docker Desktop

On a Linux server, install Docker Engine (no GUI needed):

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # allow running docker without sudo (re-login after)
newgrp docker                   # apply group change in current shell
docker compose version          # verify compose plugin is installed
```

### 5.2 — Harden the `.env` Files

The defaults in `.env.example` are safe for local dev but **must be changed** before exposing either stack to the internet.

#### `cem-compute/cem-backend/.env` — production changes

| Variable | Local default | Production value |
|----------|--------------|-----------------|
| `ALLOWED_ORIGINS` | `*` | Set to exact frontend URL, e.g. `https://compute.yourdomain.com` |
| `DEBUG` | `false` | Leave `false` |
| `CEM_DATA_DIR_HOST` | `./data` | Absolute path to a persistent volume, e.g. `/opt/cem/data` |
| `SERVER_BASE_URL` | `http://localhost:8002` | Public-facing API URL, e.g. `https://api.compute.yourdomain.com` or `https://compute.yourdomain.com/api` |
| `GOOGLE_CLIENT_ID` | *(blank)* | Set your OAuth Client ID from Google Cloud Console — required for researcher sign-in |
| `PICKER_API_KEY` | *(blank)* | Set your Google Picker API key if using Drive integration |

#### `main-website/cem-master-backend/.env` — production changes

| Variable | Local default | Production value |
|----------|--------------|-----------------|
| `CEM_DATA_DIR_HOST` | `../cem-backend/data` | Same absolute path as compute, e.g. `/opt/cem/data` |
| `CORS_ORIGINS` | `http://localhost:8000,...` | Your public domain, e.g. `https://map.yourdomain.com` |
| `FILEBROWSER_PUBLIC_URL` | `http://localhost:8097` | Public FileBrowser URL if enabled, e.g. `https://files.yourdomain.com`. Leave blank if not exposing FileBrowser publicly. |
| `LOG_LEVEL` | `info` | `info` or `error` in production |

> [!CAUTION]
> Never expose the raw Docker ports (`8002`, `8080`, `8000`, `8097`) directly to the internet. Put Nginx in front and let it handle TLS. The `8097` FileBrowser port in particular ships with default credentials and must not be publicly reachable as-is.

### 5.3 — Use a Persistent Data Directory

On a server, don't store data inside the repo folder. Use an absolute path on a volume that survives re-deployments:

```bash
sudo mkdir -p /opt/cem/data/projects
sudo mkdir -p /opt/cem/data/logs/cem-master-backend
sudo chown -R $USER:$USER /opt/cem
```

Then in both `.env` files:
```dotenv
CEM_DATA_DIR_HOST=/opt/cem/data
```

### 5.4 — Set Docker to Auto-Restart on Boot

Both stacks already have `restart: unless-stopped` in their compose files, which means containers restart automatically after a reboot — but only if you started them with `docker compose up -d` at least once.

To make Docker itself start on boot:

```bash
sudo systemctl enable docker
sudo systemctl start docker
```

After a server reboot, the containers will come back up automatically.

### 5.5 — Nginx Reverse Proxy (Recommended)

Running Nginx in front of the Docker containers lets you:
- Serve everything on port 80/443 (standard HTTP/HTTPS)
- Terminate TLS in one place
- Use one domain with path-based routing, or separate subdomains

#### Example: subdomain-based routing

```
https://compute.yourdomain.com   →  Docker port 8080 (compute frontend)
https://map.yourdomain.com       →  Docker port 8000 (main website)
```

**Install Nginx:**
```bash
sudo apt install nginx
```

**`/etc/nginx/sites-available/cem-compute`:**
```nginx
server {
    listen 80;
    server_name compute.yourdomain.com;

    location / {
        proxy_pass         http://127.0.0.1:8080;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;

        # Large uploads (audio files)
        client_max_body_size 2100M;
        proxy_read_timeout   600s;
        proxy_send_timeout   600s;
    }
}
```

**`/etc/nginx/sites-available/cem-main`:**
```nginx
server {
    listen 80;
    server_name map.yourdomain.com;

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }
}
```

**Enable and reload:**
```bash
sudo ln -s /etc/nginx/sites-available/cem-compute /etc/nginx/sites-enabled/
sudo ln -s /etc/nginx/sites-available/cem-main    /etc/nginx/sites-enabled/
sudo nginx -t          # test config
sudo systemctl reload nginx
```

### 5.6 — Enable HTTPS with Let's Encrypt (Certbot)

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d compute.yourdomain.com -d map.yourdomain.com
```

Certbot will automatically edit your Nginx configs to add TLS and set up auto-renewal.

After enabling HTTPS, update your `.env` files:
- `SERVER_BASE_URL=https://compute.yourdomain.com` (in compute `.env`)
- `CORS_ORIGINS=https://map.yourdomain.com` (in main website `.env`)
- `COMPUTE_FRONTEND_URL=https://compute.yourdomain.com/` (in main website `.env`)

Then rebuild the frontend container so `Config.js` is regenerated with the new URL:
```bash
cd cem-compute/cem-backend
docker compose up --build -d frontend
```

### 5.7 — Google OAuth Setup (Required for Researcher Sign-In)

The compute frontend uses Google OAuth for researcher authentication. To enable it on a public URL:

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → **APIs & Services** → **Credentials**
2. Create an **OAuth 2.0 Client ID** (Web application type)
3. Add your domain to **Authorized JavaScript origins**: `https://compute.yourdomain.com`
4. Copy the **Client ID** and set it in `cem-compute/cem-backend/.env`:
   ```dotenv
   GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
   ```
5. Rebuild the frontend container: `docker compose up --build -d frontend`

> [!NOTE]
> `GOOGLE_CLIENT_ID` is only needed for the Google Drive integration (saving project metadata to Drive). The core server-compute workflow (upload audio → run BirdNET → publish) works without it.

### 5.8 — Production Deployment Checklist

Before going live, verify:

- [ ] `ALLOWED_ORIGINS` set to exact frontend URL (not `*`)
- [ ] `DEBUG=false` in both `.env` files
- [ ] `CEM_DATA_DIR_HOST` points to a persistent absolute path (e.g. `/opt/cem/data`)
- [ ] `SERVER_BASE_URL` set to public HTTPS URL
- [ ] `CORS_ORIGINS` set to public main website URL
- [ ] Nginx installed and configured as reverse proxy
- [ ] HTTPS enabled via Certbot
- [ ] Docker Engine auto-start enabled (`systemctl enable docker`)
- [ ] Port 8002, 8080, 8000, 8097 are **not** directly exposed in firewall (only 80/443)
- [ ] FileBrowser password changed from default if `FILEBROWSER_BASE_URL` is set
- [ ] Google OAuth Client ID set if researcher sign-in is needed

---

## Troubleshooting

### Docker & Networking

| Problem | Fix |
|---------|-----|
| `docker: command not found` | Docker Desktop is not running. Start it and wait for "Engine running". |
| `docker compose up` fails with `network not found` | Run `docker network create cem_master_network` first |
| WSL / Docker Desktop unresponsive | Run `wsl --shutdown` in PowerShell, then restart Docker Desktop |
| Port already in use | Change `COMPUTE_BACKEND_PORT`, `COMPUTE_FRONTEND_PORT`, or `PORT` in the relevant `.env` |

### Compute Stack Issues

| Problem | Fix |
|---------|-----|
| All sidebar buttons stay greyed out after Google login | Click the "Initialize Storage" prompt that appears after login — storage must be initialized first |
| Audio files not picked up in analysis | Filename doesn't match `SPOTNAME_YYYYMMDD_HHMMSS.wav` — rename the files exactly |
| 409 "no audio files for the selected date range" | Date format must be `YYYYMMDD` not `YYYY-MM-DD`. The compute UI handles this, but custom clients often don't. |
| BirdNET runs and finds nothing | Same as above — files are silently dropped if the name doesn't match the convention. |
| 409 on "Make Public" | No completed BirdNET server-side job yet, or `aggregate.csv` is missing. Run BirdNET first. |
| `BrokenProcessPool` error | Memory issue. Set `BIRDNET_MAX_WORKERS=1` in `.env` and `docker compose up -d` |
| Analysis job stuck "pending" forever | Check `docker compose logs api`. Usually means the server is offline. |
| CORS error in browser | Set `ALLOWED_ORIGINS=*` in `.env` for local dev, then `docker compose up -d` |

### Main Website Issues

| Problem | Fix |
|---------|-----|
| Map loads but no spots appear | No published projects, or `CEM_DATA_DIR_HOST` points to wrong folder. Check `docker compose logs indexer`. |
| Indexer logs show "no projects found" | `CEM_DATA_DIR_HOST` doesn't point to `cem-compute/cem-backend/data` |
| `Set DATABASE_URL` error on startup | `.env` was not created. Run `Copy-Item .env.example .env` and restart. |
| Backend container exits immediately | Check `docker compose logs backend`. Usually a DB connection issue — `cem-database` may not be healthy yet. |
| Data not appearing after "Make Public" | The indexer polls every 30s. Wait one cycle, or trigger manually: `docker compose exec backend python -m app.indexer --data-dir /data --all` |
| Project still not appearing after indexer runs | Check `project.json` inside the compute data folder — it must have `"visibility": "public"` |

### Local Watcher (Optional — for running BirdNET on your own machine)

The watcher runs BirdNET locally instead of uploading to the server. The compute UI can download `watcher.py` to your machine.

```bash
python watcher.py
```

> [!NOTE]
> First run takes several minutes — it builds a Python venv and installs TensorFlow, BirdNET, librosa, etc. The UI's watcher status indicator will show "offline" during this time. That's normal — just wait.

| Problem | Fix |
|---------|-----|
| "Another instance is already running" | Delete `system/watcher.lock` |
| `ImportError: DLL load failed` on Windows | Machine security policy is blocking `numba`. Use server compute mode instead, or contact IT. |

---

## Service URLs Summary

| Service | URL | Notes |
|---------|-----|-------|
| Compute UI | http://localhost:8080 | Upload audio, run analysis, publish projects |
| Compute API | http://localhost:8002 | Raw REST API for the compute stack |
| FileBrowser | http://localhost:8097 | Browse and download analysis outputs |
| Main Website | http://localhost:8000 | Public-facing interactive biodiversity map |
| Main Website API | http://localhost:8000/api/v1 | REST API docs |
| Main Website Swagger | http://localhost:8000/docs | Interactive API docs |
| Main Website Health | http://localhost:8000/health | Quick health check |

---

## Environment Variables Quick Reference

### `cem-compute/cem-backend/.env`

| Variable | Required? | Example | Notes |
|----------|-----------|---------|-------|
| `CEM_DATA_DIR_HOST` | Yes | `./data` | Where audio and results are stored |
| `COMPUTE_BACKEND_PORT` | No | `8002` | Compute API host port |
| `COMPUTE_FRONTEND_PORT` | No | `8080` | Compute UI host port |
| `SERVER_BASE_URL` | Yes | `http://localhost:8002` | Must match `COMPUTE_BACKEND_PORT` |
| `COMPUTE_FRONTEND_CONTEXT` | No | `../cem-frontend` | Path to frontend repo |
| `GOOGLE_CLIENT_ID` | No | *(blank)* | For Google Drive integration only |
| `BIRDNET_MAX_WORKERS` | No | `2` | Lower to `1` on low-RAM machines |
| `FILEBROWSER_BASE_URL` | No | `http://filebrowser:80` | Enable download links; blank to disable |
| `FILEBROWSER_PASSWORD` | No | `mypassword` | Check `docker compose logs filebrowser` |

### `main-website/cem-master-backend/.env`

| Variable | Required? | Example | Notes |
|----------|-----------|---------|-------|
| `CEM_DATA_DIR_HOST` | **Yes** | `../cem-compute/cem-backend/data` | Must point to compute stack's data folder |
| `MASTER_FRONTEND_CONTEXT` | Yes | `../cem-master-frontend` | Path to frontend repo |
| `PORT` | No | `8000` | Main website host port |
| `DATABASE_URL` | Yes | `postgresql+psycopg://cem_user:change-me@cem-database:5432/cem_master` | Don't change the hostname (`cem-database`) |
| `COMPUTE_FRONTEND_URL` | No | `http://127.0.0.1:8080/` | Link to compute UI |
| `FILEBROWSER_PUBLIC_URL` | No | `http://localhost:8097` | Public-facing FileBrowser URL |
| `LOG_LEVEL` | No | `info` | `debug`, `info`, or `error` |
| `INDEXER_POLL_SECONDS` | No | `30` | Polling interval for the background indexer |

---

## Key Files Reference

### `cem-compute/`
- [`.env.example`](file:///C:/Users/asus/Desktop/sem7/BTP/cem-compute-2/cem-backend/.env.example) — all env vars with comments
- [`docker-compose.yml`](file:///C:/Users/asus/Desktop/sem7/BTP/cem-compute-2/cem-backend/docker-compose.yml) — service definitions
- [`README.md`](file:///C:/Users/asus/Desktop/sem7/BTP/cem-compute-2/cem-backend/README.md) — full backend docs
- [`HOW_TO_TEST.md`](file:///C:/Users/asus/Desktop/sem7/BTP/cem-compute-2/HOW_TO_TEST.md) — end-to-end usage walkthrough

### `main-website/`
- [`.env.example`](file:///C:/Users/asus/Desktop/sem7/BTP/main-website/cem-master-backend/.env.example) — all env vars with comments
- [`compose.yaml`](file:///C:/Users/asus/Desktop/sem7/BTP/main-website/cem-master-backend/compose.yaml) — production compose (no DB)
- [`compose.local.yaml`](file:///C:/Users/asus/Desktop/sem7/BTP/main-website/cem-master-backend/compose.local.yaml) — local overlay that adds PostgreSQL
- [`my_commands.txt`](file:///C:/Users/asus/Desktop/sem7/BTP/main-website/my_commands.txt) — Windows PowerShell command cheatsheet
- [`HOW_TO_TEST.md`](file:///C:/Users/asus/Desktop/sem7/BTP/main-website/cem-master-backend/HOW_TO_TEST.md) — end-to-end testing guide
- [`DEBUGGING.md`](file:///C:/Users/asus/Desktop/sem7/BTP/main-website/cem-master-backend/DEBUGGING.md) — debug tips
