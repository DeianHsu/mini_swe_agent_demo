"""Go 仓库诊断的离线测试；不启动容器或访问模型。"""

import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from scripts import diagnose_pro_v2_go as diagnostic


class GoDiagnosisTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix=".go-diagnostic-test-", dir=diagnostic.ROOT)
        self.root = Path(self.temporary.name).resolve()
        assert self.root.parent == diagnostic.ROOT.resolve()
        self.addCleanup(self.temporary.cleanup)

    def artifact(self, nested=False):
        buffer = io.BytesIO()
        row = {"number": 135, "instance_id": diagnostic.SAMPLES[135] + "a" * 40}
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("checkpoint.json", json.dumps({
                "config": {"dataset_commit": diagnostic.DATASET_COMMIT}, "records": [row]}))
            archive.writestr("model.patch", b"diff\n+\xff\n")
        path = self.root / ("outer.zip" if nested else "case-0135.zip")
        if nested:
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("case-0135.zip", buffer.getvalue())
        else:
            path.write_bytes(buffer.getvalue())
        return path

    def test_reads_actions_artifact_and_web_download_without_changing_patch_bytes(self):
        for nested in (False, True):
            row, patch = diagnostic.read_case_archive(self.artifact(nested), 135)
            self.assertEqual(row["number"], 135)
            self.assertEqual(patch, b"diff\n+\xff\n")

    def test_rejects_artifact_from_another_case(self):
        with self.assertRaises(ValueError):
            diagnostic.read_case_archive(self.artifact(), 213)

    def test_distinguishes_missing_go_from_a_failed_model_patch(self):
        evidence = [{"mode": "oracle-login", "grade": "failed", "go_path": ""},
                    {"mode": "oracle-plain", "grade": "passed", "go_path": "/usr/local/go/bin/go"}]
        self.assertIn("找不到 Go", diagnostic.assess_modes(evidence))
        evidence[0].update(grade="passed", go_path="/usr/local/go/bin/go")
        evidence.append({"mode": "model-login", "grade": "failed", "go_path": "/usr/local/go/bin/go"})
        self.assertIn("检查模型补丁", diagnostic.assess_modes(evidence))

    def test_failed_oracle_does_not_blame_the_model_patch(self):
        evidence = [{"mode": "oracle-login", "grade": "error", "go_path": ""},
                    {"mode": "oracle-plain", "grade": "failed", "go_path": ""}]
        self.assertIn("尚不能", diagnostic.assess_modes(evidence))

    def test_large_raw_log_keeps_the_error_tail(self):
        path = self.root / "stderr.log"
        diagnostic.write_log(path, b"x" * 100000 + b"go: command not found")
        self.assertLess(path.stat().st_size, 66000)
        self.assertTrue(path.read_bytes().endswith(b"go: command not found"))


if __name__ == "__main__":
    unittest.main()
