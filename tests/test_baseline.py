"""骨架回归测试。以下小型 CSV 均为人工测试夹具，不是业务数据或测验结果。"""

import csv
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from download_data import DataValidationError, inspect_csv, prepare_dataset, verify_file
from run_all import run_steps


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.data = self.root / "data"
        self.fixture = self.source / "example.csv"
        with self.fixture.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerows([["id", "comment"], ["001", "第一行\n第二行"], ["002", "正常"]])
        self.expected = inspect_csv(self.fixture)
        self.spec = {"handle": "test/fixture/versions/1", "files": [
            {"source": "example.csv", "target": "example.csv", **self.expected}]}

    def test_multiline_is_one_record_and_preserves_identifier(self):
        self.assertEqual(self.expected["rows"], 2)
        with self.fixture.open(encoding="utf-8", newline="") as stream:
            self.assertEqual(list(csv.reader(stream))[1][0], "001")

    def test_truncated_and_duplicate_headers_are_rejected(self):
        for content in ("id,comment\n001\n", "id,id\n1,2\n", "id,comment\n"):
            with self.subTest(content=content):
                path = self.root / "bad.csv"
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(DataValidationError):
                    inspect_csv(path)

    def test_changed_content_with_same_size_and_rows_is_rejected(self):
        path = self.root / "changed.csv"
        path.write_bytes(self.fixture.read_bytes().replace(b"001", b"999"))
        with self.assertRaisesRegex(DataValidationError, "sha256"):
            verify_file(path, self.expected)

    def test_download_uses_pinned_source_and_reuses_verified_files(self):
        with patch("download_data.fetch_dataset", return_value=self.source) as fetch:
            result = prepare_dataset("fixture", self.spec, self.data)
            fetch.assert_called_once_with("test/fixture/versions/1")
            self.assertEqual(result["files"][0]["action"], "downloaded")
        before = (self.data / "example.csv").stat().st_mtime_ns
        with patch("download_data.fetch_dataset", side_effect=AssertionError("不应联网")):
            result = prepare_dataset("fixture", self.spec, self.data, offline=True)
        self.assertEqual(result["files"][0]["action"], "verified_existing")
        self.assertEqual((self.data / "example.csv").stat().st_mtime_ns, before)

    def test_offline_missing_files_fail_without_network(self):
        with patch("download_data.fetch_dataset") as fetch:
            with self.assertRaises(FileNotFoundError):
                prepare_dataset("fixture", self.spec, self.data, offline=True)
            fetch.assert_not_called()

    def test_corrupt_existing_input_is_not_silently_overwritten(self):
        self.data.mkdir()
        path = self.data / "example.csv"
        broken = b"id,comment\n001,wrong\n"
        path.write_bytes(broken)
        with patch("download_data.fetch_dataset") as fetch:
            with self.assertRaises(DataValidationError):
                prepare_dataset("fixture", self.spec, self.data)
            fetch.assert_not_called()
        self.assertEqual(path.read_bytes(), broken)

    def test_bad_download_never_becomes_official_input(self):
        self.fixture.write_text("id,comment\n001,wrong\n", encoding="utf-8")
        with patch("download_data.fetch_dataset", return_value=self.source):
            with self.assertRaises(DataValidationError):
                prepare_dataset("fixture", self.spec, self.data)
        self.assertFalse((self.data / "example.csv").exists())
        self.assertEqual(list(self.data.iterdir()), [])

    def test_failure_does_not_prevent_independent_step(self):
        called = []
        def fail():
            raise DataValidationError("测试夹具错误")
        def succeed():
            called.append(True)
            return {"fixture": True}
        results, code = run_steps([("broken", fail), ("independent", succeed)])
        self.assertEqual(code, 1)
        self.assertEqual([r["status"] for r in results], ["failed", "passed"])
        self.assertEqual(called, [True])

    def test_unimplemented_is_not_success(self):
        results, code = run_steps([("q1", None)])
        self.assertEqual(code, 2)
        self.assertEqual(results[0]["status"], "not_implemented")

    def test_completed_scope_returns_zero(self):
        _, code = run_steps([("fixture", lambda: {"fixture": True})])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
