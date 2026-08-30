"""The three properties an indexer can silently violate.

These need PostgreSQL (see conftest). They are separate from the rollup tests
because these check the *writing*, not the arithmetic -- and writing is where
"looks fine, is wrong" lives:

1. idempotency  -- index twice, get identical rows (not doubled counts)
2. the delete pass -- remove a species from the source, its row must disappear
3. scoping      -- indexing one project never touches another's rows

Each is a bug that produces a perfectly plausible public page.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.database import Base, SessionLocal, engine
from app.indexer import rollups, source
from app.indexer.writer import write
from app.models import (
    AnalysisJob,
    Species,
    Spot,
    SpotSource,
    SpotSpeciesDaily,
    SpotSpeciesSummary,
    SpotSummary,
)
from tests.fixtures import build_fixture

PROJECT = "fixture-demo"


@pytest.fixture()
def clean_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield
    finally:
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    return build_fixture.build(tmp_path / "data_dir")


FILEBROWSER_URL = "http://localhost:8097"


def _index(data_dir: Path, project: str = PROJECT, filebrowser_url: str = FILEBROWSER_URL):
    """Run one full pass, exactly as the CLI does."""
    with SessionLocal() as db:
        df = source.read_aggregate(data_dir, project)
        coords = source.read_geo(data_dir, project)
        audio = source.count_audio_files(data_dir, project)
        jobs = source.list_jobs(data_dir, project)
        verdicts, pooled = source.read_migratory(data_dir, project)
        indices = source.read_acoustic_indices(data_dir, project)
        report = write(
            db,
            project,
            rollups.build(df, audio_counts=audio),
            coords,
            jobs=jobs,
            verdicts=verdicts,
            indices=indices,
            pooled_verdicts=pooled,
            filebrowser_url=filebrowser_url,
        )
        db.commit()
        return report


def _snapshot() -> dict:
    """Everything the indexer wrote, in a comparable form."""
    with SessionLocal() as db:
        return {
            "spots": sorted(
                (s.source_project_id, s.source_spot_id, s.name, s.latitude, s.longitude)
                for s in db.scalars(select(Spot)).all()
            ),
            "summaries": sorted(
                (s.spot_id, s.species_richness, s.total_detections,
                 s.active_days, s.recording_count)
                for s in db.scalars(select(SpotSummary)).all()
            ),
            "species_rows": sorted(
                (r.spot_id, r.species_id, r.detection_count, r.active_days,
                 r.activity_rank, tuple(r.hourly_counts or []))
                for r in db.scalars(select(SpotSpeciesSummary)).all()
            ),
            "daily": sorted(
                (d.spot_id, d.species_id, d.observation_date.isoformat(), d.detection_count)
                for d in db.scalars(select(SpotSpeciesDaily)).all()
            ),
        }


# ------------------------------------------------------------ first pass -----

def test_first_pass_writes_expected_rows(clean_db, data_dir: Path) -> None:
    report = _index(data_dir)

    assert report.spots_seen == 2
    assert report.spots_created == 2
    assert report.species_created == 3
    assert report.species_rows_written == 4      # 2 species at each of 2 spots
    assert report.daily_rows_written == 7        # 4 at site_a + 3 at site_b
    assert report.spots_without_coordinates == []

    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Spot)) == 2
        assert db.scalar(select(func.count()).select_from(Species)) == 3
        assert db.scalar(select(func.count()).select_from(SpotSource)) == 2

        site_a = db.scalar(select(Spot).where(Spot.source_spot_id == "site_a"))
        # Coordinates came from geo.json, where the spot is spelled SITE_A.
        assert (site_a.latitude, site_a.longitude) == (28.5410, 77.1695)

        summary = db.get(SpotSummary, site_a.id)
        assert (summary.species_richness, summary.total_detections) == (2, 13)
        assert (summary.active_days, summary.recording_count) == (2, 4)


def test_hourly_counts_survive_the_round_trip(clean_db, data_dir: Path) -> None:
    """JSONB must return 24 plain numbers -- the frontend indexes by hour."""
    _index(data_dir)
    with SessionLocal() as db:
        peafowl = db.scalar(select(Species).where(Species.common_name == "Indian Peafowl"))
        site_a = db.scalar(select(Spot).where(Spot.source_spot_id == "site_a"))
        row = db.scalar(
            select(SpotSpeciesSummary).where(
                SpotSpeciesSummary.spot_id == site_a.id,
                SpotSpeciesSummary.species_id == peafowl.id,
            )
        )
        assert len(row.hourly_counts) == 24
        assert row.hourly_counts[6] == 6 and row.hourly_counts[17] == 2
        assert sum(row.hourly_counts) == row.detection_count == 8
        assert row.daily_counts[0] == {"date": "2026-04-10", "count": 5}
        assert row.monthly_counts == [{"month": "2026-04", "count": 8}]


# ----------------------------------------------------------- idempotency -----

def test_indexing_twice_changes_nothing(clean_db, data_dir: Path) -> None:
    """The property that makes re-running safe.

    If any value were incremented rather than replaced, the second pass would
    double it -- and the page would look entirely believable.
    """
    _index(data_dir)
    first = _snapshot()

    second_report = _index(data_dir)
    second = _snapshot()

    assert first == second, "a second pass changed the data"
    assert second_report.spots_created == 0
    assert second_report.species_created == 0
    assert second_report.species_rows_deleted == 0


def test_three_passes_still_identical(clean_db, data_dir: Path) -> None:
    _index(data_dir)
    _index(data_dir)
    snapshot = _snapshot()
    _index(data_dir)
    assert _snapshot() == snapshot


# --------------------------------------------------------- the delete pass ---

def _rewrite_aggregate_without(data_dir: Path, common_name: str) -> None:
    path = data_dir / "projects" / PROJECT / "dataset" / "aggregate.csv"
    with path.open() as fh:
        rows = list(csv.DictReader(fh))
    kept = [r for r in rows if r["common_name"] != common_name]
    assert len(kept) < len(rows), "fixture changed; nothing was removed"
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(kept)


def test_species_that_vanishes_is_removed(clean_db, data_dir: Path) -> None:
    """Upsert alone cannot do this, which is why the delete pass exists.

    Without it the bird stays on the public page forever and nothing errors.
    """
    _index(data_dir)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(SpotSpeciesSummary)) == 4

    # Hume's Warbler occurs at site_b only. Remove it from the source entirely.
    _rewrite_aggregate_without(data_dir, "Hume's Warbler")
    report = _index(data_dir)

    assert report.species_rows_deleted == 1
    with SessionLocal() as db:
        warbler = db.scalar(select(Species).where(Species.common_name == "Hume's Warbler"))
        # The species row itself is kept -- it may still exist at other spots, and
        # deleting it would break search history. Only the association goes.
        assert warbler is not None
        assert db.scalar(
            select(func.count()).select_from(SpotSpeciesSummary)
            .where(SpotSpeciesSummary.species_id == warbler.id)
        ) == 0
        assert db.scalar(
            select(func.count()).select_from(SpotSpeciesDaily)
            .where(SpotSpeciesDaily.species_id == warbler.id)
        ) == 0

        site_b = db.scalar(select(Spot).where(Spot.source_spot_id == "site_b"))
        summary = db.get(SpotSummary, site_b.id)
        assert summary.species_richness == 1, "richness must fall with the species"
        assert summary.total_detections == 3


def test_removing_all_detections_for_a_spot_clears_its_rows(clean_db, data_dir: Path) -> None:
    """The empty-keep-set branch of the delete pass."""
    _index(data_dir)
    _rewrite_aggregate_without(data_dir, "Hume's Warbler")
    _rewrite_aggregate_without(data_dir, "Indian Peafowl")
    _index(data_dir)

    with SessionLocal() as db:
        site_b = db.scalar(select(Spot).where(Spot.source_spot_id == "site_b"))
        # site_b had only warbler + peafowl, so nothing should remain for it.
        assert db.scalar(
            select(func.count()).select_from(SpotSpeciesSummary)
            .where(SpotSpeciesSummary.spot_id == site_b.id)
        ) == 0


# --------------------------------------------------------------- scoping -----

def test_indexing_one_project_leaves_another_alone(clean_db, tmp_path: Path) -> None:
    """Deletes are scoped by project, so seeded and indexed data can coexist."""
    data_dir = build_fixture.build(tmp_path / "data_dir")
    _index(data_dir)

    with SessionLocal() as db:
        other = Spot(
            source_project_id="some-other-project",
            source_spot_id="x1",
            name="Untouched",
            latitude=1.0,
            longitude=2.0,
        )
        db.add(other)
        db.flush()
        db.add(SpotSummary(spot_id=other.id, species_richness=99, total_detections=999))
        db.commit()
        other_id = other.id

    _rewrite_aggregate_without(data_dir, "Hume's Warbler")
    _index(data_dir)

    with SessionLocal() as db:
        survivor = db.get(SpotSummary, other_id)
        assert survivor is not None
        assert (survivor.species_richness, survivor.total_detections) == (99, 999)


# ---------------------------------------------------- missing coordinates ----

def test_spot_without_coordinates_is_reported_not_invented(clean_db, data_dir: Path) -> None:
    """A spot with no geo.json cannot be placed on a map.

    It must be reported rather than written at 0,0 -- an invented position on a
    public ecological map is worse than an absent one.
    """
    for geo in (data_dir / "projects" / PROJECT).rglob("geo.json"):
        geo.unlink()

    report = _index(data_dir)

    assert sorted(report.spots_without_coordinates) == ["site_a", "site_b"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Spot)) == 0


# ----------------------------------------------------- spot identity ---------

def _rename_spot(data_dir: Path, old: str, new: str) -> None:
    """Rename a spot the way the compute app would.

    NEW detections carry the new name; historical rows keep the old one, because
    the aggregate is append-only and never rewritten. geo.json holds only the
    current name. That asymmetry is the whole difficulty.
    """
    import json

    agg = data_dir / "projects" / PROJECT / "dataset" / "aggregate.csv"
    rows = list(csv.DictReader(agg.open()))
    for row in rows[-4:]:                       # only the most recent detections
        if row["spot"] == old:
            row["spot"] = new
    with agg.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    geo = (
        data_dir / "projects" / PROJECT / "birdnet" / "job-0001" / "input" / "geo.json"
    )
    entries = json.loads(geo.read_text())
    for entry in entries:
        if entry["name"].casefold() == old.casefold():
            entry["name"] = new.upper()
    geo.write_text(json.dumps(entries, indent=2))


def test_geo_key_is_set_and_stable(clean_db, data_dir: Path) -> None:
    _index(data_dir)
    with SessionLocal() as db:
        site_a = db.scalar(select(Spot).where(Spot.source_spot_id == "site_a"))
        assert site_a.geo_key == "28.54100:77.16950"

    _index(data_dir)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Spot)) == 2


def test_rename_updates_the_spot_instead_of_forking_it(clean_db, data_dir: Path) -> None:
    """The reason geo_key exists.

    Renaming does not move the recorder, so the location key is unchanged and the
    existing row is found. Without it the indexer sees an unknown name, tries to
    create a second spot at the same coordinates, and the two rows compete.
    """
    _index(data_dir)
    with SessionLocal() as db:
        original_id = db.scalar(select(Spot).where(Spot.source_spot_id == "site_a")).id

    _rename_spot(data_dir, "site_a", "north_ridge")
    report = _index(data_dir)

    assert any("rename" in w for w in report.warnings)
    assert report.spot_aliases_added == 1

    with SessionLocal() as db:
        # Still ONE spot, not two.
        assert db.scalar(select(func.count()).select_from(Spot)) == 2
        spot = db.get(Spot, original_id)
        assert spot is not None, "the original row survived"

        # Both names now resolve to it, so historical detections are not orphaned.
        names = {
            s.source_spot_id
            for s in db.scalars(
                select(SpotSource).where(SpotSource.spot_id == original_id)
            ).all()
        }
        assert names == {"site_a", "north_ridge"}


def test_a_spot_moved_far_enough_is_a_different_place(clean_db, data_dir: Path) -> None:
    """The tolerance cuts both ways, and that is intended.

    ~1.1 m absorbs GPS jitter. A recorder genuinely relocated produces a
    different key and therefore a different spot -- which is correct, and the
    reason the precision is a named constant rather than a magic number.
    """
    import json

    _index(data_dir)
    geo = (
        data_dir / "projects" / PROJECT / "birdnet" / "job-0001" / "input" / "geo.json"
    )
    entries = json.loads(geo.read_text())
    for entry in entries:
        if entry["name"] == "SITE_A":
            entry["lat"] += 0.01          # ~1.1 km
    geo.write_text(json.dumps(entries, indent=2))

    _index(data_dir)
    with SessionLocal() as db:
        # Resolved by name first, so it is the same row -- moved, not duplicated.
        site_a = db.scalar(select(Spot).where(Spot.source_spot_id == "site_a"))
        assert site_a.geo_key == "28.55100:77.16950"


# ------------------------------------------------------------- pass B --------

def test_migration_class_is_per_spot(clean_db, data_dir: Path) -> None:
    """The whole point of the pipeline fix.

    Indian Peafowl is Resident at site_a and Unknown at site_b -- a distinction
    the pooled, species-level file cannot express, because it produces one
    verdict per species across every spot in the run.
    """
    _index(data_dir)
    with SessionLocal() as db:
        peafowl = db.scalar(select(Species).where(Species.common_name == "Indian Peafowl"))

        def verdict(spot_key: str) -> str | None:
            spot = db.scalar(select(Spot).where(Spot.source_spot_id == spot_key))
            row = db.scalar(
                select(SpotSpeciesSummary).where(
                    SpotSpeciesSummary.spot_id == spot.id,
                    SpotSpeciesSummary.species_id == peafowl.id,
                )
            )
            return row.migration_class

        assert verdict("site_a") == "Resident"
        assert verdict("site_b") == "Unknown", "3 detections is too few to judge"


def test_migration_metrics_accompany_the_verdict(clean_db, data_dir: Path) -> None:
    """A reader should be able to see WHY a bird was classified, not just that."""
    _index(data_dir)
    with SessionLocal() as db:
        warbler = db.scalar(select(Species).where(Species.common_name == "Hume's Warbler"))
        site_b = db.scalar(select(Spot).where(Spot.source_spot_id == "site_b"))
        row = db.scalar(
            select(SpotSpeciesSummary).where(
                SpotSpeciesSummary.spot_id == site_b.id,
                SpotSpeciesSummary.species_id == warbler.id,
            )
        )
        assert row.migration_class == "Migratory"
        assert row.analysis_metrics["sci"] == 0.98
        assert row.analysis_metrics["pmr"] == 6.10


def test_acoustic_indices_land_on_the_spot(clean_db, data_dir: Path) -> None:
    _index(data_dir)
    with SessionLocal() as db:
        site_a = db.scalar(select(Spot).where(Spot.source_spot_id == "site_a"))
        indices = db.get(SpotSummary, site_a.id).acoustic_indices
        assert indices["ACI"] == 0.51 and indices["NDSI"] == 0.40
        # Unknown keys pass straight through, so a new index in the pipeline
        # appears without a code change here.
        assert indices["BI"] == 12.3


def test_multi_spot_jobs_get_one_row_per_spot(clean_db, data_dir: Path) -> None:
    """Working around analysis_jobs not supporting multi-spot runs.

    job_id is the primary key and spot_id is a single column, so a run covering
    two spots is stored as two composite-keyed rows until job_spots exists.
    """
    report = _index(data_dir)
    # 3 jobs x 2 spots each
    assert report.jobs_written == 6

    with SessionLocal() as db:
        rows = db.scalars(select(AnalysisJob)).all()
        assert len(rows) == 6
        assert {r.job_id for r in rows} == {
            f"{job}#{spot}"
            for job in ("job-0001", "job-0002", "job-0003")
            for spot in ("site_a", "site_b")
        }
        # The real job id survives, so collapsing these later is mechanical.
        birdnet = next(r for r in rows if r.analysis_type == "birdnet")
        assert birdnet.job_metadata["job_id"] == "job-0001"
        assert birdnet.job_metadata["parameters"]["min_confidence"] == "0.25"
        # status and timings are derived from tasks[], not the job root
        assert birdnet.started_at is not None and birdnet.completed_at is not None
        assert birdnet.status == "completed"

        # Local DATA_DIR paths must never reach the browser. Only FileBrowser
        # share links go out, and inputs have no share, so input_url stays null.
        assert all(r.input_url is None for r in rows)
        assert all(
            r.output_url is None or r.output_url.startswith(FILEBROWSER_URL)
            for r in rows
        ), "no DATA_DIR path may leak into output_url"
        assert "birdnet_results.csv" in birdnet.job_metadata["outputs"]


# --- job artifact links ---------------------------------------------------
#
# The compute app already creates a FileBrowser share per step and records its
# hash in job.json. The indexer's job is only to turn those into URLs the
# frontend's "Analysis jobs" table can render -- never to create or revoke one.


def test_output_url_comes_from_the_recorded_share(clean_db, data_dir: Path) -> None:
    _index(data_dir)
    with SessionLocal() as db:
        birdnet = db.scalars(
            select(AnalysisJob).where(AnalysisJob.analysis_type == "birdnet")
        ).first()
        assert birdnet.output_url == f"{FILEBROWSER_URL}/share/aBcD1234"


def test_a_job_without_a_share_is_named_but_not_linked(clean_db, data_dir: Path) -> None:
    """FileBrowser is optional on the compute side, so this is the normal case
    today. The row must still be useful: a named output, and no dead link."""
    _index(data_dir)
    with SessionLocal() as db:
        job = db.scalars(
            select(AnalysisJob).where(AnalysisJob.analysis_type == "acoustic_indices")
        ).first()
        assert job.output_url is None
        assert job.job_metadata["output_file"] == "acoustic_indices_summary.csv"


def test_no_links_at_all_when_filebrowser_is_unconfigured(clean_db, data_dir: Path) -> None:
    """A blank base URL must yield null, not 'None/share/x' or '/share/x'."""
    _index(data_dir, filebrowser_url="")
    with SessionLocal() as db:
        rows = db.scalars(select(AnalysisJob)).all()
        assert rows and all(r.output_url is None for r in rows)


def test_expired_shares_are_not_published(clean_db, data_dir: Path) -> None:
    """A share past its expire 404s. Publishing it would be worse than
    publishing nothing, because the row asserts the artifact is reachable."""
    import json
    import time

    job_json = data_dir / "projects" / PROJECT / "birdnet" / "job-0001" / "job.json"
    meta = json.loads(job_json.read_text())
    meta["shares"]["birdnet"]["expire"] = time.time() - 3600
    job_json.write_text(json.dumps(meta))

    _index(data_dir)
    with SessionLocal() as db:
        birdnet = db.scalars(
            select(AnalysisJob).where(AnalysisJob.analysis_type == "birdnet")
        ).first()
        assert birdnet.output_url is None


def test_input_is_described_since_it_has_no_share(clean_db, data_dir: Path) -> None:
    _index(data_dir)
    with SessionLocal() as db:
        birdnet = db.scalars(
            select(AnalysisJob).where(AnalysisJob.analysis_type == "birdnet")
        ).first()
        # 7 recordings, not 24 -- the fixture's 24 rows are DETECTIONS, and
        # audio_spots.json is keyed by file. Counting rows here would have
        # reported the wrong thing in a way nobody would notice on the UI.
        assert birdnet.job_metadata["input_file"] == "aggregate.csv + 7 recording(s)"
        assert len(birdnet.job_metadata["input_files"]) == 7
        assert birdnet.input_url is None


def test_the_api_reads_the_keys_the_indexer_writes(clean_db, data_dir: Path) -> None:
    """Guards the seam that was broken: the writer stored a plural `outputs`
    list while routes/dashboard.py read singular `input_file`/`output_file`,
    so all four columns rendered blank."""
    _index(data_dir)
    with SessionLocal() as db:
        for row in db.scalars(select(AnalysisJob)).all():
            assert "input_file" in row.job_metadata
            assert "output_file" in row.job_metadata


def test_jobs_are_idempotent_and_swept(clean_db, data_dir: Path) -> None:
    _index(data_dir)
    second = _index(data_dir)
    assert second.jobs_deleted == 0

    # Remove a job folder, as retention would after 7 days.
    import shutil
    shutil.rmtree(data_dir / "projects" / PROJECT / "acoustic_indices")

    third = _index(data_dir)
    assert third.jobs_deleted == 2, "the removed job's rows should go"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AnalysisJob)) == 4


def test_pooled_verdicts_are_flagged(clean_db, data_dir: Path) -> None:
    """Falling back to the species-level file is a weaker claim, and says so."""
    by_spot = (
        data_dir / "projects" / PROJECT / "migratory_classification" / "job-0002"
        / "results" / "migratory_classification"
        / "migratory_classification_by_spot.csv"
    )
    by_spot.unlink()

    report = _index(data_dir)
    assert any("pooled" in w for w in report.warnings)

    with SessionLocal() as db:
        peafowl = db.scalar(select(Species).where(Species.common_name == "Indian Peafowl"))
        # Now the SAME verdict is applied at both spots -- which is exactly the
        # imprecision the warning exists to announce.
        verdicts = {
            db.get(Spot, r.spot_id).source_spot_id: r.migration_class
            for r in db.scalars(
                select(SpotSpeciesSummary).where(
                    SpotSpeciesSummary.species_id == peafowl.id
                )
            ).all()
        }
        assert verdicts == {"site_a": "Resident", "site_b": "Resident"}


def test_coordinates_are_not_blanked_when_geo_json_disappears(clean_db, data_dir: Path) -> None:
    """Retention deletes job folders after ~7 days, taking geo.json with them.

    Once captured, the database is the durable record; a later pass finding no
    geo.json must leave the stored position alone.
    """
    _index(data_dir)
    for geo in (data_dir / "projects" / PROJECT).rglob("geo.json"):
        geo.unlink()

    _index(data_dir)

    with SessionLocal() as db:
        site_a = db.scalar(select(Spot).where(Spot.source_spot_id == "site_a"))
        assert (site_a.latitude, site_a.longitude) == (28.5410, 77.1695)
