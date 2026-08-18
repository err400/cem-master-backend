"""Indexer CLI.

    python -m app.indexer --data-dir ./tests/fixtures/data_dir --all
    python -m app.indexer --project fixture-demo
    python -m app.indexer --all --dry-run

``--data-dir`` and ``--database-url`` are explicit flags rather than pure
environment lookups, because three different connection strings are in play in
this project and picking the wrong one silently is easy:

    backend container   @cem-database:5432/cem_master
    pytest on the host  @localhost:5432/cem_master_test
    indexer on the host @localhost:5432/cem_master     <-- this one

Both fall back to the environment when omitted.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from . import rollups
from . import source
from .writer import write


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.indexer",
        description="Index the compute app's DATA_DIR into the master catalog.",
    )
    parser.add_argument(
        "--data-dir",
        default=os.getenv("DATA_DIR", ""),
        help="root of the compute app's data volume (default: $DATA_DIR)",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("INDEXER_DATABASE_URL") or os.getenv("DATABASE_URL", ""),
        help="target database (default: $INDEXER_DATABASE_URL, then $DATABASE_URL)",
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--project", help="index a single project by name")
    scope.add_argument("--all", action="store_true", help="index every project found")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="compute and report, then roll back without writing",
    )
    return parser.parse_args(argv)


def _index_project(db: Session, data_dir: Path, project: str, dry_run: bool) -> bool:
    """Index one project inside its own transaction. Returns True on success."""
    try:
        detections = source.read_aggregate(data_dir, project)
        coords = source.read_geo(data_dir, project)
        audio_counts = source.count_audio_files(data_dir, project)
        jobs = source.list_jobs(data_dir, project)
        verdicts, pooled = source.read_migratory(data_dir, project)
        indices = source.read_acoustic_indices(data_dir, project)
    except source.SourceError as exc:
        print(f"project {project}: SKIPPED -- {exc}", file=sys.stderr)
        return False

    if detections.empty:
        print(f"project {project}: no detections in dataset/aggregate.csv, nothing to index")
        return True

    computed = rollups.build(detections, audio_counts=audio_counts)
    report = write(
        db,
        project,
        computed,
        coords,
        jobs=jobs,
        verdicts=verdicts,
        indices=indices,
        pooled_verdicts=pooled,
    )

    if dry_run:
        db.rollback()
        print(report.summary())
        print("  (dry run -- rolled back, nothing written)")
    else:
        db.commit()
        print(report.summary())

    return True


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if not args.data_dir:
        print("error: --data-dir is required (or set DATA_DIR)", file=sys.stderr)
        return 2
    if not args.database_url:
        print("error: --database-url is required (or set DATABASE_URL)", file=sys.stderr)
        return 2

    data_dir = Path(args.data_dir).resolve()
    if not (data_dir / "projects").is_dir():
        print(
            f"error: {data_dir} does not look like a DATA_DIR "
            "(no projects/ directory inside it)",
            file=sys.stderr,
        )
        # The commonest causes, in the order they actually happen. An empty
        # directory here almost always means the mount, not the data.
        if not data_dir.exists():
            print(f"       {data_dir} does not exist at all.", file=sys.stderr)
        else:
            contents = sorted(p.name for p in data_dir.iterdir())
            print(
                f"       contents: {contents if contents else '(empty)'}",
                file=sys.stderr,
            )
            if not contents:
                print(
                    "\n       An empty mount usually means the container predates the\n"
                    "       volume being added, or the fixture directory was replaced\n"
                    "       while the container was running. Recreate the container:\n"
                    "           ./scripts/dev-up.sh down && ./scripts/dev-up.sh -d --build",
                    file=sys.stderr,
                )
        return 2

    url = args.database_url
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)

    try:
        projects = [args.project] if args.project else source.list_projects(data_dir)
    except source.SourceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not projects:
        print(f"no projects found under {data_dir / 'projects'}")
        return 0

    engine = create_engine(url)
    failures = 0
    try:
        for project in projects:
            # A separate session per project, so one project's failure cannot
            # leave another's writes pending in a poisoned transaction.
            with Session(engine) as db:
                try:
                    if not _index_project(db, data_dir, project, args.dry_run):
                        failures += 1
                except Exception as exc:  # noqa: BLE001 - report and continue
                    db.rollback()
                    failures += 1
                    print(f"project {project}: FAILED -- {exc}", file=sys.stderr)
    finally:
        engine.dispose()

    if failures:
        print(f"\n{failures} of {len(projects)} project(s) failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
