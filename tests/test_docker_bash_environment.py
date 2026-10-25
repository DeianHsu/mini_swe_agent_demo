"""防止容器启动器通过登录式 Bash 丢失镜像的工具路径；不执行 Docker。"""

import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mini_swe_agent_demo.docker_bash import environment
from mini_swe_agent_demo.docker_bash import run_pro_v2 as core


class DockerEnvironmentTests(unittest.TestCase):
    def test_go_command_uses_the_image_environment(self):
        def simulated_shell(*, args, **kwargs):
            if "-lc" in args:
                return subprocess.CompletedProcess(args, 127, "", "bash: go: command not found")
            return subprocess.CompletedProcess(args, 0, "go version go1.24.3 linux/amd64", "")

        with patch.object(environment.subprocess, "run", side_effect=simulated_shell):
            observation = environment.execute("go version", container_name="offline", workdir="/app")
        self.assertIn("Exit code:0", observation)
        self.assertIn("go1.24.3", observation)

    def test_official_verifier_keeps_go_on_path_and_preserves_raw_logs(self):
        with tempfile.TemporaryDirectory(prefix=".go-verifier-test-", dir=core.PROJECT_ROOT) as directory:
            folder = Path(directory).resolve()
            assert folder.parent == core.PROJECT_ROOT.resolve()
            (folder / "model.patch").write_bytes(b"saved patch bytes")
            task = {"image": "offline-image", "path": str(folder), "cpus": 1, "memory_mb": 4096,
                    "setup_timeout": 10, "verifier_timeout": 30}
            state = {}

            def fake_docker(arguments, **kwargs):
                code, stdout, stderr = 0, b"", b""
                if arguments[0] == "exec" and "bash /tests/test.sh" in arguments[-1]:
                    state["passed"] = "-lc" not in arguments
                    code = 0 if state["passed"] else 1
                    stdout = b"RESULT: PASSED" if state["passed"] else b"RESULT: FAILED"
                elif arguments[0] == "exec" and "git -C /app" in arguments[-1]:
                    stdout = b"/app\n"
                elif arguments[:2] == ["cp", "offline-verifier:/logs/verifier"]:
                    verifier = folder / "verifier"
                    verifier.mkdir()
                    (verifier / "reward.txt").write_text("1" if state["passed"] else "0", encoding="utf-8")
                    (verifier / "run-script-stderr.txt").write_text(
                        "" if state["passed"] else "go: command not found", encoding="utf-8")
                return subprocess.CompletedProcess(arguments, code, stdout, stderr)

            with patch.object(core, "docker", side_effect=fake_docker):
                result = core.verify_patch(task, folder, "offline-verifier")
            self.assertEqual(result["evaluation_status"], "passed")
            self.assertEqual(result["reward"], 1)
            self.assertEqual(result["verifier_shell"], "bash -c")
            self.assertTrue((folder / "verifier/run-script-stderr.txt").is_file())


if __name__ == "__main__":
    unittest.main()
