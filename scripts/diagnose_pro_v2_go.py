"""重放 Flipt/Vuls 的已存补丁，检查 Bash 启动方式；不导入或调用模型。"""

import argparse
from collections import Counter
import io
import json
import os
from pathlib import Path
import re
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from mini_swe_agent_demo.docker_bash import run_pro_v2 as core

SAMPLES = {135: "instance_flipt-io__flipt-", 213: "instance_future-architect__vuls-"}
DATASET_COMMIT = "66f92766bba642462d4bbe5479e83f91f9211862"
MODES = [(patch, shell) for patch in ("oracle", "model") for shell in ("login", "plain")]
PROBE = r"""
printf 'WORKDIR='; pwd
printf 'PATH=%s\n' "$PATH"
go_bin="$(command -v go || true)"
printf 'GO_PATH=%s\n' "$go_bin"
printf 'GO_VERSION='; go version 2>&1 || true
printf '\n--- Go environment ---\n'
go env GOROOT GOPATH GOMOD GOWORK GOTOOLCHAIN GOFLAGS 2>&1 || true
printf '\n--- module files ---\n'
find . -maxdepth 3 -name go.mod -print | head -25
""".strip()


class MissingPatchError(ValueError):
    pass


def read_case_archive(path, number, expected_instance=None):
    """兼容 Actions 下载后的内层 ZIP，以及从网页下载的外层产物 ZIP。"""
    payload = Path(path).read_bytes()
    for _ in range(2):
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            if "checkpoint.json" in archive.namelist():
                checkpoint = json.loads(archive.read("checkpoint.json"))
                rows = checkpoint["records"]
                if (len(rows) != 1 or rows[0]["number"] != number
                        or not rows[0]["instance_id"].startswith(tuple(SAMPLES.values()))
                        or (expected_instance is not None and rows[0]["instance_id"] != expected_instance)
                        or checkpoint["config"]["dataset_commit"] != DATASET_COMMIT):
                    raise ValueError("产物与指定题号或固定数据集不匹配。")
                if "model.patch" not in archive.namelist():
                    raise MissingPatchError("原产物未保存 model.patch，无法原样重放；不重新调用模型或猜测补丁。")
                return rows[0], archive.read("model.patch")
            nested = [name for name in archive.namelist() if name.endswith(".zip")]
            if len(nested) != 1:
                raise ValueError("无法找到单题产物中的 checkpoint.json。")
            payload = archive.read(nested[0])
    raise ValueError("单题产物 ZIP 嵌套层数超出预期。")


def write_log(path, content):
    # 每个诊断文本最多保存末尾 64 KiB，避免编译日志占满产物存储。
    if len(content) > 65536:
        content = b"[Only the last 65536 bytes retained]\n" + content[-65536:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def assess_modes(results):
    by_mode = {row["mode"]: row for row in results}
    login, plain = by_mode.get("oracle-login", {}), by_mode.get("oracle-plain", {})
    if login.get("grade") != "passed" and plain.get("grade") == "passed":
        if not login.get("go_path") and plain.get("go_path"):
            return "参考补丁在非登录式 Bash 下通过；登录式 Bash 找不到 Go，已定位到启动环境/PATH 差异。"
        return "参考补丁只在非登录式 Bash 下通过，已确认 Shell 启动环境影响验证，需比较 environment.log。"
    if login.get("grade") == "passed":
        if by_mode.get("model-login", {}).get("grade") == "passed":
            return "原启动方式下参考补丁和已有模型补丁均通过，需继续排查旧运行与当前环境差异。"
        return "原启动方式下参考补丁通过，已有模型补丁未通过；此样本应继续检查模型补丁或编译错误。"
    return "参考补丁未能通过对照；请检查原始标准输出/错误，尚不能用此诊断给模型补丁定性。"


def replay(task, patch_file, output, prefix, patch_kind, shell, phase_timeout):
    mode = f"{patch_kind}-{shell}"
    folder = output / mode
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{prefix}-{mode}"
    flag = "-lc" if shell == "login" else "-c"
    result = {"mode": mode, "grade": "error", "go_path": "", "reward": None}
    print(f"开始对照：{mode}（全新容器）", flush=True)
    try:
        core.docker([
            "run", "-d", "--pull", "never", "--name", name, "--user", "root",
            "--cpus", task["cpus"], "--memory", f"{task['memory_mb']}m",
            "--network", "bridge", "--entrypoint", "sleep", task["image"], "infinity",
        ], timeout=120)
        workdir = core.docker([
            "exec", name, "bash", "-c",
            "git -C /app rev-parse --show-toplevel 2>/dev/null || git -C /testbed rev-parse --show-toplevel",
        ]).stdout.decode("utf-8").strip()
        probed = core.docker([
            "exec", "-w", workdir, name, "timeout", "-k", "5", "45", "bash", flag, PROBE,
        ], timeout=60, check=False)
        environment = (probed.stdout + probed.stderr).decode("utf-8", errors="replace")
        write_log(folder / "environment.log", environment.encode("utf-8"))
        matched = re.search(r"^GO_PATH=(.*)$", environment, re.MULTILINE)
        result["go_path"] = matched.group(1).strip() if matched else ""
        core.docker(["cp", str(Path(task["path"]) / "tests"), name + ":/"])
        if patch_kind == "oracle":
            core.docker(["cp", str(Path(task["path"]) / "solution"), name + ":/"])
            applied = core.docker([
                "exec", "-w", workdir, name, "timeout", "-k", "10", str(phase_timeout),
                "bash", flag, "bash /solution/solve.sh",
            ], timeout=phase_timeout + 30, check=False)
        else:
            core.docker(["cp", str(patch_file), name + ":/tmp/model.patch"])
            applied = core.docker([
                "exec", "-w", workdir, name, "git", "apply", "--binary", "/tmp/model.patch",
            ], check=False)
        write_log(folder / "patch-apply.log", applied.stdout + applied.stderr)
        if applied.returncode:
            result["error"] = f"补丁应用未完成，退出码 {applied.returncode}"
            return result
        verified = core.docker([
            "exec", "-w", workdir, name, "bash", flag,
            f"mkdir -p /logs/verifier && timeout -k 30 {phase_timeout} bash /tests/test.sh",
        ], timeout=phase_timeout + 60, check=False)
        log = verified.stdout + verified.stderr
        write_log(folder / "verifier.log", log)
        core.docker(["cp", name + ":/logs/verifier", str(folder)], check=False)
        reward_path = folder / "verifier/reward.txt"
        reward = reward_path.read_text(encoding="utf-8").strip() if reward_path.is_file() else ""
        result["grade"], result["reward"] = core.grade_verifier(
            verified.returncode, reward, log.decode("utf-8", errors="replace"))
        result["exit_code"] = verified.returncode
        parsed = folder / "verifier/output.json"
        if parsed.is_file():
            result["parsed_tests"] = dict(Counter(
                row.get("status", "UNKNOWN") for row in json.loads(parsed.read_text(encoding="utf-8"))["tests"]))
        for path in (folder / "verifier").glob("*.txt"):
            write_log(path, path.read_bytes())
        return result
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
        return result
    finally:
        try:
            core.docker(["rm", "-f", name], check=False)
        except Exception as error:
            result["cleanup_error"] = f"{type(error).__name__}: {error}"
        core.write_json(folder / "result.json", result)
        print(f"{mode}：{result['grade']}，Go={result['go_path'] or '未找到'}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks-dir", type=Path, required=True)
    parser.add_argument("--case-archive", type=Path, required=True)
    parser.add_argument("--number", type=int, choices=list(SAMPLES), required=True)
    parser.add_argument("--output", type=Path, default=Path("go-diagnosis"))
    parser.add_argument("--phase-timeout", type=int, default=900)
    parser.add_argument("--plan", action="store_true", help="只检查产物和对照计划，不运行 Docker。")
    args = parser.parse_args()
    if not 1 <= args.phase_timeout <= 3000:
        parser.error("单次验证时限必须在 1–3000 秒之间。")
    row, patch = read_case_archive(args.case_archive, args.number)
    task = core.load_tasks(args.tasks_dir, [row["instance_id"]])[0]
    print(f"样本 {args.number}：{task['instance_id']}；来源运行 {row.get('github_run_id')}")
    print("对照：参考补丁/已有模型补丁 × 登录式/非登录式 Bash；不调用模型，不写入正式成绩。")
    if args.plan:
        return
    args.output.mkdir(parents=True, exist_ok=False)
    patch_file = args.output / "model.patch"
    patch_file.write_bytes(patch)
    images = core.ImageCache(args.output / "image-cache.json", workers=1)
    results = []
    try:
        images.stage([(args.number, task)])
        images.wait(task["image"])
        inspected = core.docker(["image", "inspect", task["image"]])
        config = json.loads(inspected.stdout)[0]["Config"]
        core.write_json(args.output / "image-environment.json", {
            "image": task["image"], "working_dir": config.get("WorkingDir"),
            "go_environment": [value for value in config.get("Env", [])
                               if value.split("=", 1)[0] in {"PATH", "GOROOT", "GOPATH", "GOTOOLCHAIN", "GOFLAGS"}],
        })
        prefix = f"pro2diag-{os.environ.get('GITHUB_RUN_ID', 'manual')}-{args.number}"
        for patch_kind, shell in MODES:
            results.append(replay(task, patch_file, args.output, prefix, patch_kind, shell, args.phase_timeout))
    finally:
        images.close()
    conclusion = assess_modes(results)
    core.write_json(args.output / "diagnosis.json", {
        "number": args.number, "instance_id": task["instance_id"], "source_run_id": row.get("github_run_id"),
        "phase_timeout_sec": args.phase_timeout, "results": results, "conclusion": conclusion,
    })
    report = (f"## Go 仓库诊断：第 {args.number} 题\n\n"
              "仅重放补丁，不调用模型；诊断结果不合并到正式成绩。\n\n"
              "| 补丁与 Shell | 验证结果 | Go 路径 |\n| --- | --- | --- |\n"
              + "".join(f"| {r['mode']} | {r['grade']} | {r['go_path'] or '未找到'} |\n" for r in results)
              + f"\n{conclusion}\n\n每次验证上限 {args.phase_timeout} 秒；超时不能直接判定环境或补丁错误。"
              "原始输出位于各对照目录的 verifier/ 中。\n")
    (args.output / "summary.md").write_text(report, encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write(report)
    print(conclusion)


if __name__ == "__main__":
    main()
