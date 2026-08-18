# Local setup

Everything needed to run the full stack on your own machine. Roughly five
minutes.

## The stack: three containers

```
   your browser
        │  http://localhost:8000        ← the ONLY origin the browser knows
        ▼
┌───────────────────┐
│ frontend  (nginx) │  cem-master-frontend/compose.yaml
│ 8000 → 80         │  serves index.html/js/styles, proxies /api/ onward
└─────────┬─────────┘
          │  proxy_pass http://backend:8001      (Docker DNS, service name)
          ▼
┌───────────────────┐
│ backend  (FastAPI)│  cem-master-backend/compose.yaml + compose.local.yaml
│ 8001              │  runs `alembic upgrade head`, then uvicorn
└─────────┬─────────┘
          │  postgresql+psycopg://…@cem-database:5432
          ▼
┌───────────────────┐
│ cem-database      │  cem-master-backend/compose.local.yaml
│ postgis:16-3.4    │  volume cem_master_db_data
│ 5432              │
└───────────────────┘

all three attached to the docker network: cem_master_network
```

Because nginx proxies `/api/`, the browser only ever talks to port 8000 — there
is no CORS in the picture at all. Ports 8001 and 5432 are published purely so
you can reach them from your own machine with `curl`, `psql` and `pytest`.

**One service, one owner.** The frontend repo used to define its own `backend`
service too; that was removed. See "Why the frontend no longer builds the
backend" below.

## What changed, and why you need to read this

Three behavioural changes. All three will confuse you if you don't know about
them:

1. **`uvicorn` alone no longer creates database tables.** `create_all` was
   removed (correctly — it only ever created *missing* tables and silently
   ignored changes to existing ones, so schema changes were no-ops). Schema is
   now managed by Alembic: run `alembic upgrade head` before starting the app.
   The Docker path does this for you.

2. **There was previously no way to create the schema at all.** After
   `create_all` was removed nothing replaced it, so a fresh database left every
   query failing on missing tables — while `/health` still returned `200`,
   because `SELECT 1` succeeds against an empty database. If you were seeing
   that, this is why.

3. **The frontend no longer waits for the backend.** It used to be gated on the
   backend's healthcheck. Now the page loads regardless and API calls return
   `502` if the backend is down. That is deliberate — see below.

## First run

```bash
git pull

# Compose reads .env automatically; without it DATABASE_URL is unset and
# compose.yaml fails hard on `:?`
cp .env.example .env

# Start Docker Desktop, then:
./scripts/dev-up.sh
```

`dev-up.sh` creates the `cem_master_network` docker network if missing, starts
PostgreSQL, waits for it to accept connections, applies migrations, and starts
the API on **http://localhost:8001**.

Watch for this in the logs — it means the schema was created:

```
INFO  [alembic.runtime.migration] Running upgrade  -> 79ea7b4cc34e, baseline postgres schema
```

Useful flags:

```bash
./scripts/dev-up.sh -d          # background, frees the terminal
./scripts/dev-up.sh down        # stop, keep the database
./scripts/dev-up.sh down -v     # stop AND DELETE the database volume
```

### Then the frontend

Separate repo, separate compose file, started second:

```bash
cd ../cem-master-frontend
docker compose up               # no .env needed here any more
```

Open **http://localhost:8000**.

Order matters only in that `cem_master_network` must exist — `dev-up.sh` creates
it. If you start the frontend first you will get
`network cem_master_network declared as external, but could not be found`; run
`docker network create cem_master_network` or just start the backend first.

You should end up with exactly three containers:

```
$ docker ps --format 'table {{.Names}}\t{{.Ports}}'
NAMES                             PORTS
cem-master-frontend-frontend-1    0.0.0.0:8000->80/tcp
cem-master-backend-backend-1      0.0.0.0:8001->8001/tcp
cem-master-backend-cem-database-1 0.0.0.0:5432->5432/tcp
```

**Two backend containers means something is wrong** — see the next section.

## Why the frontend no longer builds the backend

`cem-master-frontend/compose.yaml` used to define a `backend` service of its own,
built from `../cem-master-backend`. It was removed, because two files defining
the same service caused four real problems:

- **Port clash.** Both published 8001, so running both stacks failed — or worse,
  left you talking to a backend you did not think you were talking to.
- **Silent drift.** Change the command, env or mounts in one file and not the
  other, and behaviour depends on which file you happened to start from. Both
  look correct in isolation.
- **No database.** The frontend repo has no db service, so *its* backend pointed
  at a `cem-database` host that did not exist, failed its healthcheck, and —
  because the frontend was gated on `service_healthy` — **the frontend never
  started either.** A missing database in one repo silently prevented the other
  repo's UI from loading.
- **Fragile build context.** `context: ../cem-master-backend` assumed a sibling
  checkout on the right branch, and made the frontend repo responsible for
  knowing how to build the backend.

Now the frontend simply joins `cem_master_network`. `nginx.conf` is unchanged —
it still proxies to `http://backend:8001`, and Docker DNS resolves that to
whichever container provides the `backend` service.

The trade-off: with `depends_on` gone the frontend starts even when the backend
is down, and `/api/` calls return `502`. That is the better failure mode — a
visible API error is far easier to diagnose than a container that refuses to
start for reasons in another repository.

`DATABASE_URL` is no longer referenced anywhere in the frontend repo, so **no
`.env` is needed there**. `.env.example` in that repo is now just
`FRONTEND_PORT`.

## Check it worked

In a second terminal:

```bash
cd cem-master-backend

# 9 tables: the 8 models plus alembic_version
docker compose -f compose.yaml -f compose.local.yaml exec cem-database \
  psql -U cem_user -d cem_master -c '\dt'

# empty FeatureCollection is the correct answer on a fresh database
curl -s localhost:8001/api/v1/spots

# sample data, so the frontend has something to draw
docker compose -f compose.yaml -f compose.local.yaml exec backend \
  python scripts/seed_spots.py
```

## Running the indexer

The indexer turns the compute app's `aggregate.csv` into the rows the map reads.
**Run it inside the container** — it already has the dependencies, `DATA_DIR`
mounted read-only, and `DATABASE_URL` set, and this is the same way it will run in
the cluster:

```bash
python3 tests/fixtures/build_fixture.py    # from the host; stdlib only, no venv
./scripts/reindex.sh --dry-run             # compute and report, write nothing
./scripts/reindex.sh                       # write
```

`DATA_DIR` in the container defaults to the generated fixture
(`compose.local.yaml`). Point `DATA_DIR_HOST` at a real tree to index that
instead. The fixture must be built from the host, because the container mounts
`DATA_DIR` read-only.

After a successful run, reload http://localhost:8000 — the fixture's spots appear
on the map with numbers that trace back to a CSV you can count by hand.

Nothing needs installing on your own machine for this. If you *want* to run it
directly for debugging, you need a virtualenv with `requirements.txt` installed
(the indexer uses pandas) and the **host-side** database URL — `@localhost:5432`,
not `@cem-database`.

## Running the tests

The suite needs a real PostgreSQL — `app/config.py` rejects non-PostgreSQL URLs,
and the models use `JSONB`, which SQLite cannot create. `scripts/initdb` already
created the `cem_master_test` database for you.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

set -a && source .env && set +a      # loads TEST_DATABASE_URL
pytest
```

Without `TEST_DATABASE_URL` the suite skips rather than fails, and says so in the
report header.

## Two DATABASE_URLs, and why

This trips everyone once:

| Who is connecting | Host | Database |
|---|---|---|
| The backend **container** | `cem-database` | `cem_master` |
| **You**, from your machine (pytest, psql, alembic) | `localhost` | `cem_master_test` |

`localhost` inside the backend container is the container itself, not the
database. `dev-up.sh` warns if `DATABASE_URL` looks like a host-side URL.

## Changing the schema

```bash
# 1. edit app/models.py, then generate a migration
alembic revision --autogenerate -m "describe the change"

# 2. READ the generated file in migrations/versions/ before applying it --
#    autogenerate is good, not infallible

# 3. see exactly what SQL it will run, without touching a database
alembic upgrade base:head --sql

# 4. apply
alembic upgrade head
```

Never edit an applied migration; add a new one. `alembic current` shows where a
database is, `alembic history` shows the chain.

`tests/test_migrations.py` fails if models and migrations drift apart — if it
goes red, you almost certainly forgot step 1.

## If something is wrong

**`required variable DATABASE_URL is missing a value`** — no `.env` file.
`cp .env.example .env`.

**`Cannot connect to the Docker daemon`** — Docker Desktop isn't running.

**`relation "spots" does not exist`** — migrations didn't run. If you started the
app outside Docker, run `alembic upgrade head` first.

**`Can't locate revision`, or a half-created schema** — the volume is in a state
that predates the current migrations. Reset it:

```bash
./scripts/dev-up.sh down -v && ./scripts/dev-up.sh
```

**`psql: database "cem_master_test" does not exist`** — `scripts/initdb` only
runs when the data volume is first created. Same reset as above.

**Two backend containers in `docker ps`** — you are running an old
`cem-master-frontend/compose.yaml` that still defines its own `backend`. Pull the
frontend repo, then `docker compose down` and `up` there to recreate.

**`network cem_master_network declared as external, but could not be found`** —
start the backend stack first, or `docker network create cem_master_network`.

**Frontend loads but every panel shows an error** — the backend is down or still
migrating. Check `curl -s localhost:8001/health`; expect
`{"status":"ok","database":"postgresql"}`. This is the intended behaviour now
that the frontend no longer waits for the backend.

**The map is empty** — correct on a fresh database. Run the seed script above.

---

## One thing worth being clear about

The stack runs end to end, but **every number the UI currently shows is
fabricated by `scripts/seed_spots.py`**. No detection has yet come from a BirdNET
run.
