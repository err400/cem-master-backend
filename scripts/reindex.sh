#!/usr/bin/env bash
# Run the indexer inside the backend container.
#
# There is no reason to install anything on your own machine: the container
# already has the dependencies, already has DATA_DIR mounted read-only, and
# already has DATABASE_URL pointing at cem-database. This is also how it will run
# in the cluster (as a Job or CronJob using the same image), so running it here
# exercises the real path rather than a laptop-only one.
#
#   ./scripts/reindex.sh                  # index every project under DATA_DIR
#   ./scripts/reindex.sh --dry-run        # compute and report, write nothing
#   ./scripts/reindex.sh --project foo    # one project
#
# By default DATA_DIR in the container is the generated fixture (see
# compose.local.yaml). Build it first, from the host -- build_fixture.py uses only
# the standard library, so it needs no virtualenv:
#
#   python3 tests/fixtures/build_fixture.py
#
# It must be built from the host because the container mounts DATA_DIR :ro.

set -euo pipefail

COMPOSE_FILES=(-f compose.yaml -f compose.local.yaml)

cd "$(dirname "$0")/.."

if ! docker info >/dev/null 2>&1; then
    echo "error: the Docker daemon is not running." >&2
    exit 1
fi

if ! docker compose "${COMPOSE_FILES[@]}" ps --status running backend 2>/dev/null | grep -q backend; then
    echo "error: the backend container is not running." >&2
    echo "       Start it with: ./scripts/dev-up.sh -d" >&2
    exit 1
fi

# --all unless the caller scoped it themselves; the CLI requires one or the other.
args=("$@")
if [[ ! " ${args[*]-} " =~ " --project " && ! " ${args[*]-} " =~ " --all " ]]; then
    args+=(--all)
fi

exec docker compose "${COMPOSE_FILES[@]}" exec backend \
    python -m app.indexer --data-dir /data "${args[@]}"
