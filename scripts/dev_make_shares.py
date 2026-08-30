#!/usr/bin/env python3
"""Mint REAL FileBrowser shares for jobs already on disk. Development only.

WHY THIS EXISTS
The fixture's job.json carries share hashes like ``aBcD1234``. They are
invented, so the master page renders an "Open" link that 404s -- which tests
the plumbing but not the thing you actually care about. Getting a real hash
normally means running a real BirdNET analysis, which needs audio, models and
patience.

This script is the shortcut: it does exactly what
``cem-backend/server/app/runner.py`` does after a step succeeds -- create a
FileBrowser share for that step's output directory and record it under
``shares`` in job.json -- without running the analysis.

It stands in for the compute app, so it WRITES into DATA_DIR. That is the one
thing the indexer must never do. Never point this at production data; it is
guarded to refuse anything that does not look like a dev fixture unless you
pass --force.

USAGE
    # 1. both stacks must share one DATA_DIR on the host
    export CEM_DATA_DIR_HOST=/absolute/path/to/cem-backend/data

    # 2. build the fixture into it
    python3 tests/fixtures/build_fixture.py --out "$CEM_DATA_DIR_HOST"

    # 3. start FileBrowser (cem-backend/docker-compose.yml, port 8097)
    # 4. mint the shares
    python3 scripts/dev_make_shares.py --data-dir "$CEM_DATA_DIR_HOST"

    # 5. reindex with links switched on
    FILEBROWSER_PUBLIC_URL=http://localhost:8097 ./scripts/reindex.sh

Standard library only, like build_fixture.py -- no virtualenv needed.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

# Mirrors cem-backend/server/app/pipeline_meta.py. birdnet is the one step whose
# real outputs live in work/ rather than results/<step>/, so runner.py shares
# work/ for it. Diverging here would produce links to an empty directory.
BIRDNET = "birdnet"


def login(base_url: str, username: str, password: str) -> str:
    """POST /api/login returns a raw JWT as the body, not JSON."""
    body = json.dumps(
        {"username": username, "password": password, "recaptcha": ""}
    ).encode()
    req = urllib.request.Request(
        f"{base_url}/api/login",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read().decode().strip()


def create_share(base_url: str, token: str, rel: str) -> dict:
    """POST /api/share/<path> -> {hash, path, expire, hasPassword}.

    The `{}` body is required. FileBrowser decodes the request body and treats
    the io.EOF from an empty one as an error, so a bodyless POST returns 400.
    `{}` takes the defaults: no password, no expiry.
    """
    url = f"{base_url}/api/share/{quote(rel.lstrip('/'), safe='/')}"
    req = urllib.request.Request(
        url,
        data=b"{}",
        method="POST",
        headers={"X-Auth": token, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def share_dir_for(job_root: Path, step: str) -> Path:
    """The directory runner.py would share for this step."""
    return job_root / "work" if step == BIRDNET else job_root / "results" / step


def steps_of(meta: dict) -> list[str]:
    """Steps this job ran, from tasks[], falling back to its script name."""
    steps = [t.get("step") for t in (meta.get("tasks") or []) if t.get("step")]
    if steps:
        return sorted(set(steps))
    return [meta["script"]] if meta.get("script") else []


def looks_like_a_fixture(data_dir: Path) -> bool:
    """A crude guard, on purpose. This script writes into DATA_DIR, and the one
    directory it must never touch is a real deployment's."""
    projects = data_dir / "projects"
    if not projects.is_dir():
        return False
    names = [p.name for p in projects.iterdir() if p.is_dir()]
    return bool(names) and all(
        "fixture" in n or "demo" in n or "test" in n for n in names
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, help="the shared DATA_DIR on the host")
    parser.add_argument("--filebrowser-url", default="http://localhost:8097")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin")
    parser.add_argument("--project", help="limit to one project")
    parser.add_argument(
        "--force",
        action="store_true",
        help="write even if DATA_DIR does not look like a dev fixture",
    )
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir).resolve()
    projects_root = data_dir / "projects"
    if not projects_root.is_dir():
        print(f"error: {data_dir} has no projects/ directory", file=sys.stderr)
        return 2

    if not args.force and not looks_like_a_fixture(data_dir):
        print(
            f"error: {data_dir} does not look like a dev fixture.\n"
            "       This script WRITES into DATA_DIR, which the compute app owns.\n"
            "       Projects found: "
            + ", ".join(sorted(p.name for p in projects_root.iterdir() if p.is_dir()))
            + "\n       Pass --force only if you are certain.",
            file=sys.stderr,
        )
        return 2

    base_url = args.filebrowser_url.rstrip("/")
    try:
        token = login(base_url, args.username, args.password)
    except urllib.error.HTTPError as exc:
        # HTTPError subclasses URLError, so it MUST be caught first -- otherwise
        # a rejected password is reported as "cannot reach", which sends you off
        # debugging the container instead of the credentials.
        if exc.code in (401, 403):
            print(
                f"error: FileBrowser rejected the login for user "
                f"{args.username!r} (HTTP {exc.code}).\n"
                "\n"
                "       Recent FileBrowser images generate a RANDOM admin password on\n"
                "       first start instead of using admin/admin. Find it with:\n"
                "           cd ../cem-backend && docker compose logs filebrowser | grep -i password\n"
                "\n"
                "       Then either pass it:\n"
                f"           python3 scripts/dev_make_shares.py --data-dir {data_dir} \\\n"
                "               --password '<that password>'\n"
                "       or set a known one:\n"
                "           docker compose exec filebrowser \\\n"
                "               filebrowser users update admin --password admin\n"
                "\n"
                "       ⚠️ The compute app hits the same wall: its FILEBROWSER_PASSWORD\n"
                "       defaults to 'admin', so runner.py's share creation fails silently\n"
                "       (it is best-effort and only logs a warning). Whatever password you\n"
                "       settle on must also be set there.",
                file=sys.stderr,
            )
        else:
            print(f"error: FileBrowser login failed: HTTP {exc.code}", file=sys.stderr)
        return 2
    except urllib.error.URLError as exc:
        print(
            f"error: cannot reach FileBrowser at {base_url} -- {exc}\n"
            "       Start it: cd ../cem-backend && docker compose up -d filebrowser",
            file=sys.stderr,
        )
        return 2

    projects = [args.project] if args.project else sorted(
        p.name for p in projects_root.iterdir() if p.is_dir()
    )

    minted = skipped = 0
    for project in projects:
        for job_json in sorted((projects_root / project).glob("*/*/job.json")):
            meta = json.loads(job_json.read_text())
            job_root = job_json.parent
            shares = meta.get("shares") or {}

            for step in steps_of(meta):
                target = share_dir_for(job_root, step)
                if not target.is_dir():
                    print(f"  skip {project}/{job_root.name}/{step}: {target.name}/ missing")
                    skipped += 1
                    continue
                # FileBrowser's root IS DATA_DIR (mounted at /srv), so share
                # paths are relative to it -- exactly as runner.py computes them.
                rel = str(target.relative_to(data_dir))
                try:
                    share = create_share(base_url, token, rel)
                except urllib.error.HTTPError as exc:
                    # FileBrowser puts the reason in the body; printing only the
                    # status code sent me hunting for the wrong bug once already.
                    detail = ""
                    try:
                        detail = exc.read().decode().strip()
                    except Exception:  # noqa: BLE001 - diagnostics only
                        pass
                    print(
                        f"  FAIL {rel}: HTTP {exc.code}"
                        + (f" -- {detail}" if detail else ""),
                        file=sys.stderr,
                    )
                    skipped += 1
                    continue
                shares[step] = share
                minted += 1
                print(f"  {project}/{job_root.name}/{step} -> {base_url}/share/{share['hash']}")

            meta["shares"] = shares
            job_json.write_text(json.dumps(meta, indent=2))

    print(f"\n{minted} share(s) minted, {skipped} skipped.")
    if minted:
        print(
            "Now reindex so the hashes reach the database:\n"
            f"  FILEBROWSER_PUBLIC_URL={base_url} ./scripts/reindex.sh"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
