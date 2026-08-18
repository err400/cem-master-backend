#!/usr/bin/env bash
# Bring up the local development stack: Postgres + backend.
#
# compose.yaml declares `cem_master_network` as external, so it must exist
# before compose runs. Creating it is idempotent, which is why this wrapper
# exists rather than a line in the README that everyone forgets once.
#
#   ./scripts/dev-up.sh              # start
#   ./scripts/dev-up.sh --build      # rebuild the backend image first
#   ./scripts/dev-up.sh down         # stop (keeps the database volume)
#   ./scripts/dev-up.sh down -v      # stop AND DELETE the database volume

set -euo pipefail

NETWORK="cem_master_network"
COMPOSE_FILES=(-f compose.yaml -f compose.local.yaml)

cd "$(dirname "$0")/.."

# Check the daemon before anything else, otherwise every later command fails
# with the same opaque socket error.
if ! docker info >/dev/null 2>&1; then
    echo "error: the Docker daemon is not running." >&2
    echo "       Start Docker Desktop, wait for the whale icon to settle, and retry." >&2
    exit 1
fi

# compose.yaml and Dockerfile arrive with the teammates' commits. Fail with a
# useful message rather than 'no such file or directory'.
for required in compose.yaml Dockerfile; do
    if [[ ! -f "$required" ]]; then
        echo "error: $required is missing — your branch is behind origin/main." >&2
        echo "       Run: git pull    (see REVIEW-2026-08-12.md for the merge notes)" >&2
        exit 1
    fi
done

if ! docker network inspect "$NETWORK" >/dev/null 2>&1; then
    echo "Creating docker network: $NETWORK"
    docker network create "$NETWORK" >/dev/null
fi

# compose.yaml declares DATABASE_URL with `:?`, which fails BEFORE the override
# file is merged -- Compose interpolates variables across all files first, so a
# default in compose.local.yaml cannot rescue it. Supply one here instead.
#
# This is the value the BACKEND CONTAINER uses, so the host is the compose
# service name `cem-database`, not localhost. Connecting from your own machine
# (pytest, psql, alembic) uses localhost instead -- see README / conftest.
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://cem_user:change-me@cem-database:5432/cem_master}"

case "$DATABASE_URL" in
    *@localhost:*|*@127.0.0.1:*)
        echo "warning: DATABASE_URL points at localhost." >&2
        echo "         Inside the compose network the database host is 'cem-database'." >&2
        echo "         localhost from within the backend container is the container itself," >&2
        echo "         so this will fail to connect. Unset DATABASE_URL to use the default." >&2
        echo >&2
        ;;
esac

if [[ "${1:-}" == "down" ]]; then
    shift
    exec docker compose "${COMPOSE_FILES[@]}" down "$@"
fi

docker compose "${COMPOSE_FILES[@]}" up "$@"
