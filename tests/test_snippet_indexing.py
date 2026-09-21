import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

from app.indexer.source import read_species_snippets
from app.indexer.writer import IndexReport
from app.routes.indexer import index_project


class SnippetIndexingTests(unittest.TestCase):
    def test_manual_index_includes_snippets_and_commits(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            data = Path(directory)
            snippets_dir = data / "projects" / "test" / "snippets"
            snippets_dir.mkdir(parents=True)
            snippets = {"SPOT_Bird": {"snippet_rel_path": "snippets/SPOT_Bird.wav"}}
            (snippets_dir / "species_snippets.json").write_text(json.dumps({"species": snippets}))
            for name, value in {
                "is_project_public": True, "read_aggregate": pd.DataFrame({"confidence": [0.9]}),
                "read_geo": {}, "count_audio_files": {}, "list_jobs": [],
                "read_migratory": ({}, {}), "read_acoustic_indices": {},
                "read_species_iucn_cache": {},
            }.items():
                stack.enter_context(patch("app.routes.indexer.source." + name, return_value=value))
            stack.enter_context(patch("app.routes.indexer.rollups.build", return_value=[]))
            writer = stack.enter_context(patch("app.routes.indexer.write",
                                              return_value=IndexReport(project="test", snippets_indexed=1)))
            db = MagicMock()
            response = index_project("test", {}, db, SimpleNamespace(data_dir=data))
            self.assertEqual(writer.call_args.kwargs["snippets"], snippets)
            db.commit.assert_called_once()
            self.assertEqual(response["report"]["snippets_indexed"], 1)

    def test_malformed_snippet_metadata_returns_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            target = data / "projects" / "test" / "snippets" / "species_snippets.json"
            target.parent.mkdir(parents=True)
            for payload in ['{', '[]', '{"species": ["invalid"]}']:
                target.write_text(payload)
                self.assertEqual(read_species_snippets(data, "test"), {})


if __name__ == "__main__":
    unittest.main()
