"""Writing rollups into the catalog, idempotently.

Three properties this file exists to guarantee. Each one is a way an
indexer that "works" can still be wrong:

1. **Replace, never increment.** Every value is computed in full from the source
   and SET. ``detection_count = detection_count + n`` would double every number
   on the second run, and nothing would look broken.

2. **Delete what is no longer there.** Upsert can insert and update but cannot
   remove. If a species stops appearing -- re-filtered at a higher floor, a bad
   detection corrected, a recording withdrawn -- the stale row survives and the
   bird stays on the public page forever. So each pass computes the desired set,
   upserts it, then deletes rows for this project that are not in it.

3. **One transaction per project.** A crash halfway must not leave a spot showing
   half its species. Either the whole project's index is visible or none of the
   new state is.

Scoping note: every delete is scoped to ``source_project_id``, so indexing one
project can never touch another project's contribution to the same physical spot,
nor the rows written by ``scripts/seed_spots.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    AnalysisJob,
    Species,
    Spot,
    SpotSource,
    SpotSpeciesDaily,
    SpotSpeciesSummary,
    SpotSummary,
)

from .rollups import SpotRollup
from .source import POOLED_SPOT, JobRef, make_geo_key


@dataclass
class IndexReport:
    """What a pass did, for the CLI to print and tests to assert on."""

    project: str
    spots_seen: int = 0
    spots_created: int = 0
    species_created: int = 0
    species_rows_written: int = 0
    daily_rows_written: int = 0
    species_rows_deleted: int = 0
    daily_rows_deleted: int = 0
    jobs_written: int = 0
    jobs_deleted: int = 0
    migration_classes_set: int = 0
    spots_with_indices: int = 0
    spot_aliases_added: int = 0
    spots_without_coordinates: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"project {self.project}:",
            f"  spots            {self.spots_seen} seen, {self.spots_created} created",
            f"  species          {self.species_created} created",
            f"  spot x species   {self.species_rows_written} written, "
            f"{self.species_rows_deleted} stale removed",
            f"  daily rows       {self.daily_rows_written} written, "
            f"{self.daily_rows_deleted} stale removed",
            f"  analysis jobs    {self.jobs_written} written, "
            f"{self.jobs_deleted} stale removed",
            f"  migration class  {self.migration_classes_set} set",
            f"  acoustic indices {self.spots_with_indices} spot(s)",
        ]
        if self.spots_without_coordinates:
            lines.append(
                "  NO COORDINATES   "
                + ", ".join(sorted(self.spots_without_coordinates))
                + "  (not placeable on the map)"
            )
        for warning in self.warnings:
            lines.append(f"  warning: {warning}")
        return "\n".join(lines)


def _upsert_species(db: Session, rollups: list[SpotRollup], report: IndexReport) -> dict[str, Species]:
    """Ensure a Species row exists for every scientific name seen.

    Keyed on scientific_name, which carries the unique constraint. Common names
    are refreshed but never used as identity -- BirdNET's common names vary and
    two spellings of one bird must not become two species.
    """
    wanted: dict[str, str] = {}
    for rollup in rollups:
        for item in rollup.species:
            wanted.setdefault(item.scientific_name, item.common_name)

    if not wanted:
        return {}

    existing = {
        s.scientific_name: s
        for s in db.scalars(
            select(Species).where(Species.scientific_name.in_(wanted))
        ).all()
    }

    for sci_name, common_name in wanted.items():
        species = existing.get(sci_name)
        if species is None:
            species = Species(scientific_name=sci_name, common_name=common_name)
            db.add(species)
            existing[sci_name] = species
            report.species_created += 1
        else:
            species.common_name = common_name

    db.flush()
    return existing


def _upsert_spot(
    db: Session,
    project: str,
    rollup: SpotRollup,
    coords: dict[str, tuple[float, float]],
    report: IndexReport,
) -> Spot | None:
    """Ensure a Spot row exists for this project's spot.

    Returns None when no coordinates can be found. That is not an error -- a spot
    only gets coordinates once an analysis job has run and written geo.json, and
    those folders are swept after 7 days -- but such a spot cannot be placed on a
    map, so it is reported rather than invented at 0,0.
    """
    position = coords.get(rollup.spot_key)
    geo_key = make_geo_key(*position) if position else None

    # 1. By the name this project used. spot_sources holds every name a spot has
    #    been known by, so a spot renamed on a previous pass still resolves from
    #    its old detections.
    source_row = db.scalar(
        select(SpotSource).where(
            SpotSource.source_project_id == project,
            SpotSource.source_spot_id == rollup.spot_key,
        )
    )
    spot = db.get(Spot, source_row.spot_id) if source_row else None

    # 2. By physical location. This is what makes a rename a rename: the name
    #    changed but the recorder did not move, so the key is unchanged.
    if spot is None and geo_key is not None:
        spot = db.scalar(select(Spot).where(Spot.geo_key == geo_key))

        if spot is not None and spot.source_project_id != project:
            # A different project already holds this location. The schema's
            # intent is that they share one canonical spot, attaching through
            # spot_sources -- but the rollup tables are keyed on spot_id alone,
            # so two projects sharing a spot would overwrite each other's
            # totals and whichever indexed last would win. That needs
            # source_project_id on the rollups (INDEXING-PLAN 6.6b), which is a
            # migration rather than a patch here.
            report.warnings.append(
                f"{rollup.spot_key}: location {geo_key} is already held by "
                f"project {spot.source_project_id!r} (spot "
                f"{spot.source_spot_id!r}). Two projects at one place need the "
                "rollup tables keyed by source_project_id first "
                "(INDEXING-PLAN 6.6b); skipping this spot."
            )
            return None

        if spot is not None:
            # Same project, same place, different name -- a rename. Record the
            # new name as another source so future passes resolve it by name
            # directly, and so the old name keeps resolving too: historical
            # detections still carry it.
            report.warnings.append(
                f"{rollup.spot_key}: same location as existing spot "
                f"{spot.source_spot_id!r}, treated as a rename rather than a new "
                "spot. Both names now resolve to it."
            )
            db.add(
                SpotSource(
                    spot_id=spot.id,
                    source_project_id=project,
                    source_spot_id=rollup.spot_key,
                )
            )
            report.spot_aliases_added += 1

    if spot is None:
        if position is None:
            # No coordinates anywhere: geo.json was never written, or the job
            # folder holding it has been swept (retention, ~7 days). Reported
            # rather than invented at 0,0 -- a fabricated position on a public
            # ecological map is worse than an absent one.
            report.spots_without_coordinates.append(rollup.spot_key)
            return None

        spot = Spot(
            source_project_id=project,
            source_spot_id=rollup.spot_key,
            geo_key=geo_key,
            name=rollup.spot_label,
            description=None,
            latitude=position[0],
            longitude=position[1],
        )
        db.add(spot)
        db.flush()
        report.spots_created += 1
        db.add(
            SpotSource(
                spot_id=spot.id,
                source_project_id=project,
                source_spot_id=rollup.spot_key,
            )
        )
    else:
        spot.name = rollup.spot_label
        # Only overwrite coordinates when we actually have some. Once captured,
        # the database is the durable record; a later pass finding no geo.json
        # because retention swept it must not blank them.
        if position is not None:
            spot.latitude, spot.longitude = position
            spot.geo_key = geo_key

    return spot


def _write_spot_summary(db: Session, spot: Spot, rollup: SpotRollup) -> None:
    values = {
        "recording_count": rollup.recording_count,
        "species_richness": rollup.species_richness,
        "total_detections": rollup.total_detections,
        "active_days": rollup.active_days,
        "first_recording_date": rollup.first_recording_date,
        "last_recording_date": rollup.last_recording_date,
    }
    summary = db.get(SpotSummary, spot.id)
    if summary is None:
        db.add(SpotSummary(spot_id=spot.id, **values))
    else:
        for key, value in values.items():
            setattr(summary, key, value)


def _write_spot_species(
    db: Session,
    spot: Spot,
    rollup: SpotRollup,
    species_by_name: dict[str, Species],
    report: IndexReport,
) -> None:
    """Upsert this spot's per-species rows, then remove any that vanished."""
    keep: set[int] = set()

    for item in rollup.species:
        species = species_by_name[item.scientific_name]
        row = db.scalar(
            select(SpotSpeciesSummary).where(
                SpotSpeciesSummary.spot_id == spot.id,
                SpotSpeciesSummary.species_id == species.id,
            )
        )
        values = {
            "detection_count": item.detection_count,
            "active_days": item.active_days,
            "activity_rank": item.activity_rank,
            "average_confidence": item.average_confidence,
            "maximum_confidence": item.maximum_confidence,
            "first_detection_date": item.first_detection_date,
            "last_detection_date": item.last_detection_date,
            "hourly_counts": item.hourly_counts,
            "daily_counts": item.daily_counts,
            "monthly_counts": item.monthly_counts,
        }
        if row is None:
            row = SpotSpeciesSummary(spot_id=spot.id, species_id=species.id, **values)
            db.add(row)
            db.flush()
        else:
            for key, value in values.items():
                setattr(row, key, value)
        keep.add(species.id)
        report.species_rows_written += 1

    # --- the delete pass ---
    # Anything this spot used to have and no longer does. When `keep` is empty
    # (the spot has no detections at all any more) every row goes, so the
    # NOT IN clause is omitted rather than passed an empty set.
    stale = delete(SpotSpeciesSummary).where(SpotSpeciesSummary.spot_id == spot.id)
    if keep:
        stale = stale.where(SpotSpeciesSummary.species_id.not_in(keep))
    report.species_rows_deleted += db.execute(stale).rowcount or 0


def _write_daily(
    db: Session,
    spot: Spot,
    rollup: SpotRollup,
    species_by_name: dict[str, Species],
    report: IndexReport,
) -> None:
    """Rewrite this spot's daily grain.

    Deleted and reinserted wholesale rather than diffed row by row: the grain is
    (spot x species x date), a re-index legitimately changes many rows at once,
    and reconstructing it is cheap. Doing it inside the project transaction means
    the table is never observed empty.
    """
    report.daily_rows_deleted += (
        db.execute(
            delete(SpotSpeciesDaily).where(SpotSpeciesDaily.spot_id == spot.id)
        ).rowcount
        or 0
    )
    for entry in rollup.daily:
        db.add(
            SpotSpeciesDaily(
                spot_id=spot.id,
                species_id=species_by_name[entry.scientific_name].id,
                observation_date=entry.observation_date,
                detection_count=entry.detection_count,
            )
        )
        report.daily_rows_written += 1


def _write_migration_class(
    db: Session,
    spot: Spot,
    rollup: SpotRollup,
    species_by_name: dict[str, Species],
    verdicts: dict[tuple[str, str], dict],
    report: IndexReport,
) -> None:
    """Set migratory/resident on this spot's species rows.

    Looks up (spot, common name) first, falling back to the pooled sentinel when
    only the species-level file existed. "Unknown" is written through rather
    than skipped: it is a real answer -- too few detections here to judge -- and
    is more useful than a blank that looks like missing data.
    """
    for item in rollup.species:
        verdict = verdicts.get((rollup.spot_key, item.common_name)) or verdicts.get(
            (POOLED_SPOT, item.common_name)
        )
        if not verdict:
            continue
        species = species_by_name[item.scientific_name]
        row = db.scalar(
            select(SpotSpeciesSummary).where(
                SpotSpeciesSummary.spot_id == spot.id,
                SpotSpeciesSummary.species_id == species.id,
            )
        )
        if row is None:
            continue
        row.migration_class = str(verdict.get("Classification") or "") or None
        # SCI / Kurtosis / PMR go in analysis_metrics, which the frontend renders
        # as a labelled grid. Keeping them beside the verdict means a reader can
        # see WHY a bird was called migratory, not just that it was.
        metrics = {
            key.lower(): float(verdict[key])
            for key in ("SCI", "Kurtosis", "PMR")
            if key in verdict and verdict[key] is not None
        }
        if metrics:
            row.analysis_metrics = {**(row.analysis_metrics or {}), **metrics}
        report.migration_classes_set += 1


def _write_indices(
    db: Session, spot: Spot, rollup: SpotRollup, indices: dict[str, dict], report: IndexReport
) -> None:
    values = indices.get(rollup.spot_key)
    if not values:
        return
    summary = db.get(SpotSummary, spot.id)
    if summary is not None:
        summary.acoustic_indices = values
        report.spots_with_indices += 1


def _as_datetime(value):
    """Parse an ISO-8601 timestamp from job.json, tolerating junk.

    A malformed timestamp is not worth failing a whole project's index over --
    the job row is still useful without it.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _write_jobs(
    db: Session,
    project: str,
    jobs: list[JobRef],
    spots_by_key: dict[str, Spot],
    report: IndexReport,
) -> None:
    """Register analysis runs, one row per (job, spot) it covered.

    ⚠️ WORKING AROUND A SCHEMA LIMIT. ``analysis_jobs.job_id`` is the primary key
    and ``spot_id`` is a single column, so the table cannot represent one run
    covering several spots -- but the pipeline's ``spot_date_range`` input takes
    exactly that, and steps like spatial_stickiness are inherently cross-spot.

    So a multi-spot run is stored as one row per spot with a composite key,
    ``<job_id>#<spot_key>``, and the real id preserved in ``job_metadata``. It is
    a workaround, and it is visible in the data rather than hidden: when the
    ``job_spots`` join table lands (INDEXING-PLAN 3.1 / conflict C1) these
    collapse back to one row per job and the composite ids disappear.

    Single-spot runs -- the common case -- keep their plain job id.
    """
    keep: set[str] = set()

    for job in jobs:
        meta = job.read_meta()
        facts = job.facts()
        spot_keys = [k for k in job.spot_keys() if k in spots_by_key]
        if not spot_keys:
            # A job whose spots we could not resolve: no coordinates, or a name
            # that does not match the aggregate. Nothing to attach it to.
            continue

        outputs = job.result_files()
        composite = len(spot_keys) > 1

        for spot_key in spot_keys:
            row_id = f"{job.job_id}#{spot_key}" if composite else job.job_id
            keep.add(row_id)

            values = {
                "spot_id": spots_by_key[spot_key].id,
                "species_id": None,  # runs are not species-specific
                "analysis_type": job.script,
                "status": facts["status"],
                "started_at": _as_datetime(facts["started_at"]),
                "completed_at": _as_datetime(facts["completed_at"]),
                # Local DATA_DIR paths must never reach the browser, so only the
                # file NAMES are recorded here. Turning them into fetchable URLs
                # is the artifact-serving question (INDEXING-PLAN 4.3), not this
                # function's job.
                "input_url": None,
                "output_url": None,
                "job_metadata": {
                    "job_id": job.job_id,
                    "project": project,
                    "spots": spot_keys,
                    "parameters": facts["params"],
                    "date_start": meta.get("start_date"),
                    "date_end": meta.get("end_date"),
                    "outputs": [p.name for p in outputs],
                    "output_count": len(outputs),
                },
            }

            row = db.get(AnalysisJob, row_id)
            if row is None:
                db.add(AnalysisJob(job_id=row_id, **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            report.jobs_written += 1

    # Delete pass, scoped to this project's spots so other projects are untouched.
    spot_ids = [s.id for s in spots_by_key.values()]
    if spot_ids:
        stale = delete(AnalysisJob).where(AnalysisJob.spot_id.in_(spot_ids))
        if keep:
            stale = stale.where(AnalysisJob.job_id.not_in(keep))
        report.jobs_deleted += db.execute(stale).rowcount or 0


def write(
    db: Session,
    project: str,
    rollups: list[SpotRollup],
    coords: dict[str, tuple[float, float]],
    jobs: list[JobRef] | None = None,
    verdicts: dict[tuple[str, str], dict] | None = None,
    indices: dict[str, dict] | None = None,
    pooled_verdicts: bool = False,
) -> IndexReport:
    """Write one project's rollups. Caller owns the transaction.

    Deliberately does NOT commit: the CLI commits once per project so a failure
    part-way leaves nothing visible, and ``--dry-run`` can roll back instead.
    """
    report = IndexReport(project=project, spots_seen=len(rollups))

    for rollup in rollups:
        if len(rollup.label_variants) > 1:
            report.warnings.append(
                f"{rollup.spot_key}: detections carry {len(rollup.label_variants)} "
                f"different spot spellings {rollup.label_variants}, merged into one "
                "spot. Correct if they are the same place typed differently; wrong "
                "if they are not -- spot names are the only cross-system identifier "
                "available (see INDEXING-PLAN 6.3)."
            )
        if rollup.effective_confidence_floor is None:
            report.warnings.append(
                f"{rollup.spot_key}: no min_confidence recorded, so the detection "
                "floor is unknown -- these rows predate the pipeline change"
            )
        elif rollup.heterogeneous_floor:
            report.warnings.append(
                f"{rollup.spot_key}: files processed at differing confidence "
                f"thresholds; effective floor is "
                f"{rollup.effective_confidence_floor}"
            )

    jobs = jobs or []
    verdicts = verdicts or {}
    indices = indices or {}

    if verdicts and pooled_verdicts:
        report.warnings.append(
            "migratory classification came from the pooled, species-level file: "
            "one verdict per species has been applied to every spot. Re-run "
            "migratory_classification to get per-spot results."
        )

    species_by_name = _upsert_species(db, rollups, report)

    spots_by_key: dict[str, Spot] = {}
    for rollup in rollups:
        spot = _upsert_spot(db, project, rollup, coords, report)
        if spot is None:
            continue
        spots_by_key[rollup.spot_key] = spot
        _write_spot_summary(db, spot, rollup)
        _write_spot_species(db, spot, rollup, species_by_name, report)
        _write_daily(db, spot, rollup, species_by_name, report)
        # After the species rows exist, so there is something to annotate.
        _write_migration_class(db, spot, rollup, species_by_name, verdicts, report)
        _write_indices(db, spot, rollup, indices, report)

    _write_jobs(db, project, jobs, spots_by_key, report)

    db.flush()
    return report
