"""防止容器启动器通过登录式 Bash 丢失镜像的工具路径；不执行 Docker。"""

import subprocess
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from mini_swe_agent_demo.docker_bash import environment
from mini_swe_agent_demo.docker_bash import run_pro_v2 as core


class DockerEnvironmentTests(unittest.TestCase):
    def test_output_limit_keeps_short_output_and_both_ends_of_large_output(self):
        short = "Exit code:0\nSTDOUT:\n正常输出\nSTDERR:\n"
        self.assertEqual(core.limit_observation(short), short)
        long = "start\n" + "中文🙂" * 100000 + "\nlast error"
        limited = core.limit_observation(long)
        self.assertLessEqual(len(limited), core.MAX_OBSERVATION_CHARS)
        self.assertTrue(limited.startswith("start\n"))
        self.assertTrue(limited.endswith("last error"))
        self.assertIn("输出已截断", limited)

    def test_accumulated_outputs_stay_bounded_without_losing_tool_call_pairs(self):
        history = []
        for i in range(30):
            history.extend([{"role": "assistant", "tool_calls": [{"id": str(i)}]},
                            {"role": "tool", "tool_call_id": str(i), "content": str(i) + "x" * 15990}])
        core.trim_tool_history(history)
        tools = history[1::2]
        self.assertLessEqual(sum(len(row["content"]) for row in tools), core.MAX_TOOL_HISTORY_CHARS)
        self.assertEqual([row["tool_call_id"] for row in tools], [str(i) for i in range(30)])
        self.assertTrue(tools[-1]["content"].startswith("29"))
        self.assertEqual(len(history), 60)

    def test_benchmark_worker_survives_multi_megabyte_command_output(self):
        from mini_swe_agent_demo import docker_bash
        import json

        with tempfile.TemporaryDirectory(prefix=".output-test-", dir=core.PROJECT_ROOT) as directory:
            folder = Path(directory)
            (folder / "instruction.md").write_text("修复测试中的问题。", encoding="utf-8")
            core.write_json(folder / "case.json", {
                "path": str(folder), "max_steps": 30, "command_timeout": 180,
                "agent_container": "offline", "workdir": "/app",
            })

            def fake_model(task, history, **kwargs):
                if sum(len(row.get("content", "")) for row in history) > 1048576:
                    raise ValueError("maximum context length exceeded")
                return {"role": "assistant", "content": "finish"}

            module = SimpleNamespace(model=fake_model, execute=None)

            def fake_agent(task, **kwargs):
                observation = module.execute("cat huge.log", container_name="offline", workdir="/app", timeout=180)
                self.assertIn("Exit code:1", observation)
                self.assertIn("STDERR:\nreal compile error", observation)
                history = [{"role": "tool", "tool_call_id": "call-1", "content": observation}]
                history.append(module.model(task, history, workdir="/app"))
                return history

            module.agent = fake_agent
            result = subprocess.CompletedProcess([], 1, b"x" * 8_000_000, b"real compile error")
            with patch.object(docker_bash, "mini_agent", module, create=True), \
                 patch.object(core, "docker", return_value=result):
                core.run_worker(folder)
            info = json.loads((folder / "agent_result.json").read_text(encoding="utf-8"))
            self.assertEqual(info["status"], "finished", info)
            self.assertLess((folder / "trajectory.jsonl").stat().st_size, 20000)

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
