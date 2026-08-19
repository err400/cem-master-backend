"""Reading the compute app's DATA_DIR.

Every filesystem access the indexer makes lives here. Nothing else in the package
touches a path, so if the deployment ever changes -- the compute app moving
somewhere that does not share a volume, and an HTTP API replacing the mount --
this is the only file that changes and the rollup logic is untouched.

Layout, verified against cem-backend/server/app/{projects,jobs}.py:

    DATA_DIR/projects/<project>/
        project.json
        <SPOT>/audio/*.wav
        dataset/aggregate.csv          the durable master table
        dataset/processed_files.txt    the process-once cache
        <script>/<job_id>/
            job.json
            input/geo.json             SPOT COORDINATES -- see read_geo()
            input/audio_spots.json
            work/aggregate.csv
            results/<step>/...

Treat everything here as READ-ONLY and TRANSIENT. The compute app's own config
says "Cluster = compute, not storage", and retention.py deletes job folders after
RETENTION_HOURS (default 168h). Read promptly; never assume a second read will
find the same thing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

# Columns the indexer relies on. birdnet_predictions.py writes these plus
# scientific_name/common_name/confidence from BirdNET itself.
REQUIRED_AGGREGATE_COLUMNS = frozenset(
    {"scientific_name", "common_name", "confidence", "filename", "spot", "date", "hour"}
)

AGGREGATE_REL = Path("dataset") / "aggregate.csv"
PROCESSED_REL = Path("dataset") / "processed_files.txt"


class SourceError(RuntimeError):
    """The DATA_DIR is missing, malformed, or not laid out as expected."""


@dataclass(frozen=True)
class JobRef:
    """One analysis run on disk."""

    job_id: str
    script: str
    root: Path

    @property
    def results_dir(self) -> Path:
        return self.root / "results"

    @property
    def geo_path(self) -> Path:
        return self.root / "input" / "geo.json"

    def read_meta(self) -> dict:
        path = self.root / "job.json"
        if not path.is_file():
            return {}
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}

    def facts(self) -> dict:
        """Job-level status, parameters and timings, derived from its tasks.

        ``job.json`` keeps ``status``, ``params``, ``started_at`` and
        ``finished_at`` on each entry in ``tasks[]``, not at the top level -- a
        job is a container for one or more task runs. Reading ``meta["status"]``
        directly (as an earlier version did) silently returns nothing on real
        data and makes every job look completed with no parameters.

        A job is 'failed' if any task failed, 'completed' when every task
        finished, and 'running' otherwise. Parameters are merged across tasks,
        later ones winning, since a job usually has a single task.
        """
        meta = self.read_meta()
        tasks = meta.get("tasks") or []

        if not tasks:
            return {
                "status": str(meta.get("status") or "completed"),
                "params": dict(meta.get("params") or {}),
                "started_at": meta.get("started_at") or meta.get("created_at"),
                "completed_at": meta.get("finished_at"),
            }

        statuses = {str(t.get("status") or "").lower() for t in tasks}
        if statuses & {"failed", "error"}:
            status = "failed"
        elif statuses <= {"completed", "success", "succeeded", "done"}:
            status = "completed"
        else:
            status = "running"

        params: dict = {}
        for task in tasks:
            params.update(task.get("params") or {})

        starts = [t.get("started_at") for t in tasks if t.get("started_at")]
        ends = [t.get("finished_at") for t in tasks if t.get("finished_at")]

        return {
            "status": status,
            "params": params,
            # ISO-8601 strings sort chronologically, so min/max are correct
            # without parsing.
            "started_at": min(starts) if starts else meta.get("created_at"),
            "completed_at": max(ends) if ends else None,
        }

    def spot_keys(self) -> list[str]:
        """Normalised spot names this job covered.

        From ``job.json``'s ``spots`` if present, else from
        ``input/audio_spots.json``'s values -- the second is authoritative about
        which audio actually went in, the first about what was requested.
        """
        meta = self.read_meta()
        spots = meta.get("spots")
        if isinstance(spots, list) and spots:
            return sorted({normalise_spot(s) for s in spots if s})

        mapping = self.root / "input" / "audio_spots.json"
        if mapping.is_file():
            try:
                data = json.loads(mapping.read_text())
            except (OSError, json.JSONDecodeError):
                return []
            if isinstance(data, dict):
                return sorted({normalise_spot(v) for v in data.values() if v})
        return []

    def result_files(self) -> list[Path]:
        """Every output file, relative paths, sorted."""
        if not self.results_dir.is_dir():
            return []
        return sorted(p for p in self.results_dir.rglob("*") if p.is_file())


# Decimal places used for spot identity. 5 dp is ~1.1 m at the equator: coarse
# enough to absorb GPS jitter between two readings of the same recorder, fine
# enough not to merge genuinely different ones.
#
# A CONSTANT, not a literal scattered through the code, because changing it is a
# re-index rather than a migration -- and someone will want to change it.
GEO_KEY_PRECISION = 5


def make_geo_key(lat: float, lon: float) -> str:
    """Identity for a physical location: ``"28.54100:77.16950"``.

    Rounded rather than compared exactly, because two GPS readings of the same
    tree differ in the last decimals and exact equality made them two map
    markers.

    Formatted to a fixed width so the key is stable: ``round(28.541, 5)`` is
    ``28.541``, whose ``str()`` is ``"28.541"`` -- a different string from
    ``"28.54100"`` for the same place. Padding removes that trap entirely.

    This is also what lets identity survive a rename: renaming a spot does not
    move the recorder, so the key is unchanged.
    """
    return f"{lat:.{GEO_KEY_PRECISION}f}:{lon:.{GEO_KEY_PRECISION}f}"


def normalise_spot(name: str) -> str:
    """Canonical form for matching spot names across files.

    ``aggregate.csv`` lowercases the spot (filter_utils does
    ``.str.strip().str.lower()``), while ``geo.json`` uppercases it and strips
    whitespace (the frontend does ``name.replace(/\\s+/g,'').toUpperCase()``).
    Neither is authoritative, so both sides get folded to the same key before
    being compared. Whitespace is removed rather than trimmed, because the
    frontend removes interior spaces too: "Site A" becomes "SITEA".
    """
    return "".join(str(name).split()).casefold()


def project_root(data_dir: Path, project: str) -> Path:
    root = (data_dir / "projects" / project).resolve()
    # Refuse a project name that escapes the projects directory. The name reaches
    # us from a CLI argument or an API payload, so this is not paranoia.
    projects_dir = (data_dir / "projects").resolve()
    if not str(root).startswith(str(projects_dir)):
        raise SourceError(f"project name escapes the projects directory: {project!r}")
    return root


def list_projects(data_dir: Path) -> list[str]:
    projects_dir = data_dir / "projects"
    if not projects_dir.is_dir():
        raise SourceError(f"not a DATA_DIR: {projects_dir} does not exist")
    return sorted(
        p.name
        for p in projects_dir.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    )


def read_aggregate(data_dir: Path, project: str) -> pd.DataFrame:
    """Load a project's durable master table.

    Returns an EMPTY DataFrame (with the expected columns) when the file is
    absent, rather than raising: a project whose analysis has not run yet is a
    normal state, not an error. A malformed file IS an error.
    """
    path = project_root(data_dir, project) / AGGREGATE_REL
    if not path.is_file() or path.stat().st_size == 0:
        return pd.DataFrame(columns=sorted(REQUIRED_AGGREGATE_COLUMNS))

    try:
        df = pd.read_csv(path)
    except Exception as exc:  # pragma: no cover - surfaced to the operator
        raise SourceError(f"cannot parse {path}: {exc}") from exc

    missing = REQUIRED_AGGREGATE_COLUMNS - set(df.columns)
    if missing:
        raise SourceError(
            f"{path} is missing required columns {sorted(missing)}. "
            "Has the pipeline's aggregate schema changed?"
        )
    return df


def read_processed_files(data_dir: Path, project: str) -> set[str]:
    """The process-once cache.

    Not needed for the rollups, but reading it lets the indexer report when a
    project's aggregate covers files the cache no longer lists -- a sign the
    cache was lost and detections may have been double-appended (see
    INDEXING-PLAN 6.7).
    """
    path = project_root(data_dir, project) / PROCESSED_REL
    if not path.is_file():
        return set()
    return {
        Path(line.strip()).name
        for line in path.read_text().splitlines()
        if line.strip()
    }


_RESERVED_DIRS = {"dataset", ".git", "__pycache__"}


def list_jobs(data_dir: Path, project: str) -> list[JobRef]:
    """Every analysis run still on disk, newest last.

    A job directory is ``<project>/<script>/<job_id>/`` containing ``job.json``.
    Spot directories are excluded by that requirement -- they contain ``audio/``,
    not ``job.json`` -- which avoids having to guess from the name.
    """
    root = project_root(data_dir, project)
    if not root.is_dir():
        return []

    jobs: list[JobRef] = []
    for script_dir in sorted(root.iterdir()):
        if (
            not script_dir.is_dir()
            or script_dir.name in _RESERVED_DIRS
            or script_dir.name.startswith(".")
            or (script_dir / "audio").is_dir()  # a spot, not a script
        ):
            continue
        for job_dir in sorted(script_dir.iterdir()):
            if job_dir.is_dir() and (job_dir / "job.json").is_file():
                jobs.append(
                    JobRef(job_id=job_dir.name, script=script_dir.name, root=job_dir)
                )

    # Sort by mtime so "most recent wins" is well defined for coordinates.
    jobs.sort(key=lambda j: j.root.stat().st_mtime)
    return jobs


def read_geo(data_dir: Path, project: str) -> dict[str, tuple[float, float]]:
    """Spot coordinates, keyed by normalised spot name.

    THE ONLY PLACE COORDINATES EXIST ON DISK. ``aggregate.csv`` has spot names
    but no positions; the frontend sends ``spots_geo`` on POST /analyze and the
    compute backend writes it to ``<job>/input/geo.json``.

    Two consequences worth knowing:

    * Coordinates are per-JOB, so every job is scanned and later jobs win. A spot
      that has never been analysed has no coordinates anywhere.
    * ``retention.py`` deletes job folders after RETENTION_HOURS (default 7
      days), taking geo.json with them. So this must be captured into the
      catalog DB promptly -- afterwards the database is the durable record and
      this function may legitimately return nothing.
    """
    coords: dict[str, tuple[float, float]] = {}
    for job in list_jobs(data_dir, project):  # oldest first, so newer overwrite
        if not job.geo_path.is_file():
            continue
        try:
            entries = json.loads(job.geo_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(entries, list):
            continue
        for entry in entries:
            try:
                name = normalise_spot(entry["name"])
                lat = float(entry["lat"])
                lon = float(entry["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            coords[name] = (lat, lon)
    return coords


MIGRATORY_BY_SPOT = "migratory_classification_by_spot.csv"
MIGRATORY_POOLED = "migratory_classification_all_species.csv"


def read_migratory(
    data_dir: Path, project: str
) -> tuple[dict[tuple[str, str], dict], bool]:
    """Migratory/resident verdicts, keyed by (normalised spot, common name).

    Returns ``(verdicts, pooled)``. ``pooled`` is True when only the older
    species-level file was available, meaning one verdict has been applied to
    every spot -- which is not the same claim, and the caller should say so.

    Prefers ``migratory_classification_by_spot.csv``, which the pipeline fix
    added. Falls back to ``migratory_classification_all_species.csv``, whose
    verdicts are computed across every spot in the run pooled together: fine as a
    statement about a dataset, wrong as a statement about a place, since a
    species can be resident in one location and migratory in another.

    Later jobs win, so a re-run supersedes an earlier classification.
    """
    verdicts: dict[tuple[str, str], dict] = {}
    pooled_only = True

    for job in list_jobs(data_dir, project):  # oldest first
        results = job.results_dir / "migratory_classification"
        if not results.is_dir():
            continue

        by_spot = results / MIGRATORY_BY_SPOT
        pooled = results / MIGRATORY_POOLED

        if by_spot.is_file():
            try:
                frame = pd.read_csv(by_spot)
            except Exception:
                continue
            if {"Spot", "Species", "Classification"} <= set(frame.columns):
                pooled_only = False
                for row in frame.to_dict("records"):
                    verdicts[(normalise_spot(row["Spot"]), str(row["Species"]))] = row
                continue

        if pooled.is_file():
            try:
                frame = pd.read_csv(pooled)
            except Exception:
                continue
            if {"Species", "Classification"} <= set(frame.columns):
                # No spot information: mark with a sentinel so the writer can
                # apply it everywhere while knowing it did so.
                for row in frame.to_dict("records"):
                    verdicts[(POOLED_SPOT, str(row["Species"]))] = row

    return verdicts, pooled_only


# Sentinel spot key for a verdict that came from the pooled, spot-less file.
POOLED_SPOT = "*"


def read_acoustic_indices(data_dir: Path, project: str) -> dict[str, dict]:
    """Soundscape indices per normalised spot name.

    The step writes one row per spot with columns like ACI/ADI/AEI/NDSI. Column
    names are passed through as-is rather than being mapped to a fixed list --
    the frontend renders whatever keys it receives, so a new index appearing in
    the pipeline shows up without a change here.
    """
    indices: dict[str, dict] = {}
    for job in list_jobs(data_dir, project):  # oldest first, later jobs win
        results = job.results_dir / "acoustic_indices"
        if not results.is_dir():
            continue
        for csv_path in sorted(results.glob("*.csv")):
            try:
                frame = pd.read_csv(csv_path)
            except Exception:
                continue
            if "Spot" not in frame.columns:
                continue
            for row in frame.to_dict("records"):
                spot_key = normalise_spot(row.pop("Spot"))
                values = {
                    k: float(v)
                    for k, v in row.items()
                    if isinstance(v, (int, float)) and pd.notna(v)
                }
                if values:
                    indices[spot_key] = values
    return indices


def count_audio_files(data_dir: Path, project: str) -> dict[str, int]:
    """Audio file count per normalised spot name, from the directory tree.

    Distinct from counting ``filename`` in the aggregate: a spot can hold audio
    that has not been analysed yet, and those recordings exist even though no
    detection references them.
    """
    root = project_root(data_dir, project)
    counts: dict[str, int] = {}
    if not root.is_dir():
        return counts
    for spot_dir in sorted(root.iterdir()):
        audio = spot_dir / "audio"
        if not (spot_dir.is_dir() and audio.is_dir()):
            continue
        counts[normalise_spot(spot_dir.name)] = sum(
            1 for p in audio.iterdir() if p.is_file()
        )
    return counts
