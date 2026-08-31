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
import time
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from . import rollups
from . import source
from .writer import prune_project, prune_projects_not_in, write


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
    parser.add_argument(
        "--filebrowser-url",
        default=os.getenv("FILEBROWSER_PUBLIC_URL", ""),
        help=(
            "public base URL of FileBrowser, as a visitor's browser reaches it "
            "(e.g. http://localhost:8097). Used to turn the share hashes the "
            "compute app recorded into download links. Blank means job outputs "
            "are named but not linked -- no link is better than a broken one."
        ),
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--project", help="index a single project by name")
    scope.add_argument("--all", action="store_true", help="index every project found")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="compute and report, then roll back without writing",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="keep polling DATA_DIR and re-indexing the selected scope",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=float(os.getenv("INDEXER_POLL_SECONDS", "30")),
        help="polling interval for --watch (default: $INDEXER_POLL_SECONDS or 30)",
    )
    return parser.parse_args(argv)


def _index_project(
    db: Session,
    data_dir: Path,
    project: str,
    dry_run: bool,
    filebrowser_url: str = "",
) -> bool:
    """Index one project inside its own transaction. Returns True on success."""
    try:
        detections = source.read_aggregate(data_dir, project)
        coords = source.read_geo(data_dir, project)
        audio_counts = source.count_audio_files(data_dir, project)
        jobs = source.list_jobs(data_dir, project)
        verdicts, pooled = source.read_migratory(data_dir, project)
        indices = source.read_acoustic_indices(data_dir, project)
        iucn_cache = source.read_species_iucn_cache(data_dir, project)
    except source.SourceError as exc:
        print(f"project {project}: SKIPPED -- {exc}", file=sys.stderr)
        return False

    if detections.empty:
        print(f"project {project}: no detections in dataset/aggregate.csv, nothing to index")
        return True

    computed = rollups.build(
        detections, audio_counts=audio_counts, iucn_cache=iucn_cache
    )
    report = write(
        db,
        project,
        computed,
        coords,
        jobs=jobs,
        verdicts=verdicts,
        indices=indices,
        pooled_verdicts=pooled,
        filebrowser_url=filebrowser_url,
    )

    if dry_run:
        db.rollback()
        print(report.summary())
        print("  (dry run -- rolled back, nothing written)")
    else:
        db.commit()
        print(report.summary())

    return True


def _validate_args(args: argparse.Namespace) -> tuple[Path, str] | None:
    if not args.data_dir:
        print("error: --data-dir is required (or set DATA_DIR)", file=sys.stderr)
        return None
    if not args.database_url:
        print("error: --database-url is required (or set DATABASE_URL)", file=sys.stderr)
        return None

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
        return None

    url = args.database_url
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return data_dir, url


def _run_once(args: argparse.Namespace, data_dir: Path, url: str) -> int:
    try:
        projects = [args.project] if args.project else source.list_projects(data_dir)
    except source.SourceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        if args.project and not source.is_project_public(data_dir, args.project):
            engine = create_engine(url)
            try:
                with Session(engine) as db:
                    removed = prune_project(db, args.project)
                    if args.dry_run:
                        db.rollback()
                    else:
                        db.commit()
            finally:
                engine.dispose()
            suffix = " (dry run)" if args.dry_run else ""
            print(
                f"project {args.project}: private -- pruned {removed} stale spot(s){suffix}",
                file=sys.stderr,
            )
            return 0
    except source.SourceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    engine = create_engine(url)
    failures = 0
    try:
        if args.all:
            with Session(engine) as db:
                pruned = prune_projects_not_in(db, set(projects))
                if args.dry_run:
                    db.rollback()
                else:
                    db.commit()
            for project, count in pruned.items():
                suffix = " (dry run)" if args.dry_run else ""
                print(f"project {project}: pruned {count} stale spot(s){suffix}")

        if not projects:
            print(f"no public projects found under {data_dir / 'projects'}")
            return 0

        for project in projects:
            # A separate session per project, so one project's failure cannot
            # leave another's writes pending in a poisoned transaction.
            with Session(engine) as db:
                try:
                    if not _index_project(
                        db,
                        data_dir,
                        project,
                        args.dry_run,
                        filebrowser_url=getattr(args, "filebrowser_url", ""),
                    ):
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


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    validated = _validate_args(args)
    if validated is None:
        return 2
    data_dir, url = validated

    if not args.watch:
        return _run_once(args, data_dir, url)

    interval = max(1.0, args.interval_seconds)
    print(f"watching {data_dir} every {interval:g}s", flush=True)
    while True:
        started = time.time()
        code = _run_once(args, data_dir, url)
        if code not in (0, 1):
            print(f"watch pass exited with code {code}", file=sys.stderr, flush=True)
        elapsed = time.time() - started
        time.sleep(max(1.0, interval - elapsed))


if __name__ == "__main__":
    raise SystemExit(main())
