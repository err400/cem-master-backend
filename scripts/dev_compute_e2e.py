#!/usr/bin/env python3
"""Drive the COMPUTE app end to end, then hand off to the master indexer.

    your .wav files
        -> POST /api/v1/projects/upload/audio      (compute app, port 8002)
        -> POST /api/v1/analyze  script=birdnet    (runs BirdNET, SYNCHRONOUS)
        -> POST /api/v1/projects/publish           ("Make public")
        -> the master indexer picks it up from the shared DATA_DIR
        -> spot + species + job rows appear on the master page (port 8000)

WHY DRIVE THE API INSTEAD OF CLICKING THE PAGE
The compute frontend generates js/core/Config.js at build time and wants a
GOOGLE_CLIENT_ID for sign-in. The API itself has no auth -- `_user` just reads
two optional headers -- so the whole flow is reachable without that detour.
Use the page to look at things; use this to make them happen reproducibly.

FILENAMES MATTER MORE THAN THEY LOOK
pipeline/file_metadata.py only understands SPOT_YYYYMMDD_HHMMSS.wav. Anything
else parses as None, and birdnet_predictions.py's date filter then drops the
file with no error:

    lambda fn: (p := parse_filename(str(fn))) is not None and ...

So a recording named `REC001.wav` does not fail loudly -- it just never appears
in the results. This script renames on the way in (from each file's modified
time) and tells you what it did.

    python3 scripts/dev_compute_e2e.py --audio-dir ~/recordings \\
        --project my-test --spot SITE1 --lat 28.5450 --lon 77.1926

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import re
import struct
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta
from pathlib import Path

AUDIO_SUFFIXES = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}

# Mirrors pipeline/file_metadata.py's _FILENAME_RE. Kept deliberately strict:
# a name this does not match is a name the pipeline will silently ignore.
CONVENTION = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_-]*_\d{8}_\d{6}\.[A-Za-z0-9]+$"
)


# --------------------------------------------------------------------------
# HTTP (stdlib multipart, so there is nothing to pip install)
# --------------------------------------------------------------------------

def _post_json(url: str, payload: dict, timeout: float) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "X-User-Email": "dev@local"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode() or "{}")


def _post_multipart(url: str, fields: list[tuple[str, str]],
                    files: list[tuple[str, Path, str]], timeout: float) -> dict:
    """fields: (name, value). files: (field name, path, filename to send as)."""
    boundary = f"----cem{uuid.uuid4().hex}"
    body = bytearray()
    for name, value in fields:
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        body += f"{value}\r\n".encode()
    for name, path, send_as in files:
        ctype = mimetypes.guess_type(send_as)[0] or "application/octet-stream"
        body += f"--{boundary}\r\n".encode()
        body += (
            f'Content-Disposition: form-data; name="{name}"; '
            f'filename="{send_as}"\r\n'.encode()
        )
        body += f"Content-Type: {ctype}\r\n\r\n".encode()
        body += path.read_bytes()
        body += b"\r\n"
    body += f"--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        url,
        data=bytes(body),
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "X-User-Email": "dev@local",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode() or "{}")


def _explain(exc: urllib.error.HTTPError) -> str:
    """FileBrowser taught me this lesson: never print a bare status code."""
    try:
        detail = exc.read().decode().strip()
    except Exception:  # noqa: BLE001
        detail = ""
    return f"HTTP {exc.code}" + (f" -- {detail}" if detail else "")


# --------------------------------------------------------------------------
# Naming
# --------------------------------------------------------------------------

def target_name(path: Path, spot: str) -> tuple[str, bool]:
    """(name to upload as, whether it was renamed).

    A file already following the convention keeps its name -- including its
    spot label, which may differ from --spot. Renaming those would silently
    reassign real field data to the wrong site.
    """
    if CONVENTION.match(path.name):
        return path.name, False
    stamp = datetime.fromtimestamp(path.stat().st_mtime)
    return f"{spot}_{stamp:%Y%m%d}_{stamp:%H%M%S}{path.suffix.lower()}", True


def deduplicate(plan: list[tuple[Path, str, bool]]) -> list[tuple[Path, str, bool]]:
    """Push colliding generated names forward a second at a time.

    Files copied together often share an mtime to the second, so several would
    generate the SAME name. The upload endpoint skips a name that already
    exists, so the extras would vanish -- reported as "skipped", which reads
    like success. Only generated names are adjusted; a name that already
    followed the convention is real metadata and is left alone.
    """
    seen: set[str] = set()
    out: list[tuple[Path, str, bool]] = []
    for src, name, renamed in plan:
        if name in seen and renamed:
            stem, _, suffix = name.rpartition(".")
            base, date_part, time_part = stem.rsplit("_", 2)
            t = datetime.strptime(date_part + time_part, "%Y%m%d%H%M%S")
            while name in seen:
                t += timedelta(seconds=1)
                name = f"{base}_{t:%Y%m%d}_{t:%H%M%S}.{suffix}"
        seen.add(name)
        out.append((src, name, renamed))
    return out


# --------------------------------------------------------------------------
# GUANO — the recorder already knows where it was
# --------------------------------------------------------------------------

def read_guano(path: Path) -> dict[str, str]:
    """Key/value metadata from a WAV's GUANO chunk, {} if there is none.

    Wildlife Acoustics Song Meters write a `guan` RIFF chunk holding, among
    other things, `Loc Position: <lat> <lon>` from the recorder's GPS. Reading
    it beats asking a human to type coordinates: it cannot be mistyped, it
    cannot be attached to the wrong spot, and it is captured at the moment of
    recording rather than remembered afterwards.
    """
    try:
        with open(path, "rb") as fh:
            if fh.read(4) != b"RIFF":
                return {}
            fh.seek(12)
            while True:
                header = fh.read(8)
                if len(header) < 8:
                    return {}
                chunk_id, size = struct.unpack("<4sI", header)
                if chunk_id == b"guan":
                    out: dict[str, str] = {}
                    for line in fh.read(size).decode("utf-8", "replace").splitlines():
                        if ":" in line:
                            key, _, value = line.partition(":")
                            out[key.strip()] = value.strip()
                    return out
                # RIFF chunks are word-aligned; an odd size is followed by a pad
                # byte. Skipping it desynchronises every later chunk.
                fh.seek(size + (size % 2), 1)
    except (OSError, struct.error):
        return {}


def guano_position(meta: dict[str, str]) -> tuple[float, float] | None:
    raw = meta.get("Loc Position") or ""
    parts = raw.split()
    if len(parts) != 2:
        return None
    try:
        lat, lon = float(parts[0]), float(parts[1])
    except ValueError:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    # 0,0 is in the Gulf of Guinea. A recorder reporting it has no GPS fix, and
    # treating that as a location would put the spot in the ocean.
    if lat == 0 and lon == 0:
        return None
    return lat, lon


def parse_date(name: str) -> str | None:
    """The file's date as COMPACT YYYYMMDD -- the form the API compares against.

    ⚠️ Not ISO. projects.py filters uploads with a plain STRING comparison:

        fd = self._parse_date_from_filename(p.name)   # -> "20260131"
        if end_date and fd > end_date: continue

    Send "2026-01-31" and every file is dropped, because "20260131" sorts
    after it ('0' is 0x30, '-' is 0x2D). The result is a 409 saying no audio
    matches the range, for audio that is sitting right there. The compute
    frontend gets this right by doing `startDate.replace(/-/g, '')` before it
    posts; there is nothing on the server that would catch the mistake.
    """
    m = re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]*_(\d{8})_", name)
    return m.group(1) if m else None


def to_iso(compact: str) -> str:
    """20260131 -> 2026-01-31, for display only."""
    return f"{compact[:4]}-{compact[4:6]}-{compact[6:]}"


# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--audio-dir", required=True, help="folder of your recordings")
    p.add_argument("--project", default="e2e-test")
    p.add_argument("--spot", default="SITE1", help="spot label for files that need renaming")
    p.add_argument("--lat", type=float, default=None,
                   help="override; by default coordinates come from each file's "
                        "GUANO metadata (Song Meter GPS)")
    p.add_argument("--lon", type=float, default=None)
    p.add_argument("--api", default="http://localhost:8002")
    p.add_argument("--limit", type=int, default=5,
                   help="upload at most N files (BirdNET is slow; default 5)")
    p.add_argument("--min-confidence", default=None)
    p.add_argument("--timeout", type=float, default=3600,
                   help="seconds to wait for BirdNET; /analyze is SYNCHRONOUS")
    p.add_argument("--dry-run", action="store_true",
                   help="show what would be uploaded and stop")
    args = p.parse_args(argv)

    if (args.lat is None) != (args.lon is None):
        print("error: pass both --lat and --lon, or neither", file=sys.stderr)
        return 2
    if args.lat is not None and not (-90 <= args.lat <= 90 and -180 <= args.lon <= 180):
        print("error: --lat/--lon out of range", file=sys.stderr)
        return 2

    audio_dir = Path(args.audio_dir).expanduser().resolve()
    if not audio_dir.is_dir():
        print(f"error: {audio_dir} is not a directory", file=sys.stderr)
        return 2

    found = sorted(
        p for p in audio_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in AUDIO_SUFFIXES
    )
    found = [p for p in found if p.stat().st_size > 0]
    if not found:
        print(f"error: no non-empty audio files under {audio_dir}", file=sys.stderr)
        return 2

    selected = found[: args.limit]
    plan = deduplicate([(p, *target_name(p, args.spot)) for p in selected])

    print(f"{len(found)} audio file(s) found, uploading {len(selected)}:\n")
    for src, name, renamed in plan:
        mb = src.stat().st_size / 1e6
        note = "  (renamed from " + src.name + ")" if renamed else ""
        print(f"  {name}  {mb:.1f} MB{note}")

    dates = sorted({d for _, n, _ in plan if (d := parse_date(n))})
    spots = sorted({n.split("_")[0] for _, n, _ in plan})
    print(f"\n  spots: {', '.join(spots)}")
    print(
        f"  dates: {to_iso(dates[0])} .. {to_iso(dates[-1])}  "
        f"(sent as {dates[0]}/{dates[-1]})"
        if dates else "  dates: NONE"
    )

    # ---- coordinates -----------------------------------------------------
    # Resolved PER SPOT, because one run can cover several recorders. An
    # explicit --lat/--lon overrides every spot, which is only right when there
    # is one of them.
    geo: dict[str, tuple[float, float]] = {}
    if args.lat is not None:
        geo = {s: (args.lat, args.lon) for s in spots}
        source = "--lat/--lon"
        if len(spots) > 1:
            print(
                f"\n  warning: --lat/--lon applied to all {len(spots)} spots, so they\n"
                "           will stack on one point. Omit them to use each\n"
                "           recording's own GPS instead.",
                file=sys.stderr,
            )
    else:
        source = "GUANO metadata"
        per_spot: dict[str, list[tuple[float, float]]] = {}
        for src, name, _ in plan:
            position = guano_position(read_guano(src))
            if position:
                per_spot.setdefault(name.split("_")[0], []).append(position)
        for spot_name, positions in per_spot.items():
            distinct = set(positions)
            # Do NOT average disagreeing fixes: the midpoint of two real places
            # is a third place that nothing was recorded at.
            if len(distinct) > 1:
                print(
                    f"\n  warning: {spot_name} reports {len(distinct)} different GPS\n"
                    "           positions. Using the most common; pass --lat/--lon to\n"
                    "           decide yourself.",
                    file=sys.stderr,
                )
            geo[spot_name] = max(distinct, key=positions.count)

    missing = [s for s in spots if s not in geo]
    if missing:
        print(
            f"\nerror: no coordinates for {', '.join(missing)}.\n"
            "       These files carry no GPS in their GUANO metadata, and the\n"
            "       master page cannot place a spot without them. Pass --lat/--lon\n"
            "       explicitly -- but only real ones. A spot indexed at 0,0 lands\n"
            "       in the Gulf of Guinea and looks like data rather than a gap.",
            file=sys.stderr,
        )
        return 2

    print(f"\n  coordinates (from {source}):")
    for spot_name in spots:
        lat, lon = geo[spot_name]
        print(f"    {spot_name}: {lat}, {lon}")

    if args.dry_run:
        print("\n(dry run -- nothing uploaded)")
        return 0

    api = args.api.rstrip("/")

    # ---- 1. upload -------------------------------------------------------
    print(f"\n[1/3] uploading to {api} ...")
    try:
        for src, name, _ in plan:
            spot_of = name.split("_")[0]
            r = _post_multipart(
                f"{api}/api/v1/projects/upload/audio",
                [("project", args.project), ("spot", spot_of)],
                [("files", src, name)],
                timeout=600,
            )
            state = "skipped (already there)" if r.get("skipped") else "ok"
            print(f"  {name}: {state}")
    except urllib.error.HTTPError as exc:
        print(f"error: upload failed: {_explain(exc)}", file=sys.stderr)
        return 2
    except urllib.error.URLError as exc:
        print(
            f"error: cannot reach the compute API at {api} -- {exc}\n"
            "       Start it: cd ../cem-backend && docker compose up -d api",
            file=sys.stderr,
        )
        return 2

    # ---- 2. run BirdNET --------------------------------------------------
    job_id = f"e2e-{int(time.time())}"
    payload = {
        "script": "birdnet",
        "job_id": job_id,
        "project": args.project,
        "spots": spots,
        "spots_geo": [
            {"name": s, "lat": geo[s][0], "lon": geo[s][1]} for s in spots
        ],
    }
    if dates:
        payload["start_date"] = dates[0]
        payload["end_date"] = dates[-1]
    if args.min_confidence is not None:
        payload["min_confidence"] = args.min_confidence

    print(f"\n[2/3] running BirdNET as job {job_id} ...")
    print("      /analyze is SYNCHRONOUS -- this blocks until the run finishes.")
    started = time.time()
    try:
        result = _post_json(f"{api}/api/v1/analyze", payload, timeout=args.timeout)
    except urllib.error.HTTPError as exc:
        print(f"error: analyze failed: {_explain(exc)}", file=sys.stderr)
        return 2
    print(f"      done in {time.time() - started:.0f}s")

    # ---- 3. publish ------------------------------------------------------
    print("\n[3/3] publishing ...")
    try:
        pub = _post_json(
            f"{api}/api/v1/projects/publish", {"project": args.project}, timeout=120
        )
    except urllib.error.HTTPError as exc:
        print(
            f"error: publish refused: {_explain(exc)}\n"
            "\n"
            "       409 here is the publish guard doing its job -- it requires a\n"
            "       COMPLETED server-side BirdNET job AND dataset/aggregate.csv.\n"
            "       If BirdNET found nothing, there is no aggregate to publish.\n"
            f"       Check the run: {api}/api/v1/jobs/{job_id}",
            file=sys.stderr,
        )
        return 2

    print(f"      visibility={pub.get('visibility')} "
          f"retention_hours={pub.get('retention_hours')}")

    print(
        "\nNow the master side:\n"
        "  cd ../cem-master-backend && ./scripts/reindex.sh\n"
        "\n"
        f"  then open http://localhost:8000 and look for '{spots[0]}'.\n"
        "\n"
        "If the spot is missing, check in this order:\n"
        "  1. did BirdNET detect anything?   "
        f"{api}/api/v1/jobs/{job_id}/results\n"
        "  2. is the project public?         "
        "grep visibility $CEM_DATA_DIR_HOST/projects/"
        f"{args.project}/project.json\n"
        "  3. does the indexer see it?       ./scripts/reindex.sh --project "
        f"{args.project} --dry-run"
    )
    if not result.get("job_id") and not result.get("status"):
        print("\nnote: /analyze returned an unexpected shape:\n"
              f"  {json.dumps(result)[:400]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
