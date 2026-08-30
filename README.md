# cem-master-backend

API, database and **indexer** for the public CEM Master catalogue — the
read-only map at [cem-master-frontend](../cem-master-frontend).

This repo starts the whole master stack.

```text
frontend (nginx :8000) ──/api/──▶ backend (FastAPI :8001) ──▶ cem-database (PostgreSQL)
                                                                   ▲
                                        indexer ──reads──▶ DATA_DIR (read-only)
```

The API answers every request from PostgreSQL and never touches `DATA_DIR`.
Only the indexer reads the filesystem.

## Quick start

Clone the two master repos **side by side** — compose builds the frontend from
`../cem-master-frontend`.

```bash
cp .env.example .env        # then set CEM_DATA_DIR_HOST
./scripts/dev-up.sh -d      # database + API + indexer + page
```

Map <http://localhost:8000> · API docs <http://localhost:8001/docs>

```bash
./scripts/dev-up.sh -d --build   # rebuild first
./scripts/dev-up.sh down         # stop, keep the database
./scripts/dev-up.sh down -v      # stop AND DELETE the database
```

`dev-up.sh` exists because `compose.yaml` declares an external network and a
`:?` `DATABASE_URL` — correct for the cluster, fatal on a laptop. It creates the
network and supplies a default.

## Configuration

`.env`, read automatically by Compose.

| Variable | Default | Notes |
| --- | --- | --- |
| `DATABASE_URL` | `…@cem-database:5432/…` | Host is the **service name**, not localhost |
| `CEM_DATA_DIR_HOST` | `../cem-backend/data` | Compute output, mounted read-only |
| `TEST_DATABASE_URL` | `…@localhost:5432/…` | `localhost` — pytest runs on your machine |
| `FILEBROWSER_PUBLIC_URL` | *(blank)* | Enables job download links |
| `INDEXER_POLL_SECONDS` | `30` | |
| `MASTER_FRONTEND_PORT` | `8000` | |

> **Changing `.env` needs `./scripts/dev-up.sh -d`, not a restart.** Compose only
> reads environment when it *creates* a container, and `docker compose exec` runs
> inside the one that already exists — so a value exported in your shell never
> reaches the process.

## Indexer

Species search spans every project, so the work happens on write, not on read.
The indexer walks `DATA_DIR`, rolls detections up per spot and species, and
upserts them — then runs a delete pass, so re-indexing unchanged data changes
nothing and removed data disappears.

It only indexes projects whose `project.json` says public, and fails closed.

```bash
./scripts/reindex.sh                     # all public projects
./scripts/reindex.sh --dry-run           # report, write nothing
./scripts/reindex.sh --project real-test
```

The `indexer` service does the same continuously (`--watch`).

**Job download links.** `output_url` is a FileBrowser share the compute app
already created; the indexer only reads the hash. Set `FILEBROWSER_PUBLIC_URL`
to the address a *browser* uses (e.g. `http://localhost:8097`) — not the compute
app's `FILEBROWSER_BASE_URL`, which is container-internal. Blank means outputs
are named but not linked, which is the right default for real private data:
see [`INDEXING-PLAN.md`](INDEXING-PLAN.md) §4.3a. `input_url` is always null —
the compute app shares results only.

## Migrations and tests

Alembic owns the schema; `create_all` is not used, because it never *alters* an
existing table.

```bash
docker compose exec backend alembic revision --autogenerate -m "add x"
docker compose exec backend alembic upgrade head
```

```bash
set -a && source .env && set +a
python3 -m pytest
```

Most tests need PostgreSQL. Without `TEST_DATABASE_URL` those modules are
skipped rather than failed, and the report header says so.

## Scripts

| Script | Purpose |
| --- | --- |
| `scripts/dev-up.sh` | Start/stop the stack |
| `scripts/reindex.sh` | Index on demand |
| `scripts/seed_spots.py` | Sample spots, no real data needed |
| `tests/fixtures/build_fixture.py` | Build a synthetic `DATA_DIR` |
| `scripts/dev_make_shares.py` | Mint real FileBrowser shares for fixture jobs |
| `scripts/dev_compute_e2e.py` | Full loop: audio → BirdNET → publish → map |

`dev_compute_e2e.py` reads coordinates from each recording's GUANO metadata
(Song Meter GPS), so nobody types them.

## Troubleshooting

**Job links all show `—`** — `FILEBROWSER_PUBLIC_URL` never reached the process.
Put it in `.env` and re-run `dev-up.sh -d`; `exec` cannot see a value exported
after the container was created.

**`/data` empty in the container** — the container predates the volume, or the
fixture directory was replaced while it ran. `dev-up.sh down && dev-up.sh -d`.

**A spot has no coordinates** — they exist only in `<job>/input/geo.json`, from
the frontend's `spots_geo`. A spot never analysed has none. The indexer reports
this rather than writing `0, 0`: a fabricated coordinate looks like data.

**Spots merged or split** — identity is a rounded `geo_key` (5 dp ≈ 1.1 m) with
name aliases in `spot_sources`. `INDEXING-PLAN.md` §6.3.

**Warnings about `min_confidence` or pooled migratory classification** — both
accurate. Those rows predate the pipeline changes that record a per-file
detection floor and per-spot verdicts.

## Related

- [cem-master-frontend](../cem-master-frontend) — the map page
- [cem-backend](../cem-backend) — compute API that produces `DATA_DIR`
- [`INDEXING-PLAN.md`](INDEXING-PLAN.md) — design decisions and open questions
