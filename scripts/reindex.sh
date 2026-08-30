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

# `docker compose exec` runs inside the container that ALREADY EXISTS. It does
# not re-read compose.yaml's environment, so setting FILEBROWSER_PUBLIC_URL in
# your shell and running this script has no effect -- the indexer sees the value
# the container was created with, and every output link comes back empty with no
# error. Forward it explicitly, and say so, because a silently missing link is
# indistinguishable from a job that has no share.
exec_env=()
container_fb="$(docker compose "${COMPOSE_FILES[@]}" exec -T backend \
    printenv FILEBROWSER_PUBLIC_URL 2>/dev/null | tr -d '\r\n' || true)"

if [[ -n "${FILEBROWSER_PUBLIC_URL:-}" && "${FILEBROWSER_PUBLIC_URL}" != "${container_fb}" ]]; then
    echo "note: forwarding FILEBROWSER_PUBLIC_URL=${FILEBROWSER_PUBLIC_URL} into the container." >&2
    echo "      The container itself has '${container_fb}'. To make this stick — and to fix" >&2
    echo "      the background 'indexer' service, which re-indexes every ${INDEXER_POLL_SECONDS:-30}s and would" >&2
    echo "      otherwise overwrite these links with nulls — put it in .env and run:" >&2
    echo "          ./scripts/dev-up.sh -d" >&2
    echo >&2
    exec_env=(-e "FILEBROWSER_PUBLIC_URL=${FILEBROWSER_PUBLIC_URL}")
elif [[ -z "${FILEBROWSER_PUBLIC_URL:-}" && -z "${container_fb}" ]]; then
    echo "note: FILEBROWSER_PUBLIC_URL is not set, so job outputs will be named but" >&2
    echo "      not linked. Set it in .env and run ./scripts/dev-up.sh -d to enable links." >&2
    echo >&2
fi

# `${a[@]+"${a[@]}"}` rather than plain `"${a[@]}"`: macOS ships bash 3.2, where
# expanding an EMPTY array under `set -u` is an unbound-variable error.
exec docker compose "${COMPOSE_FILES[@]}" exec ${exec_env[@]+"${exec_env[@]}"} backend \
    python -m app.indexer --data-dir /data "${args[@]}"
