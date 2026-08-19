"""Build a minimal fixture DATA_DIR mirroring the compute app's real layout.

Deliberately TINY -- 24 detections, 2 spots, 3 species -- so every expected value
can be worked out by hand and asserted exactly. A large realistic dataset tells
you the indexer ran; a hand-countable one tells you it ran *correctly*.

Layout produced (verified against cem-backend/server/app/projects.py and jobs.py):

    <out>/projects/fixture-demo/
        project.json
        SITE_A/audio/*.wav                    (empty files -- only names matter)
        SITE_B/audio/*.wav
        dataset/aggregate.csv                 the durable master table
        dataset/processed_files.txt           the process-once cache
        birdnet/job-0001/
            job.json
            input/audio/                      (symlinks in production)
            input/audio_spots.json            {basename: spot}
            input/geo.json                    SPOT COORDINATES -- the only
                                              place they exist on disk
            input/aggregate.csv               copied in from dataset/
            input/processed_files.txt
            work/aggregate.csv                produced by birdnet
            work/processed_files.txt
            results/birdnet/birdnet_results.csv
        migratory_classification/job-0002/
            results/migratory_classification/
                migratory_classification_all_species.csv   (pooled, legacy)
                migratory_classification_by_spot.csv       (added by the fix)
        acoustic_indices/job-0003/
            results/acoustic_indices/acoustic_indices_summary.csv

job.json uses the REAL shape: status, params and timings live on entries in
tasks[], not at the top level (see cem-backend/server/app/jobs.py:161).

Note the casing mismatch this reproduces on purpose: geo.json names are
UPPERCASE (the frontend does name.replace(/\\s+/g,'').toUpperCase()) while
aggregate.csv's `spot` column is lowercase (filter_utils lowercases it). The
indexer has to normalise both sides, so the fixture must exercise it.

Usage:
    python tests/fixtures/build_fixture.py [--out tests/fixtures/data_dir]
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path

# --------------------------------------------------------------------------
# The hand-countable dataset.
#
# 24 detection rows. Work them out by hand; the tests assert these exact values.
#
#   SPOT A  (site_a, 28.5330 / 77.1760)
#     Indian Peafowl       8 detections, 2 dates (04-10 x5, 04-11 x3)
#     Common Tailorbird    5 detections, 2 dates (04-10 x2, 04-11 x3)
#     -> richness 2, total 13, active_days 2, recordings 4
#
#   SPOT B  (site_b, 28.5352 / 77.1812)
#     Indian Peafowl       3 detections, 1 date  (04-10 x3)
#     Hume's Warbler       8 detections, 2 dates (04-10 x6, 04-11 x2)
#     -> richness 2, total 11, active_days 2, recordings 3
#
#   Hume's Warbler appears at ONE spot only -- so species search must return
#   exactly one spot for it, and two for Indian Peafowl.
# --------------------------------------------------------------------------

SPECIES = {
    "Indian Peafowl": "Pavo cristatus",
    "Common Tailorbird": "Orthotomus sutorius",
    "Hume's Warbler": "Phylloscopus humei",
}

# (spot, filename, date, hour, common_name, confidence, min_confidence)
DETECTIONS = [
    # --- SPOT A, 2026-04-10, file 1 (hour 6): peafowl x3, tailorbird x1
    ("site_a", "SPOTA_20260410_060000.wav", "2026-04-10", 6, "Indian Peafowl", 0.81, 0.25),
    ("site_a", "SPOTA_20260410_060000.wav", "2026-04-10", 6, "Indian Peafowl", 0.77, 0.25),
    ("site_a", "SPOTA_20260410_060000.wav", "2026-04-10", 6, "Indian Peafowl", 0.62, 0.25),
    ("site_a", "SPOTA_20260410_060000.wav", "2026-04-10", 6, "Common Tailorbird", 0.55, 0.25),
    # --- SPOT A, 2026-04-10, file 2 (hour 17): peafowl x2, tailorbird x1
    ("site_a", "SPOTA_20260410_170000.wav", "2026-04-10", 17, "Indian Peafowl", 0.71, 0.25),
    ("site_a", "SPOTA_20260410_170000.wav", "2026-04-10", 17, "Indian Peafowl", 0.44, 0.25),
    ("site_a", "SPOTA_20260410_170000.wav", "2026-04-10", 17, "Common Tailorbird", 0.39, 0.25),
    # --- SPOT A, 2026-04-11, file 3 (hour 6): peafowl x3, tailorbird x2
    ("site_a", "SPOTA_20260411_060000.wav", "2026-04-11", 6, "Indian Peafowl", 0.90, 0.25),
    ("site_a", "SPOTA_20260411_060000.wav", "2026-04-11", 6, "Indian Peafowl", 0.68, 0.25),
    ("site_a", "SPOTA_20260411_060000.wav", "2026-04-11", 6, "Indian Peafowl", 0.51, 0.25),
    ("site_a", "SPOTA_20260411_060000.wav", "2026-04-11", 6, "Common Tailorbird", 0.61, 0.25),
    ("site_a", "SPOTA_20260411_060000.wav", "2026-04-11", 6, "Common Tailorbird", 0.47, 0.25),
    # --- SPOT A, 2026-04-11, file 4 (hour 18): tailorbird x1
    ("site_a", "SPOTA_20260411_180000.wav", "2026-04-11", 18, "Common Tailorbird", 0.52, 0.25),

    # --- SPOT B, 2026-04-10, file 1 (hour 6): peafowl x3, warbler x4
    ("site_b", "SPOTB_20260410_060000.wav", "2026-04-10", 6, "Indian Peafowl", 0.66, 0.25),
    ("site_b", "SPOTB_20260410_060000.wav", "2026-04-10", 6, "Indian Peafowl", 0.58, 0.25),
    ("site_b", "SPOTB_20260410_060000.wav", "2026-04-10", 6, "Indian Peafowl", 0.49, 0.25),
    ("site_b", "SPOTB_20260410_060000.wav", "2026-04-10", 6, "Hume's Warbler", 0.72, 0.25),
    ("site_b", "SPOTB_20260410_060000.wav", "2026-04-10", 6, "Hume's Warbler", 0.64, 0.25),
    ("site_b", "SPOTB_20260410_060000.wav", "2026-04-10", 6, "Hume's Warbler", 0.55, 0.25),
    ("site_b", "SPOTB_20260410_060000.wav", "2026-04-10", 6, "Hume's Warbler", 0.41, 0.25),
    # --- SPOT B, 2026-04-10, file 2 (hour 7): warbler x2
    ("site_b", "SPOTB_20260410_070000.wav", "2026-04-10", 7, "Hume's Warbler", 0.68, 0.25),
    ("site_b", "SPOTB_20260410_070000.wav", "2026-04-10", 7, "Hume's Warbler", 0.60, 0.25),
    # --- SPOT B, 2026-04-11, file 3 (hour 6): warbler x2
    ("site_b", "SPOTB_20260411_060000.wav", "2026-04-11", 6, "Hume's Warbler", 0.75, 0.25),
    ("site_b", "SPOTB_20260411_060000.wav", "2026-04-11", 6, "Hume's Warbler", 0.53, 0.25),
]

# Spot names here are UPPERCASE, as the frontend sends them
# (name.replace(/\s+/g,'').toUpperCase()). aggregate.csv's `spot` column is
# lowercase, because filter_utils lowercases it. Reproducing that mismatch is
# the point: the indexer must normalise both sides to join them.
#
# In production the frontend also strips whitespace, so a spot named "Site A"
# becomes "SITEA" in geo.json but "site a" in the aggregate. The safe
# normalisation is therefore casefold + remove whitespace, on both sides.
#
# These must NOT collide with scripts/seed_spots.py's coordinates. `spots` has
# UniqueConstraint("latitude", "longitude"), so two projects at an identical
# point cannot both hold a row -- the schema's intent is that they share one
# canonical spot instead. Until the rollup tables are keyed by
# source_project_id (INDEXING-PLAN 6.6b) that sharing is not supported, so the
# fixture deliberately sits at its own coordinates.
GEO = [
    {"name": "SITE_A", "lat": 28.5410, "lon": 77.1695},
    {"name": "SITE_B", "lat": 28.5388, "lon": 77.1902},
]

PROJECT = "fixture-demo"
BIRDNET_JOB = "job-0001"
MIGRATORY_JOB = "job-0002"

AGGREGATE_COLUMNS = [
    "scientific_name", "common_name", "confidence",
    "filename", "filepath", "spot", "date", "hour", "label", "min_confidence",
]


def _aggregate_rows() -> list[dict]:
    rows = []
    for spot, filename, date, hour, common, conf, min_conf in DETECTIONS:
        rows.append({
            "scientific_name": SPECIES[common],
            "common_name": common,
            "confidence": conf,
            "filename": filename,
            "filepath": f"/data/projects/{PROJECT}/{spot.upper()}/audio/{filename}",
            "spot": spot,
            "date": date,
            "hour": hour,
            "label": common,
            "min_confidence": min_conf,
        })
    return rows


def _write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _clear(out: Path) -> None:
    """Empty the output directory WITHOUT deleting the directory itself.

    ``shutil.rmtree(out)`` followed by recreating it gives the path a new inode.
    A container bind-mounting this directory keeps pointing at the old, deleted
    one, so ``/data`` inside the container silently becomes empty and stays that
    way until the container is recreated -- with no error anywhere.

    Removing only the *contents* keeps the inode, so a running container sees the
    rebuilt fixture immediately.
    """
    if not out.exists():
        out.mkdir(parents=True)
        return
    for child in out.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def build(out: Path) -> Path:
    _clear(out)

    project_root = out / "projects" / PROJECT
    rows = _aggregate_rows()
    filenames = sorted({r["filename"] for r in rows})

    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "project.json").write_text(json.dumps({
        "created_at": "2026-04-09T00:00:00+00:00",
        "last_modified": "2026-04-12T00:00:00+00:00",
    }, indent=2))

    # Audio files, per spot. Contents are irrelevant -- the indexer only ever
    # counts and names them -- but the directory structure must be real, because
    # that is how spot membership is expressed on disk.
    for spot in {r["spot"] for r in rows}:
        audio_dir = project_root / spot.upper() / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        for name in (r["filename"] for r in rows if r["spot"] == spot):
            (audio_dir / name).touch()

    # The durable master table, plus the process-once cache that guards it.
    _write_csv(project_root / "dataset" / "aggregate.csv", AGGREGATE_COLUMNS, rows)
    (project_root / "dataset" / "processed_files.txt").write_text(
        "\n".join(filenames) + "\n"
    )

    # --- birdnet job -------------------------------------------------------
    job = project_root / "birdnet" / BIRDNET_JOB
    (job / "input" / "audio").mkdir(parents=True)
    (job / "work").mkdir(parents=True)
    (job / "results" / "birdnet").mkdir(parents=True)

    # Real job.json shape (cem-backend/server/app/jobs.py): status, params and
    # timings live on each entry in tasks[], NOT at the top level. A fixture that
    # flattened them would validate a shape that does not exist.
    (job / "job.json").write_text(json.dumps({
        "id": BIRDNET_JOB,
        "script": "birdnet",
        "project": PROJECT,
        "created_at": "2026-04-12T04:00:00+00:00",
        "spots": ["SITE_A", "SITE_B"],
        "start_date": "2026-04-10",
        "end_date": "2026-04-11",
        "tasks": [
            {
                "task_id": "t_aaaa1111",
                "step": "birdnet",
                "status": "completed",
                "created_at": "2026-04-12T04:00:00+00:00",
                "started_at": "2026-04-12T04:00:05+00:00",
                "finished_at": "2026-04-12T04:20:00+00:00",
                "returncode": 0,
                "params": {"min_confidence": "0.25", "snr_db": "18"},
                "results": ["results/birdnet/birdnet_results.csv"],
            }
        ],
    }, indent=2))

    for name in filenames:
        (job / "input" / "audio" / name).touch()

    (job / "input" / "audio_spots.json").write_text(json.dumps(
        {r["filename"]: r["spot"] for r in rows}, indent=2
    ))
    # THE COORDINATES. Nothing else on disk has them.
    (job / "input" / "geo.json").write_text(json.dumps(GEO, indent=2))

    _write_csv(job / "input" / "aggregate.csv", AGGREGATE_COLUMNS, [])
    (job / "input" / "processed_files.txt").write_text("")
    _write_csv(job / "work" / "aggregate.csv", AGGREGATE_COLUMNS, rows)
    (job / "work" / "processed_files.txt").write_text("\n".join(filenames) + "\n")
    _write_csv(job / "results" / "birdnet" / "birdnet_results.csv", AGGREGATE_COLUMNS, rows)

    # --- migratory_classification job -------------------------------------
    # NOTE: no Spot column. That is the CURRENT pipeline output -- one verdict
    # per species across every spot in the run. The per-spot fix will add it,
    # and the indexer must cope with both shapes.
    mig = project_root / "migratory_classification" / MIGRATORY_JOB
    (mig / "results" / "migratory_classification").mkdir(parents=True)
    (mig / "job.json").write_text(json.dumps({
        "id": MIGRATORY_JOB,
        "script": "migratory_classification",
        "project": PROJECT,
        "created_at": "2026-04-12T05:00:00+00:00",
        "spots": ["SITE_A", "SITE_B"],
        "tasks": [{
            "task_id": "t_migr0001",
            "step": "migratory_classification",
            "status": "completed",
            "started_at": "2026-04-12T05:00:05+00:00",
            "finished_at": "2026-04-12T05:05:00+00:00",
            "params": {},
        }],
    }, indent=2))
    _write_csv(
        mig / "results" / "migratory_classification"
        / "migratory_classification_all_species.csv",
        ["Species", "SCI", "Kurtosis", "PMR", "Total_Detections", "Classification"],
        [
            {"Species": "Indian Peafowl", "SCI": 0.42, "Kurtosis": 1.10,
             "PMR": 1.80, "Total_Detections": 11, "Classification": "Resident"},
            {"Species": "Common Tailorbird", "SCI": 0.31, "Kurtosis": 0.90,
             "PMR": 1.40, "Total_Detections": 5, "Classification": "Resident"},
            {"Species": "Hume's Warbler", "SCI": 0.98, "Kurtosis": 4.20,
             "PMR": 6.10, "Total_Detections": 8, "Classification": "Migratory"},
        ],
    )

    # The per-spot file added by the pipeline fix. Note the disagreement it makes
    # possible and the pooled file cannot express: Indian Peafowl is Resident at
    # site_a (spread over both days) but Unknown at site_b, where three
    # detections on a single day are too few to judge. That asymmetry is the
    # whole reason per-spot classification exists.
    _write_csv(
        mig / "results" / "migratory_classification"
        / "migratory_classification_by_spot.csv",
        ["Spot", "Species", "SCI", "Kurtosis", "PMR", "Total_Detections", "Classification"],
        [
            {"Spot": "site_a", "Species": "Indian Peafowl", "SCI": 0.44, "Kurtosis": 1.05,
             "PMR": 1.60, "Total_Detections": 8, "Classification": "Resident"},
            {"Spot": "site_a", "Species": "Common Tailorbird", "SCI": 0.31, "Kurtosis": 0.90,
             "PMR": 1.40, "Total_Detections": 5, "Classification": "Resident"},
            {"Spot": "site_b", "Species": "Hume's Warbler", "SCI": 0.98, "Kurtosis": 4.20,
             "PMR": 6.10, "Total_Detections": 8, "Classification": "Migratory"},
            {"Spot": "site_b", "Species": "Indian Peafowl", "SCI": 1.00, "Kurtosis": 9.90,
             "PMR": 99.00, "Total_Detections": 3, "Classification": "Unknown"},
        ],
    )

    # Acoustic indices, per spot. One row per spot is what the panel shows.
    ai = project_root / "acoustic_indices" / "job-0003"
    (ai / "results" / "acoustic_indices").mkdir(parents=True)
    (ai / "job.json").write_text(json.dumps({
        "id": "job-0003",
        "script": "acoustic_indices",
        "project": PROJECT,
        "created_at": "2026-04-12T05:00:00+00:00",
        "spots": ["SITE_A", "SITE_B"],
        "tasks": [{
            "task_id": "t_acou0001",
            "step": "acoustic_indices",
            "status": "completed",
            "started_at": "2026-04-12T05:00:05+00:00",
            "finished_at": "2026-04-12T05:05:00+00:00",
            "params": {},
        }],
    }, indent=2))
    _write_csv(
        ai / "results" / "acoustic_indices" / "acoustic_indices_summary.csv",
        ["Spot", "ACI", "ADI", "AEI", "NDSI", "BI", "H"],
        [
            {"Spot": "site_a", "ACI": 0.51, "ADI": 0.60, "AEI": 0.58,
             "NDSI": 0.40, "BI": 12.3, "H": 0.71},
            {"Spot": "site_b", "ACI": 0.47, "ADI": 0.66, "AEI": 0.62,
             "NDSI": 0.35, "BI": 10.9, "H": 0.68},
        ],
    )

    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=str(Path(__file__).parent / "data_dir"),
        help="where to write the fixture DATA_DIR",
    )
    args = parser.parse_args()
    out = build(Path(args.out).resolve())
    print(f"Fixture DATA_DIR written to {out}")
    print(f"  {len(DETECTIONS)} detections, "
          f"{len({d[0] for d in DETECTIONS})} spots, {len(SPECIES)} species")


if __name__ == "__main__":
    main()
