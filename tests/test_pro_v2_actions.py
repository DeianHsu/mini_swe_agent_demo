"""云端调度的离线测试；不调用 Docker、GitHub 或模型接口。"""

import argparse
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from scripts import pro_v2_actions as ci


class ActionsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix=".actions-test-", dir=ci.ROOT)
        self.root = Path(self.temporary.name).resolve()
        assert self.root.parent == ci.ROOT.resolve() and self.root.name.startswith(".actions-test-")
        self.addCleanup(self.temporary.cleanup)
        self.config = {"dataset_commit": "test-revision", "model": "deepseek-flash",
                       "base_url": "https://api.deepseek.com", "max_steps": 30, "command_timeout": 180}
        self.ids = ["task-1", "task-2", "task-3"]

    def row(self, number, state="passed", newer=False):
        return {"instance_id": self.ids[number - 1], "number": number,
                "evaluation_status": state, "reward": 1 if state == "passed" else 0 if state == "failed" else None,
                "agent": {"status": "finished"}, "source": "actions" if newer else "local",
                "updated_at": "2026-10-25T00:00:00+00:00" if newer else "2026-10-21T00:00:00+00:00"}

    def checkpoint(self, rows):
        return {"config": self.config, "total": len(self.ids), "records": rows}

    def fixture_plan(self):
        path = self.root / "plan.json"
        ci.core.write_json(path, {"config": self.config, "all_instance_ids": self.ids,
                                  "records": [], "selected": [1]})
        return path

    def test_real_baseline_skips_scored_and_retries_download_errors(self):
        baseline = ci.read_json(ci.ROOT / "benchmarks/pro_v2/baseline.json")
        # 基线无需本地大体积日志，也不依赖任务仓库仍在本机。
        scored = {row["number"] for row in baseline["records"] if row["evaluation_status"] in ci.VALID_RESULTS}
        self.assertEqual(len(scored), 117)
        all_ids = [None] * baseline["total"]
        for row in baseline["records"]:
            all_ids[row["number"] - 1] = row["instance_id"]
        for index, instance in enumerate(all_ids):
            if instance is None:
                all_ids[index] = f"future-task-{index + 1}"
        selected = ci.select_numbers(all_ids, baseline["records"], 200)
        self.assertEqual(selected[:3], [102, 110, 120])
        self.assertEqual(len(selected), 200)
        self.assertTrue(scored.isdisjoint(selected))
        with self.assertRaises(ValueError):
            ci.select_numbers(all_ids, [], 257)

    def test_merge_reads_case_archives_and_takes_latest_result(self):
        base = self.checkpoint([self.row(1), self.row(2, "error")])
        fresh = self.checkpoint([self.row(2, "failed", newer=True)])
        (self.root / "case-0002.zip").write_bytes(ci.archive_bytes(fresh, {}))
        records = ci.merge_records(self.config, base, ci.checkpoints(self.root), self.ids)
        self.assertEqual([row["evaluation_status"] for row in records], ["passed", "failed"])

    def test_task_numbering_matches_windows_on_case_sensitive_paths(self):
        names = ["instance_NodeBB__NodeBB-b", "instance_element__web-c", "instance_ansible__ansible-a"]
        config = (
            '[agent]\nnetwork_mode="no-network"\ntimeout_sec=3000\n'
            '[verifier]\nnetwork_mode="public"\ntimeout_sec=3000\n'
            '[environment]\ndocker_image="ghcr.io/example:test"\ncpus=1\nmemory_mb=4096\n'
        )
        class LinuxEntry:
            def __init__(self, path):
                self.path = path
                self.name = path.name
            def __lt__(self, other):
                return self.name < other.name
            def is_dir(self):
                return True
            def __truediv__(self, other):
                return self.path / other
            def resolve(self):
                return self.path.resolve()

        entries = []
        for name in names:
            path = self.root / name
            path.mkdir()
            (path / "task.toml").write_text(config, encoding="utf-8")
            entries.append(LinuxEntry(path))
        root = SimpleNamespace(iterdir=lambda: entries)
        self.assertEqual([row["instance_id"] for row in ci.core.load_tasks(root)],
                         [names[2], names[1], names[0]])

    def test_merge_rejects_different_model_or_unknown_task(self):
        other = self.checkpoint([self.row(1)])
        other["config"] = {**self.config, "model": "another-model"}
        with self.assertRaises(ValueError):
            ci.merge_records(self.config, self.checkpoint([]), [other], self.ids)
        other = self.checkpoint([{**self.row(1), "instance_id": "unknown-task"}])
        with self.assertRaises(ValueError):
            ci.merge_records(self.config, self.checkpoint([]), [other], self.ids)

    def test_restore_skips_empty_prepare_failure_and_uses_earlier_results(self):
        replies = [
            [{"databaseId": 100}, {"databaseId": 99}],
            {"artifacts": []},
            {"jobs": [{"name": "prepare", "conclusion": "failure"}]},
            {"artifacts": [{"name": "pro-v2-summary", "expired": False}]},
        ]
        output = self.root / "resume"
        responses = [SimpleNamespace(stdout=json.dumps(item)) for item in replies] + [SimpleNamespace()]
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo", "GITHUB_REF_NAME": "master"}), \
             patch.object(ci.subprocess, "run", side_effect=responses) as gh:
            ci.restore(argparse.Namespace(selection="latest", output=output))
        self.assertEqual(gh.call_args.args[0][:4], ["gh", "run", "download", "99"])

    def test_restore_does_not_reset_scored_run_with_missing_artifacts(self):
        replies = [[{"databaseId": 100}], {"artifacts": []},
                   {"jobs": [{"name": "prepare", "conclusion": "success"}]}]
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo", "GITHUB_REF_NAME": "master"}), \
             patch.object(ci.subprocess, "run", side_effect=[SimpleNamespace(stdout=json.dumps(x)) for x in replies]) as gh:
            with self.assertRaises(ValueError):
                ci.restore(argparse.Namespace(selection="latest", output=self.root / "resume"))
        self.assertFalse(any(call.args[0][1:3] == ["run", "download"] for call in gh.call_args_list))

    def test_restore_uses_baseline_when_only_prepare_failed(self):
        replies = [[{"databaseId": 100}], {"artifacts": []},
                   {"jobs": [{"name": "prepare", "conclusion": "failure"}]}]
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo", "GITHUB_REF_NAME": "master"}), \
             patch.object(ci.subprocess, "run", side_effect=[SimpleNamespace(stdout=json.dumps(x)) for x in replies]) as gh:
            ci.restore(argparse.Namespace(selection="latest", output=self.root / "resume"))
        self.assertEqual(gh.call_count, 3)

    def test_archive_limit_and_secret_redaction(self):
        plan = self.fixture_plan()
        output = self.root / "run"
        (output / "case").mkdir(parents=True)
        record = self.row(1)
        record["error"] = "failure TEST_SECRET_FOR_REDACTION"
        ci.core.write_json(output / "checkpoint.json", self.checkpoint([record]))
        (output / "case/model.patch").write_bytes(os.urandom(1024 * 1024))
        (output / "case/agent_result.json").write_text('{"error":"TEST_SECRET_FOR_REDACTION"}', encoding="utf-8")
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "TEST_SECRET_FOR_REDACTION"}):
            ci.pack(argparse.Namespace(plan=plan, number=1, output=output, artifacts=self.root / "artifacts"))
        archive_path = self.root / "artifacts/case-0001.zip"
        self.assertLessEqual(archive_path.stat().st_size, ci.ARCHIVE_LIMIT)
        with zipfile.ZipFile(archive_path) as archive:
            checkpoint = json.loads(archive.read("checkpoint.json"))
            self.assertIn("model.patch", checkpoint["omitted_files"])
            self.assertNotIn(b"TEST_SECRET_FOR_REDACTION", archive.read("agent_result.json"))
            self.assertNotIn(b"TEST_SECRET_FOR_REDACTION", archive.read("checkpoint.json"))

    def test_small_patch_bytes_are_preserved(self):
        plan = self.fixture_plan()
        output = self.root / "run"
        (output / "case").mkdir(parents=True)
        ci.core.write_json(output / "checkpoint.json", self.checkpoint([self.row(1)]))
        payload = b"diff\n+\xff\xfe\n"
        (output / "case/model.patch").write_bytes(payload)
        ci.pack(argparse.Namespace(plan=plan, number=1, output=output, artifacts=self.root / "artifacts"))
        with zipfile.ZipFile(self.root / "artifacts/case-0001.zip") as archive:
            self.assertEqual(archive.read("model.patch"), payload)

    def test_interrupted_case_is_error_not_test_failure(self):
        plan = self.fixture_plan()
        ci.pack(argparse.Namespace(plan=plan, number=1, output=self.root / "missing", artifacts=self.root / "artifacts"))
        checkpoint = next(ci.checkpoints(self.root / "artifacts"))
        self.assertEqual(checkpoint["records"][0]["evaluation_status"], "error")
        self.assertIsNone(checkpoint["records"][0]["reward"])

    def test_scored_rate_does_not_count_infrastructure_errors(self):
        summary = ci.summarize({"all_instance_ids": self.ids}, [self.row(1), self.row(2, "error")])
        self.assertEqual(summary["pass_rate_scored"], 1)
        self.assertEqual(summary["remaining_to_evaluate"], 2)
        self.assertEqual(summary["pending"], 1)

    def test_next_batch_is_automatic_but_bounded_and_stops_on_errors(self):
        healthy = {"remaining_to_evaluate": 325, "batch_received": 200,
                   "batch_errors": 0, "batch_missing": 0}
        second = ci.next_batch_inputs(healthy, 1, 200, 20, "123")
        self.assertEqual(second["batch_number"], 2)
        self.assertEqual(second["resume_run_id"], "123")
        self.assertEqual(second["parallelism"], "20")
        self.assertTrue(second["auto_continue"])
        self.assertEqual(ci.next_batch_inputs(healthy, 2, 200, 20, "124")["batch_number"], 3)
        self.assertIsNone(ci.next_batch_inputs(healthy, 3, 200, 20, "125"))
        for change in ({"batch_errors": 1}, {"batch_missing": 1}, {"remaining_to_evaluate": 0}):
            self.assertIsNone(ci.next_batch_inputs({**healthy, **change}, 1, 200, 20, "123"))

    def test_batch_progress_only_counts_this_runs_records(self):
        data = {"selected": [1, 2]}
        fresh = {**self.row(1, newer=True), "github_run_id": "new"}
        old = {**self.row(2, "error", newer=True), "github_run_id": "old"}
        progress = ci.batch_progress(data, [fresh, old], "new")
        self.assertEqual(progress["batch_received"], 1)
        self.assertEqual(progress["batch_missing"], 1)
        self.assertEqual(progress["batch_errors"], 0)

    def test_dispatch_passes_current_checkpoint_to_next_run(self):
        summary = self.root / "summary.json"
        ci.core.write_json(summary, {"remaining_to_evaluate": 325, "batch_received": 200,
                                     "batch_errors": 0, "batch_missing": 0})
        args = argparse.Namespace(summary=summary, batch_number=1, batch_size=200, parallelism=20)
        environment = {"GITHUB_RUN_ID": "123", "GITHUB_REF_NAME": "master",
                       "GITHUB_REPOSITORY": "DeianHsu/mini_swe_agent_demo",
                       "GITHUB_STEP_SUMMARY": str(self.root / "step.md")}
        with patch.dict(os.environ, environment), patch.object(ci.subprocess, "run") as api:
            ci.dispatch_next(args)
        self.assertIn("dispatches", api.call_args.args[0][4])
        payload = ci.read_json(self.root / "next-batch.json")
        self.assertEqual(payload["ref"], "master")
        self.assertEqual(payload["inputs"]["resume_run_id"], "123")
        self.assertEqual(payload["inputs"]["batch_number"], 2)

    def test_normal_failure_continues_but_agent_error_stops_matrix(self):
        class FakeImages:
            def __init__(self, *args, **kwargs):
                pass
            def stage(self, *args):
                pass
            def close(self):
                pass

        plan = self.fixture_plan()
        args = argparse.Namespace(plan=plan, number=1, output=self.root / "run", tasks_dir=self.root)
        environment = {"DEEPSEEK_API_KEY": "offline-only", "DEEPSEEK_MODEL": self.config["model"],
                       "DEEPSEEK_BASE_URL": self.config["base_url"]}
        for state, expected_code in (("finished", 0), ("error", 2)):
            result = {"instance_id": "task-1", "evaluation_status": "failed", "reward": 0,
                      "agent": {"status": state, "error": "mock failure"}}
            with patch.dict(os.environ, environment), patch.object(ci.core, "ImageCache", FakeImages), \
                 patch.object(ci.core, "load_tasks", return_value=[{"instance_id": "task-1"}]), \
                 patch.object(ci.core, "run_case", return_value=result), \
                 patch.object(ci.shutil, "disk_usage", return_value=SimpleNamespace(free=20 * 1024 ** 3)):
                self.assertEqual(ci.run_one(args), expected_code)
            row = ci.read_json(args.output / "checkpoint.json")["records"][0]
            self.assertEqual(row["evaluation_status"], "failed" if state == "finished" else "error")


if __name__ == "__main__":
    unittest.main()
