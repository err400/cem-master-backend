"""Turning detection rows into the summaries the master page reads.

Pure computation: pandas in, plain dataclasses out. No database, no filesystem.
That makes every number here testable against a hand-counted fixture without
standing anything up, which matters because a wrong rollup produces a page that
looks entirely plausible.

The grain of each output mirrors a table:

    SpotRollup         -> spot_summaries          (one per spot)
    SpotSpeciesRollup  -> spot_species_summaries  (one per spot x species)
    DailyRollup        -> spot_species_daily      (one per spot x species x date)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from .source import normalise_spot

# The frontend's chart indexes hourly_counts by hour and calls .toLocaleString()
# on each element, so this must always be exactly 24 numbers -- never null, never
# a dict, never short. See INDEXING-PLAN 6.8.
HOURS_IN_DAY = 24


@dataclass
class DailyRollup:
    spot_key: str
    scientific_name: str
    observation_date: date
    detection_count: int


@dataclass
class SpotSpeciesRollup:
    spot_key: str
    scientific_name: str
    common_name: str
    detection_count: int
    active_days: int
    average_confidence: float
    maximum_confidence: float
    first_detection_date: date
    last_detection_date: date
    activity_rank: int
    hourly_counts: list[int]
    daily_counts: list[dict]
    monthly_counts: list[dict]


@dataclass
class SpotRollup:
    spot_key: str
    spot_label: str
    species_richness: int
    total_detections: int
    active_days: int
    recording_count: int
    first_recording_date: date
    last_recording_date: date
    effective_confidence_floor: float | None
    heterogeneous_floor: bool
    species: list[SpotSpeciesRollup] = field(default_factory=list)
    daily: list[DailyRollup] = field(default_factory=list)
    # Every distinct raw spelling that folded into spot_key. More than one means
    # rows differing only in case or whitespace were merged into a single spot --
    # right for "Site A" vs "SITE A", wrong if they were genuinely different
    # places. Surfaced rather than silently resolved; the writer warns.
    label_variants: list[str] = field(default_factory=list)


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise raw aggregate rows before any grouping.

    Deliberately strict about dropping unusable rows rather than coercing them:
    a detection with no date or no species cannot be attributed to anything, and
    silently defaulting it would put invented data on a public page.
    """
    if df.empty:
        return df

    out = df.copy()
    out["spot_key"] = out["spot"].map(normalise_spot)
    out["spot_label"] = out["spot"].astype(str).str.strip()
    out["observation_date"] = pd.to_datetime(out["date"], errors="coerce").dt.date
    out["confidence"] = pd.to_numeric(out["confidence"], errors="coerce")
    out["hour"] = pd.to_numeric(out["hour"], errors="coerce")

    out = out[
        out["spot_key"].astype(bool)
        & ~out["spot_key"].isin({"nan", "none"})
        & out["observation_date"].notna()
        & out["scientific_name"].notna()
        & out["confidence"].notna()
    ]

    # Guard against a lost processed_files.txt having caused the same recording to
    # be analysed twice and appended twice (INDEXING-PLAN 6.7). Deduplicating on
    # the detection's identity is cheap and turns a silent doubling of every
    # number into a non-event.
    dedupe_cols = [c for c in ("filename", "start_time", "scientific_name") if c in out.columns]
    if len(dedupe_cols) >= 2:
        out = out.drop_duplicates(subset=dedupe_cols + ["confidence"])

    return out


def _hourly(group: pd.DataFrame) -> list[int]:
    counts = [0] * HOURS_IN_DAY
    hours = group["hour"].dropna()
    for hour, n in hours.astype(int).value_counts().items():
        if 0 <= hour < HOURS_IN_DAY:
            counts[hour] = int(n)
    return counts


def _daily_pairs(group: pd.DataFrame) -> list[dict]:
    """``[{"date": "2026-04-10", "count": 5}, ...]``, chronological.

    The frontend uses ``rows[0].date`` and ``rows.at(-1).date`` as axis labels,
    so the order is part of the contract, not a nicety.
    """
    counts = group.groupby("observation_date").size().sort_index()
    return [{"date": d.isoformat(), "count": int(n)} for d, n in counts.items()]


def _monthly_pairs(group: pd.DataFrame) -> list[dict]:
    """``[{"month": "2026-04", "count": 13}, ...]``, chronological.

    Keys are ``YYYY-MM`` so they sort lexicographically as well as
    chronologically -- which is what makes a December/January boundary behave.
    """
    months = group["observation_date"].map(lambda d: f"{d.year:04d}-{d.month:02d}")
    counts = months.value_counts().sort_index()
    return [{"month": m, "count": int(n)} for m, n in counts.items()]


def _confidence_floor(group: pd.DataFrame) -> tuple[float | None, bool]:
    """The effective floor for a spot, and whether its files disagree.

    ``min_confidence`` is a GENERATION parameter: detections below it were never
    written and cannot be recovered. Because each audio file is analysed exactly
    once, a spot's files can have been processed at different thresholds, and the
    aggregate then has a floor that varies per file.

    The effective floor is therefore the MAXIMUM -- reporting anything below it
    would be biased, since some files could never have contributed there. Rows
    written before the column existed have an unknown floor and are flagged
    rather than assumed.
    """
    if "min_confidence" not in group.columns:
        return None, True
    values = pd.to_numeric(group["min_confidence"], errors="coerce")
    known = values.dropna()
    if known.empty:
        return None, True
    heterogeneous = bool(known.nunique() > 1 or values.isna().any())
    return float(known.max()), heterogeneous


def build(df: pd.DataFrame, audio_counts: dict[str, int] | None = None) -> list[SpotRollup]:
    """Compute every rollup for one project's detections."""
    audio_counts = audio_counts or {}
    prepared = prepare(df)
    if prepared.empty:
        return []

    rollups: list[SpotRollup] = []

    for spot_key, spot_rows in prepared.groupby("spot_key", sort=True):
        floor, heterogeneous = _confidence_floor(spot_rows)

        per_species: list[SpotSpeciesRollup] = []
        daily: list[DailyRollup] = []

        for sci_name, sp_rows in spot_rows.groupby("scientific_name", sort=True):
            per_species.append(
                SpotSpeciesRollup(
                    spot_key=spot_key,
                    scientific_name=str(sci_name),
                    # A species can appear under name variants; the most frequent
                    # spelling is the least surprising one to display.
                    common_name=str(sp_rows["common_name"].mode().iat[0]),
                    detection_count=int(len(sp_rows)),
                    active_days=int(sp_rows["observation_date"].nunique()),
                    average_confidence=round(float(sp_rows["confidence"].mean()), 4),
                    maximum_confidence=round(float(sp_rows["confidence"].max()), 4),
                    first_detection_date=min(sp_rows["observation_date"]),
                    last_detection_date=max(sp_rows["observation_date"]),
                    activity_rank=0,  # assigned below, once the spot is known
                    hourly_counts=_hourly(sp_rows),
                    daily_counts=_daily_pairs(sp_rows),
                    monthly_counts=_monthly_pairs(sp_rows),
                )
            )
            for d, n in sp_rows.groupby("observation_date").size().sort_index().items():
                daily.append(
                    DailyRollup(
                        spot_key=spot_key,
                        scientific_name=str(sci_name),
                        observation_date=d,
                        detection_count=int(n),
                    )
                )

        # Rank within the spot: 1 is most detected. Ties break on name so the
        # ranking is stable across runs -- otherwise an idempotency test would
        # fail intermittently on equal counts.
        for rank, item in enumerate(
            sorted(per_species, key=lambda s: (-s.detection_count, s.scientific_name)),
            start=1,
        ):
            item.activity_rank = rank

        rollups.append(
            SpotRollup(
                spot_key=spot_key,
                spot_label=str(spot_rows["spot_label"].mode().iat[0]),
                label_variants=sorted(spot_rows["spot_label"].astype(str).unique()),
                species_richness=int(spot_rows["scientific_name"].nunique()),
                total_detections=int(len(spot_rows)),
                active_days=int(spot_rows["observation_date"].nunique()),
                # Prefer the directory count: a spot may hold recordings that
                # produced no detections, and those were still recordings.
                recording_count=int(
                    audio_counts.get(spot_key, spot_rows["filename"].nunique())
                ),
                first_recording_date=min(spot_rows["observation_date"]),
                last_recording_date=max(spot_rows["observation_date"]),
                effective_confidence_floor=floor,
                heterogeneous_floor=heterogeneous,
                species=per_species,
                daily=daily,
            )
        )

    return rollups
