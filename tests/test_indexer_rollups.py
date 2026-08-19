"""Rollup arithmetic, asserted against hand-counted fixture values.

No database and no app import, so these run anywhere -- including without
PostgreSQL. That matters: the rollups are where a wrong number would come from,
and they should be the cheapest thing in the suite to check.

Every expected value below was worked out by hand from the 24 detections in
tests/fixtures/build_fixture.py. If one of these fails, the arithmetic changed --
go and re-derive it rather than adjusting the expectation to match the code.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.indexer import rollups, source  # noqa: E402
from tests.fixtures import build_fixture  # noqa: E402

PROJECT = "fixture-demo"


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory) -> Path:
    """A freshly built fixture DATA_DIR, isolated per test run."""
    return build_fixture.build(tmp_path_factory.mktemp("data_dir"))


@pytest.fixture(scope="module")
def built(data_dir: Path) -> dict[str, rollups.SpotRollup]:
    df = source.read_aggregate(data_dir, PROJECT)
    audio = source.count_audio_files(data_dir, PROJECT)
    return {r.spot_key: r for r in rollups.build(df, audio_counts=audio)}


# ---------------------------------------------------------------- reading ----

def test_aggregate_has_expected_shape(data_dir: Path) -> None:
    df = source.read_aggregate(data_dir, PROJECT)
    assert len(df) == 24
    assert source.REQUIRED_AGGREGATE_COLUMNS <= set(df.columns)
    assert "min_confidence" in df.columns, "the pipeline change should be reflected"


def test_missing_aggregate_is_empty_not_an_error(tmp_path: Path) -> None:
    """A project whose analysis has not run yet is a normal state."""
    (tmp_path / "projects" / "brand-new").mkdir(parents=True)
    assert source.read_aggregate(tmp_path, "brand-new").empty


def test_malformed_aggregate_raises(tmp_path: Path) -> None:
    """A file we cannot trust must fail loudly, not index partial nonsense."""
    dataset = tmp_path / "projects" / "broken" / "dataset"
    dataset.mkdir(parents=True)
    (dataset / "aggregate.csv").write_text("only,two\ncolumns,here\n")
    with pytest.raises(source.SourceError, match="missing required columns"):
        source.read_aggregate(tmp_path, "broken")


def test_project_name_cannot_escape_the_projects_dir(tmp_path: Path) -> None:
    (tmp_path / "projects").mkdir()
    with pytest.raises(source.SourceError, match="escapes"):
        source.read_aggregate(tmp_path, "../../etc")


# ------------------------------------------------------------ coordinates ----

def test_geo_json_is_found_and_normalised(data_dir: Path) -> None:
    """geo.json says SITE_A, the aggregate says site_a. Both must resolve."""
    coords = source.read_geo(data_dir, PROJECT)
    assert coords == {
        "site_a": (28.5410, 77.1695),
        "site_b": (28.5388, 77.1902),
    }


def test_every_spot_in_the_aggregate_has_coordinates(data_dir: Path) -> None:
    df = source.read_aggregate(data_dir, PROJECT)
    coords = source.read_geo(data_dir, PROJECT)
    unplaceable = {
        source.normalise_spot(s)
        for s in df["spot"].unique()
        if source.normalise_spot(s) not in coords
    }
    assert not unplaceable, f"spots with no coordinates: {unplaceable}"


def test_normalise_spot_folds_case_and_removes_whitespace() -> None:
    # The frontend sends name.replace(/\s+/g,'').toUpperCase(); the aggregate is
    # lowercased. "Site A" must match "SITEA".
    assert source.normalise_spot("Site A") == source.normalise_spot("SITEA")
    assert source.normalise_spot("  site_a  ") == "site_a"


# ------------------------------------------------------------------ jobs -----

def test_jobs_are_found_and_spots_are_not_mistaken_for_them(data_dir: Path) -> None:
    jobs = source.list_jobs(data_dir, PROJECT)
    assert {(j.script, j.job_id) for j in jobs} == {
        ("birdnet", "job-0001"),
        ("migratory_classification", "job-0002"),
        ("acoustic_indices", "job-0003"),
    }
    assert jobs[0].read_meta().get("project") == PROJECT
    # Spot directories contain audio/, not job.json, so they are not mistaken
    # for scripts -- which is why this checks the set exactly.
    assert all(j.spot_keys() == ["site_a", "site_b"] for j in jobs)


def test_migratory_verdicts_are_read_per_spot(data_dir: Path) -> None:
    verdicts, pooled = source.read_migratory(data_dir, PROJECT)
    assert pooled is False, "the by-spot file should be preferred"
    assert verdicts[("site_a", "Indian Peafowl")]["Classification"] == "Resident"
    assert verdicts[("site_b", "Indian Peafowl")]["Classification"] == "Unknown"
    assert verdicts[("site_b", "Hume's Warbler")]["Classification"] == "Migratory"


def test_pooled_migratory_file_is_used_as_a_fallback(data_dir: Path) -> None:
    by_spot = (
        data_dir / "projects" / PROJECT / "migratory_classification" / "job-0002"
        / "results" / "migratory_classification"
        / "migratory_classification_by_spot.csv"
    )
    by_spot.unlink()
    verdicts, pooled = source.read_migratory(data_dir, PROJECT)
    assert pooled is True
    assert verdicts[(source.POOLED_SPOT, "Indian Peafowl")]["Classification"] == "Resident"


def test_acoustic_indices_are_read_per_spot(data_dir: Path) -> None:
    indices = source.read_acoustic_indices(data_dir, PROJECT)
    assert indices["site_a"]["ACI"] == 0.51
    assert indices["site_b"]["NDSI"] == 0.35


# --------------------------------------------------------------- rollups -----

def test_spot_a_totals(built) -> None:
    # 13 detections = peafowl 8 (5 on 04-10, 3 on 04-11) + tailorbird 5 (2, 3)
    r = built["site_a"]
    assert r.species_richness == 2
    assert r.total_detections == 13
    assert r.active_days == 2
    assert r.recording_count == 4          # from the audio directory
    assert str(r.first_recording_date) == "2026-04-10"
    assert str(r.last_recording_date) == "2026-04-11"


def test_spot_b_totals(built) -> None:
    # 11 detections = warbler 8 (6 on 04-10, 2 on 04-11) + peafowl 3 (04-10 only)
    r = built["site_b"]
    assert r.species_richness == 2
    assert r.total_detections == 11
    assert r.active_days == 2
    assert r.recording_count == 3


def test_totals_reconcile_with_a_direct_count(data_dir: Path, built) -> None:
    """The rollups must agree with counting the CSV directly.

    The point of the indexer is that nobody has to do this at request time -- so
    something has to check that the precomputed answer is the same one.
    """
    df = source.read_aggregate(data_dir, PROJECT)
    direct = df.groupby(df["spot"].map(source.normalise_spot))
    for spot_key, group in direct:
        assert built[spot_key].total_detections == len(group)
        assert built[spot_key].species_richness == group["scientific_name"].nunique()
        assert built[spot_key].active_days == group["date"].nunique()


def test_activity_rank_is_by_detection_count(built) -> None:
    a = {s.common_name: s.activity_rank for s in built["site_a"].species}
    assert a == {"Indian Peafowl": 1, "Common Tailorbird": 2}
    b = {s.common_name: s.activity_rank for s in built["site_b"].species}
    assert b == {"Hume's Warbler": 1, "Indian Peafowl": 2}


def test_per_species_detail(built) -> None:
    peafowl = next(s for s in built["site_a"].species if s.common_name == "Indian Peafowl")
    assert peafowl.detection_count == 8
    assert peafowl.active_days == 2
    assert peafowl.maximum_confidence == 0.90
    assert str(peafowl.first_detection_date) == "2026-04-10"
    assert str(peafowl.last_detection_date) == "2026-04-11"

    # Peafowl at site_b appears on ONE day only -- the asymmetry the fixture
    # exists to create, and what makes species-at-spot stats meaningful.
    at_b = next(s for s in built["site_b"].species if s.common_name == "Indian Peafowl")
    assert at_b.detection_count == 3
    assert at_b.active_days == 1


def test_hourly_counts_contract(built) -> None:
    """24 numbers, indexed by hour. The frontend chart depends on exactly this."""
    for rollup in built.values():
        for item in rollup.species:
            assert len(item.hourly_counts) == 24
            assert all(isinstance(c, int) for c in item.hourly_counts), "never null"

    peafowl = next(s for s in built["site_a"].species if s.common_name == "Indian Peafowl")
    assert peafowl.hourly_counts[6] == 6     # 3 on 04-10 + 3 on 04-11
    assert peafowl.hourly_counts[17] == 2    # both on 04-10
    assert sum(peafowl.hourly_counts) == peafowl.detection_count


def test_daily_counts_are_chronological_pairs(built) -> None:
    warbler = next(s for s in built["site_b"].species if s.common_name == "Hume's Warbler")
    assert warbler.daily_counts == [
        {"date": "2026-04-10", "count": 6},
        {"date": "2026-04-11", "count": 2},
    ]
    dates = [row["date"] for row in warbler.daily_counts]
    assert dates == sorted(dates), "the frontend uses first/last as axis labels"


def test_monthly_counts_use_sortable_keys() -> None:
    """YYYY-MM so a December/January boundary orders correctly."""
    df = pd.DataFrame({
        "spot": ["site_a"] * 3,
        "date": ["2025-12-30", "2026-01-02", "2025-12-31"],
        "hour": [6, 6, 6],
        "scientific_name": ["Pavo cristatus"] * 3,
        "common_name": ["Indian Peafowl"] * 3,
        "confidence": [0.5, 0.6, 0.7],
        "filename": ["a.wav", "b.wav", "c.wav"],
    })
    item = rollups.build(df)[0].species[0]
    assert item.monthly_counts == [
        {"month": "2025-12", "count": 2},
        {"month": "2026-01", "count": 1},
    ]


def test_daily_grain_row_count(built) -> None:
    # site_a: peafowl on 2 dates + tailorbird on 2 dates = 4
    # site_b: warbler on 2 dates + peafowl on 1 date   = 3
    assert len(built["site_a"].daily) == 4
    assert len(built["site_b"].daily) == 3


# ------------------------------------------------------- confidence floor ----

def test_uniform_floor_is_not_flagged(built) -> None:
    for rollup in built.values():
        assert rollup.effective_confidence_floor == 0.25
        assert rollup.heterogeneous_floor is False


def test_mixed_floors_take_the_maximum_and_flag_it() -> None:
    """A spot whose files were processed at different thresholds is biased.

    Reporting at 0.25 would imply the 0.40 files could have contributed rows
    between 0.25 and 0.40, which they never could. So the effective floor is the
    maximum, and the mismatch is flagged.
    """
    df = pd.DataFrame({
        "spot": ["site_a"] * 4,
        "date": ["2026-04-10"] * 4,
        "hour": [6] * 4,
        "scientific_name": ["Pavo cristatus"] * 4,
        "common_name": ["Indian Peafowl"] * 4,
        "confidence": [0.30, 0.45, 0.50, 0.60],
        "filename": ["a.wav", "a.wav", "b.wav", "b.wav"],
        "min_confidence": [0.25, 0.25, 0.40, 0.40],
    })
    rollup = rollups.build(df)[0]
    assert rollup.effective_confidence_floor == 0.40
    assert rollup.heterogeneous_floor is True


def test_absent_floor_column_is_unknown_not_assumed() -> None:
    """Rows predating the pipeline change must not be given a default."""
    df = pd.DataFrame({
        "spot": ["site_a"], "date": ["2026-04-10"], "hour": [6],
        "scientific_name": ["Pavo cristatus"], "common_name": ["Indian Peafowl"],
        "confidence": [0.5], "filename": ["a.wav"],
    })
    rollup = rollups.build(df)[0]
    assert rollup.effective_confidence_floor is None
    assert rollup.heterogeneous_floor is True


# ------------------------------------------------------------- robustness ----

def test_unusable_rows_are_dropped_not_coerced() -> None:
    """A detection with no date or no species cannot be attributed to anything."""
    df = pd.DataFrame({
        "spot":            ["site_a", "site_a", "site_a", ""],
        "date":            ["2026-04-10", None, "2026-04-10", "2026-04-10"],
        "hour":            [6, 6, 6, 6],
        "scientific_name": ["Pavo cristatus", "Pavo cristatus", None, "Pavo cristatus"],
        "common_name":     ["Indian Peafowl"] * 4,
        "confidence":      [0.5, 0.5, 0.5, 0.5],
        "filename":        ["a.wav", "b.wav", "c.wav", "d.wav"],
    })
    built = rollups.build(df)
    assert len(built) == 1
    assert built[0].total_detections == 1, "only the fully-formed row survives"


def test_duplicate_detections_are_deduplicated() -> None:
    """Guards against a lost processed_files.txt doubling every number."""
    row = {
        "spot": "site_a", "date": "2026-04-10", "hour": 6,
        "scientific_name": "Pavo cristatus", "common_name": "Indian Peafowl",
        "confidence": 0.81, "filename": "a.wav", "start_time": 3.0,
    }
    df = pd.DataFrame([row, row])          # the same detection appended twice
    assert rollups.build(df)[0].total_detections == 1


def test_empty_input_produces_nothing() -> None:
    assert rollups.build(pd.DataFrame()) == []
