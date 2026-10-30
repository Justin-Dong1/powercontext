import importlib.util, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from sdd_context import generate, parse_changes, project_data
from replay_evidence import replay


class Contracts(unittest.TestCase):
    def test_mock_cannot_use_remote_endpoint(self):
        with self.assertRaises(ValueError):
            generate({}, "https://example.com/messages", "model", True)

    def test_live_cannot_send_key_to_non_minimax(self):
        with patch.dict("os.environ", {"MINIMAX_API_KEY": "test-secret"}):
            with self.assertRaises(ValueError):
                generate({}, "https://example.com/messages", "model", False)

    def test_empty_file_map_rejected(self):
        with self.assertRaises(ValueError):
            parse_changes('{"files":{}}')

    def test_list_not_accepted_as_file_map(self):
        with self.assertRaises(ValueError):
            parse_changes('{"files":[]}')

    def test_source_escape_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)
            (p / "project").mkdir()
            (p / "outside.py").write_text("private", encoding="utf8")
            (p / "project/context.json").write_text(
                json.dumps({"sources": [{"path": "../outside.py", "kind": "code"}]}),
                encoding="utf8",
            )
            with self.assertRaises(ValueError):
                project_data(p / "project")

    def test_mock_cannot_be_replayed_as_real_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)
            (p / "context.json").write_text("{}", encoding="utf8")
            (p / "model-record.json").write_text(
                '{"actual_minimax":false,"provider":"protocol_mock"}', encoding="utf8"
            )
            with self.assertRaises(ValueError):
                replay(p, p / "output")

    def test_changes_in_source_change_revision(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)
            (p / "spec.md").write_text("old", encoding="utf8")
            (p / "context.json").write_text(
                json.dumps({"sources": [{"path": "spec.md", "kind": "spec"}]}),
                encoding="utf8",
            )
            old = project_data(p)[2]
            (p / "spec.md").write_text("new", encoding="utf8")
            self.assertNotEqual(old, project_data(p)[2])


if __name__ == "__main__":
    unittest.main()
