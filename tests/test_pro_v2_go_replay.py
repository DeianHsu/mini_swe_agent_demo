"""已有补丁重评的离线测试，确保缺失补丁不触发模型或新容器。"""

import argparse
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import replay_pro_v2_go as replay


class GoReplayTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix=".go-replay-test-", dir=replay.ci.ROOT)
        self.root = Path(self.temporary.name).resolve()
        assert self.root.parent == replay.ci.ROOT.resolve()
        self.addCleanup(self.temporary.cleanup)
        self.instance = replay.diagnostic.SAMPLES[135] + "a" * 40
        self.config = {"dataset_commit": replay.diagnostic.DATASET_COMMIT}
        self.row = {"number": 135, "instance_id": self.instance, "github_run_id": replay.SOURCE_RUN_ID,
                    "agent": {"status": "finished", "model_rounds": 12}, "evaluation_status": "failed"}
        self.plan = self.root / "plan.json"
        ids = [f"unused-{i}" for i in range(136)]
        ids[134] = self.instance
        replay.ci.core.write_json(self.plan, {"config": self.config, "all_instance_ids": ids,
                                             "selected": [135], "records": [self.row]})

    def artifact(self, include_patch=True):
        path = self.root / "case-0135.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("checkpoint.json", json.dumps({"config": self.config, "records": [self.row]}))
            if include_patch:
                archive.writestr("model.patch", b"exact saved patch\n")
        return path

    def test_replay_only_runs_the_verifier_and_keeps_source_provenance(self):
        args = argparse.Namespace(plan=self.plan, number=135, case_archive=self.artifact(),
                                  tasks_dir=self.root, output=self.root / "result", plan_only=False)
        class Images:
            def __init__(self, *args, **kwargs): pass
            def stage(self, *args): pass
            def wait(self, *args): pass
            def close(self): pass
            def download_image(self, image): return image

        with patch.object(replay.ci.core, "ImageCache", Images), \
             patch.object(replay.ci.core, "load_tasks", return_value=[{"image": "offline-image"}]), \
             patch.object(replay.ci.core, "verify_patch", return_value={"evaluation_status": "passed", "reward": 1,
                                                                      "verifier_shell": "bash -c"}) as verifier, \
             patch.object(replay.ci.core, "run_case", side_effect=AssertionError("不得启动智能体")), \
             patch.dict(os.environ, {"GITHUB_RUN_ID": "new-run"}):
            replay.run(args)
        verifier.assert_called_once()
        self.assertEqual((args.output / "case/model.patch").read_bytes(), b"exact saved patch\n")
        result = replay.ci.read_json(args.output / "checkpoint.json")["records"][0]
        self.assertEqual(result["evaluation_status"], "passed")
        self.assertEqual(result["evaluation_method"], "patch_replay")
        self.assertEqual(result["replay_source_run_id"], replay.SOURCE_RUN_ID)
        self.assertEqual(result["github_run_id"], "new-run")

    def test_missing_saved_patch_is_error_without_starting_docker(self):
        args = argparse.Namespace(plan=self.plan, number=135, case_archive=self.artifact(False),
                                  tasks_dir=self.root, output=self.root / "result", plan_only=False)
        with patch.object(replay.ci.core, "ImageCache", side_effect=AssertionError("不得拉取镜像")):
            replay.run(args)
        result = replay.ci.read_json(args.output / "checkpoint.json")["records"][0]
        self.assertEqual(result["evaluation_status"], "error")
        self.assertIsNone(result["reward"])
        self.assertEqual(result["reason"], "missing_saved_patch")


if __name__ == "__main__":
    unittest.main()
