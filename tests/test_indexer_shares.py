"""FileBrowser share reading and URL building.

Pure filesystem/string work, so no database is needed -- these run on a fresh
clone. The database-backed half (that the URLs actually land in
``analysis_jobs``) lives in test_indexer_writer.py.

The thing under test is small but easy to get wrong in a way that is invisible:
every failure mode here produces a link that looks fine in the API response and
404s in the visitor's browser.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from app.indexer.source import JobRef, share_url


def _job(tmp_path: Path, meta: dict, script: str = "birdnet") -> JobRef:
    root = tmp_path / script / "job-0001"
    root.mkdir(parents=True)
    (root / "job.json").write_text(json.dumps(meta))
    return JobRef(job_id="job-0001", script=script, root=root)


# --- share_url ------------------------------------------------------------

def test_share_url_builds_the_filebrowser_path():
    url = share_url("http://localhost:8097", {"hash": "aBcD1234"})
    assert url == "http://localhost:8097/share/aBcD1234"


def test_share_url_tolerates_a_trailing_slash_on_the_base():
    # Config strips one already; this guards the direct callers.
    assert share_url("http://x/", {"hash": "h"}) == "http://x/share/h"


@pytest.mark.parametrize(
    "base, share",
    [
        ("", {"hash": "h"}),        # FileBrowser not configured
        ("http://x", None),         # job has no share at all
        ("http://x", {}),           # share record present but empty
        ("http://x", {"hash": ""}), # hash blank
    ],
)
def test_share_url_returns_none_rather_than_a_broken_link(base, share):
    assert share_url(base, share) is None


def test_share_url_drops_an_expired_share():
    past = time.time() - 60
    assert share_url("http://x", {"hash": "h", "expire": past}) is None


def test_share_url_keeps_a_share_expiring_in_the_future():
    future = time.time() + 3600
    assert share_url("http://x", {"hash": "h", "expire": future}) is not None


def test_expire_zero_means_never_not_epoch():
    """0 is FileBrowser's 'no expiry'. Comparing it as a timestamp would read
    as 1970 and silently drop every permanent share -- the whole feature."""
    assert share_url("http://x", {"hash": "h", "expire": 0}) is not None


# --- JobRef.shares / primary_share ---------------------------------------

def test_shares_reads_the_block_from_job_json(tmp_path):
    job = _job(tmp_path, {"shares": {"birdnet": {"hash": "h1", "expire": 0}}})
    assert job.shares() == {"birdnet": {"hash": "h1", "expire": 0}}


def test_shares_is_empty_when_the_key_is_absent(tmp_path):
    assert _job(tmp_path, {"id": "job-0001"}).shares() == {}


def test_shares_ignores_malformed_records(tmp_path):
    job = _job(tmp_path, {"shares": {
        "good": {"hash": "h"},
        "no_hash": {"path": "/x"},
        "not_a_dict": "h2",
    }})
    assert set(job.shares()) == {"good"}


def test_shares_survives_unreadable_job_json(tmp_path):
    root = tmp_path / "birdnet" / "job-0001"
    root.mkdir(parents=True)
    (root / "job.json").write_text("{ not json")
    assert JobRef("job-0001", "birdnet", root).shares() == {}


def test_primary_share_prefers_the_jobs_own_step(tmp_path):
    job = _job(tmp_path, {"shares": {
        "heatmaps": {"hash": "other"},
        "birdnet": {"hash": "mine"},
    }}, script="birdnet")
    assert job.primary_share()["hash"] == "mine"


def test_primary_share_falls_back_when_the_step_name_does_not_match(tmp_path):
    job = _job(tmp_path, {"shares": {"heatmaps": {"hash": "other"}}},
               script="birdnet")
    assert job.primary_share()["hash"] == "other"


def test_primary_share_is_none_with_no_shares(tmp_path):
    assert _job(tmp_path, {}).primary_share() is None


# --- JobRef.input_files ---------------------------------------------------

def test_input_files_lists_the_audio_the_job_consumed(tmp_path):
    job = _job(tmp_path, {})
    (job.root / "input").mkdir()
    (job.root / "input" / "audio_spots.json").write_text(
        json.dumps({"b.wav": "SITE_A", "a.wav": "SITE_B"})
    )
    assert job.input_files() == ["a.wav", "b.wav"]  # sorted, deterministic


def test_input_files_is_empty_when_the_mapping_is_missing(tmp_path):
    assert _job(tmp_path, {}).input_files() == []
