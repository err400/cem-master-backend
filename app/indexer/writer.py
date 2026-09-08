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
import hashlib
from pathlib import Path
import wave

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    AnalysisJob,
    AudioRecording,
    BirdOccurrence,
    Species,
    Spot,
    SpotEnvironmentDaily,
    SpotSource,
    SpotSpeciesDaily,
    SpotSpeciesSummary,
    SpotSummary,
)

from . import rollups as rollup_mod
from .rollups import SpotRollup
from .source import POOLED_SPOT, JobRef, make_geo_key, normalise_spot, share_url


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
    recordings_written: int = 0
    occurrences_written: int = 0
    occurrences_deleted: int = 0
    recordings_deleted: int = 0
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
            f"  recordings       {self.recordings_written} written, "
            f"{self.recordings_deleted} stale removed",
            f"  occurrences      {self.occurrences_written} written, "
            f"{self.occurrences_deleted} stale removed",
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


def prune_project(db: Session, project: str) -> int:
    """Remove one project's rows from the public catalog.

    Used when a project disappears from DATA_DIR or is marked private. Deletes
    child rows explicitly instead of relying on database-specific cascade
    settings, then removes the project's spots and source aliases.
    """
    spot_ids = {
        row[0]
        for row in db.execute(
            select(Spot.id).where(Spot.source_project_id == project)
        ).all()
    }
    spot_ids.update(
        row[0]
        for row in db.execute(
            select(SpotSource.spot_id).where(SpotSource.source_project_id == project)
        ).all()
    )
    if not spot_ids:
        return 0

    ids = sorted(spot_ids)
    db.execute(delete(AnalysisJob).where(AnalysisJob.spot_id.in_(ids)))
    db.execute(delete(BirdOccurrence).where(BirdOccurrence.spot_id.in_(ids)))
    db.execute(delete(AudioRecording).where(AudioRecording.spot_id.in_(ids)))
    db.execute(delete(SpotSpeciesDaily).where(SpotSpeciesDaily.spot_id.in_(ids)))
    db.execute(delete(SpotSpeciesSummary).where(SpotSpeciesSummary.spot_id.in_(ids)))
    db.execute(delete(SpotSummary).where(SpotSummary.spot_id.in_(ids)))
    db.execute(delete(SpotEnvironmentDaily).where(SpotEnvironmentDaily.spot_id.in_(ids)))
    db.execute(delete(SpotSource).where(SpotSource.source_project_id == project))
    removed = db.execute(delete(Spot).where(Spot.source_project_id == project)).rowcount or 0
    return removed


def prune_projects_not_in(db: Session, keep_projects: set[str]) -> dict[str, int]:
    known = {
        row[0]
        for row in db.execute(select(Spot.source_project_id).distinct()).all()
        if row[0]
    }
    known.update(
        row[0]
        for row in db.execute(select(SpotSource.source_project_id).distinct()).all()
        if row[0]
    )
    removed: dict[str, int] = {}
    for project in sorted(known - keep_projects):
        count = prune_project(db, project)
        if count:
            removed[project] = count
    return removed


def _upsert_species(db: Session, rollups: list[SpotRollup], report: IndexReport) -> dict[str, Species]:
    """Ensure a Species row exists for every scientific name seen.

    Keyed on scientific_name, which carries the unique constraint. Common names
    are refreshed but never used as identity -- BirdNET's common names vary and
    two spellings of one bird must not become two species.
    """
    wanted: dict[str, tuple[str, str | None]] = {}
    for rollup in rollups:
        for item in rollup.species:
            if item.scientific_name not in wanted:
                wanted[item.scientific_name] = (item.common_name, item.iucn_category)
            elif wanted[item.scientific_name][1] is None and item.iucn_category is not None:
                wanted[item.scientific_name] = (item.common_name, item.iucn_category)

    if not wanted:
        return {}

    existing = {
        s.scientific_name: s
        for s in db.scalars(
            select(Species).where(Species.scientific_name.in_(wanted))
        ).all()
    }

    for sci_name, (common_name, iucn_val) in wanted.items():
        species = existing.get(sci_name)
        if species is None:
            species = Species(
                scientific_name=sci_name,
                common_name=common_name,
                iucn_category=iucn_val,
            )
            db.add(species)
            existing[sci_name] = species
            report.species_created += 1
        else:
            species.common_name = common_name
            if iucn_val is not None:
                species.iucn_category = iucn_val

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

    Spots are scoped to projects. Every project owns its own spots even if multiple
    projects have spots geotagged at the exact same physical coordinates.
    """
    position = coords.get(rollup.spot_key)
    geo_key = make_geo_key(*position) if position else None

    # Resolve spot strictly within THIS project
    spot = db.scalar(
        select(Spot).where(
            Spot.source_project_id == project,
            Spot.source_spot_id == rollup.spot_key,
        )
    )

    if spot is None:
        if position is None:
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


def _clean_filename(value) -> str:
    return Path(str(value or "")).name.strip()


def _nullable_float(value) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _nullable_int(value) -> int | None:
    try:
        if value is None or pd.isna(value):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _relative_audio_path(project: str, source_spot_id: str, filename: str) -> str:
    return f"projects/{project}/{source_spot_id}/audio/{filename}"


def _make_audio_id(project: str, source_spot_id: str, filename: str) -> str:
    payload = "\0".join([str(project).strip(), str(source_spot_id).strip(), Path(str(filename)).name])
    return "aud_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _source_audio_id(project: str, source_spot_id: str, filename: str, row) -> str:
    value = row.get("audio_id", "")
    existing = "" if pd.isna(value) else str(value or "").strip()
    if existing:
        return existing
    return _make_audio_id(project, source_spot_id, filename)


def _find_audio_file(
    data_dir: Path | None,
    project: str,
    source_spot_id: str,
    filename: str,
) -> Path | None:
    if data_dir is None:
        return None
    project_root = data_dir / "projects" / project
    direct = project_root / source_spot_id / "audio" / filename
    if direct.is_file():
        return direct
    if not project_root.is_dir():
        return None
    for child in project_root.iterdir():
        candidate = child / "audio" / filename
        if child.is_dir() and normalise_spot(child.name) == source_spot_id and candidate.is_file():
            return candidate
    return None


def _wav_metadata(path: Path | None) -> tuple[float | None, int | None]:
    if path is None or path.suffix.lower() != ".wav":
        return None, None
    try:
        with wave.open(str(path), "rb") as audio:
            frames = audio.getnframes()
            rate = audio.getframerate()
            duration = round(frames / rate, 3) if rate else None
            return duration, rate
    except (OSError, EOFError, wave.Error):
        return None, None


def _write_recordings(
    db: Session,
    project: str,
    detections: pd.DataFrame | None,
    spots_by_key: dict[str, Spot],
    species_by_name: dict[str, Species],
    report: IndexReport,
    iucn_cache: dict[str, str] | None = None,
    data_dir: Path | None = None,
) -> None:
    if detections is None or detections.empty:
        return

    public_rows = rollup_mod.prepare(detections, iucn_cache=iucn_cache)
    project_recordings = select(AudioRecording.id).where(AudioRecording.source_project_id == project)
    report.occurrences_deleted += (
        db.execute(
            delete(BirdOccurrence).where(BirdOccurrence.audio_recording_id.in_(project_recordings))
            .execution_options(synchronize_session=False)
        ).rowcount
        or 0
    )

    if public_rows.empty:
        report.recordings_deleted += (
            db.execute(
                delete(AudioRecording).where(AudioRecording.source_project_id == project)
                .execution_options(synchronize_session=False)
            ).rowcount
            or 0
        )
        return

    existing = {
        (row.source_spot_id, row.filename): row
        for row in db.scalars(
            select(AudioRecording).where(AudioRecording.source_project_id == project)
        ).all()
    }
    keep_recording_ids: set[int] = set()

    grouped = public_rows.groupby(["spot_key", "filename"], sort=True, dropna=True)
    for (spot_key, raw_filename), rows in grouped:
        spot = spots_by_key.get(str(spot_key))
        filename = _clean_filename(raw_filename)
        if spot is None or not filename:
            continue

        first = rows.iloc[0]
        path = _find_audio_file(data_dir, project, str(spot_key), filename)
        duration, sample_rate = _wav_metadata(path)
        values = {
            "source_audio_id": _source_audio_id(project, str(spot_key), filename, first),
            "spot_id": spot.id,
            "source_project_id": project,
            "source_spot_id": str(spot_key),
            "filename": filename,
            "relative_path": _relative_audio_path(project, str(spot_key), filename),
            "recorded_date": first.get("observation_date"),
            "hour": _nullable_int(first.get("hour")),
            "minute": _nullable_int(first.get("minute")),
            "second": _nullable_int(first.get("second")),
            "duration_seconds": duration,
            "sample_rate": sample_rate,
        }
        recording = existing.get((str(spot_key), filename))
        if recording is None:
            recording = AudioRecording(**values)
            db.add(recording)
            db.flush()
        else:
            for key, value in values.items():
                setattr(recording, key, value)
        keep_recording_ids.add(recording.id)
        report.recordings_written += 1

        for _, detection in rows.iterrows():
            species = species_by_name.get(str(detection.get("scientific_name")))
            if species is None:
                continue
            db.add(
                BirdOccurrence(
                    audio_recording_id=recording.id,
                    spot_id=spot.id,
                    species_id=species.id,
                    confidence=_nullable_float(detection.get("confidence")),
                    start_time_seconds=_nullable_float(detection.get("start_time")),
                    end_time_seconds=_nullable_float(detection.get("end_time")),
                )
            )
            report.occurrences_written += 1

    stale = delete(AudioRecording).where(AudioRecording.source_project_id == project)
    if keep_recording_ids:
        stale = stale.where(AudioRecording.id.not_in(keep_recording_ids))
    report.recordings_deleted += db.execute(
        stale.execution_options(synchronize_session=False)
    ).rowcount or 0


def _primary_output_name(outputs: list) -> str | None:
    """The one output file worth naming in a single-line table cell.

    A step writes a CSV of results plus several PNG plots. The CSV is the
    result; the plots are a rendering of it. So prefer a CSV, then any
    non-image, and only fall back to an image if that is genuinely all there
    is. Ties break on shortest name -- arbitrary but deterministic, which is
    what matters: the same job must not name a different file on each pass.

    This is a label, not a claim about which file the reader wants. The full
    list is kept in ``job_metadata["outputs"]``, and ``output_url`` links the
    whole directory, so nothing is hidden by choosing badly here.
    """
    if not outputs:
        return None
    names = [p.name for p in outputs]

    # A run log is not a result. It was being surfaced as the output of every
    # birdnet job, which is both wrong and a small disclosure -- pipeline logs
    # carry absolute server paths. STAC sidecars are metadata ABOUT an output,
    # so they lose to the file they describe.
    substantive = [
        n for n in names
        if not n.endswith(".stac.json")
        and not n.lower().endswith((".log", ".err"))
        and not n.startswith("_")
    ]
    names = substantive or names

    for predicate in (
        lambda n: n.lower().endswith(".csv"),
        lambda n: not n.lower().endswith((".png", ".jpg", ".jpeg", ".svg")),
        lambda n: True,
    ):
        matches = [n for n in names if predicate(n)]
        if matches:
            return min(matches, key=lambda n: (len(n), n))
    return None


def _write_jobs(
    db: Session,
    project: str,
    jobs: list[JobRef],
    spots_by_key: dict[str, Spot],
    report: IndexReport,
    filebrowser_url: str = "",
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

        # --- what the UI's "Analysis jobs" table shows per row ---------------
        #
        # The compute app already created a FileBrowser share for this step's
        # output directory when the analysis finished, and recorded its hash in
        # job.json. We turn that into a link; we never create or revoke one.
        #
        # The share points at the DIRECTORY, so the link opens the job's whole
        # result set rather than a single file. output_file names the most
        # useful file in it so the row is meaningful even without the link.
        output_url = share_url(filebrowser_url, job.primary_share())
        output_file = _primary_output_name(outputs)

        # Inputs have no share of their own -- the compute app only shares
        # results -- so input_url stays None and the input is described rather
        # than linked. input/aggregate.csv is the detection table the run
        # started from, which is the honest answer to "what went in".
        consumed = job.input_files()
        has_input_aggregate = (job.root / "input" / "aggregate.csv").is_file()
        if has_input_aggregate and consumed:
            input_file = f"aggregate.csv + {len(consumed)} recording(s)"
        elif consumed:
            input_file = f"{len(consumed)} recording(s)"
        elif has_input_aggregate:
            input_file = "aggregate.csv"
        else:
            input_file = None

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
                # A DATA_DIR path must never reach the browser -- it is
                # meaningless there and discloses the server's layout. Only a
                # FileBrowser share link ever goes out, and only one the compute
                # app already published.
                "input_url": None,
                "output_url": output_url,
                "job_metadata": {
                    "job_id": job.job_id,
                    "project": project,
                    "spots": spot_keys,
                    "parameters": facts["params"],
                    "date_start": meta.get("start_date"),
                    "date_end": meta.get("end_date"),
                    # The read API surfaces these two as the table's file
                    # columns; the full lists stay here for anything that wants
                    # detail without another round trip.
                    "input_file": input_file,
                    "output_file": output_file,
                    "input_files": consumed,
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
    detections: pd.DataFrame | None = None,
    iucn_cache: dict[str, str] | None = None,
    data_dir: Path | None = None,
    jobs: list[JobRef] | None = None,
    verdicts: dict[tuple[str, str], dict] | None = None,
    indices: dict[str, dict] | None = None,
    pooled_verdicts: bool = False,
    filebrowser_url: str = "",
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

    _write_recordings(
        db,
        project,
        detections,
        spots_by_key,
        species_by_name,
        report,
        iucn_cache=iucn_cache,
        data_dir=data_dir,
    )
    _write_jobs(db, project, jobs, spots_by_key, report, filebrowser_url)

    db.flush()
    return report
