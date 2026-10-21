"""本地串行运行 SWE-bench Pro V2；使用原项目的 agent()，由用户手动启动。"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread
import time
import tomllib
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TASKS = PROJECT_ROOT.parent / "SWE-bench-Pro-V2" / "v2" / "tasks"
DEFAULT_OUTPUT = PROJECT_ROOT / "pro_v2_runs" / "full"


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )
    temporary.replace(path)


def docker(arguments, *, timeout=120, check=True):
    result = subprocess.run(
        ["docker", *map(str, arguments)],
        capture_output=True, timeout=timeout,
    )
    if check and result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"Docker 命令失败：{' '.join(map(str, arguments[:4]))}\n{detail[-4000:]}")
    return result


def load_tasks(root, instances=None):
    tasks = []
    for path in sorted(root.iterdir()):
        if not path.is_dir() or not (path / "task.toml").is_file():
            continue
        if instances and path.name not in instances:
            continue
        cfg = tomllib.loads((path / "task.toml").read_text(encoding="utf-8"))
        if cfg["agent"]["network_mode"] != "no-network" or cfg["verifier"]["network_mode"] != "public":
            raise ValueError(f"不支持这道题的网络配置：{path.name}")
        tasks.append({
            "instance_id": path.name,
            "path": str(path.resolve()),
            "image": cfg["environment"]["docker_image"],
            "cpus": cfg["environment"]["cpus"],
            "memory_mb": cfg["environment"]["memory_mb"],
            "setup_timeout": cfg["environment"].get("build_timeout_sec", 1800),
            "agent_timeout": cfg["agent"]["timeout_sec"],
            "verifier_timeout": cfg["verifier"]["timeout_sec"],
        })
    if not tasks:
        raise ValueError(f"没有找到题目：{root}")
    if instances and set(instances) != {task["instance_id"] for task in tasks}:
        raise ValueError("指定的题号中有目录不存在或缺少 task.toml。")
    return tasks


def run_worker(case_dir):
    """独立进程内调用现有智能体，让父进程能够限制整题运行时间。"""
    case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    history_ref = []
    info = {"status": "error", "model_rounds": 0}
    trace = case_dir / "trajectory.jsonl"
    try:
        from mini_swe_agent_demo.docker_bash import mini_agent as agent_module

        original_model = agent_module.model

        def record(kind, data):
            with trace.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps({"kind": kind, "data": data}, ensure_ascii=False) + "\n")

        def model(task, history, workdir="/workspace"):
            nonlocal history_ref
            history_ref = history
            info["model_rounds"] += 1
            print(f"  模型第 {info['model_rounds']}/{case['max_steps']} 轮", flush=True)
            message = original_model(task, history, workdir=workdir)
            record("assistant", message)
            return message

        def execute(command, *, container_name, workdir, timeout):
            # 限制容器内的命令；只限制 Windows 客户端等待不能终止容器里的进程。
            try:
                result = docker([
                    "exec", "-w", workdir, container_name,
                    "timeout", "-k", "5", str(timeout), "bash", "-lc", command,
                ], timeout=timeout + 15, check=False)
                observation = (
                    f"Exit code:{result.returncode}\nSTDOUT:\n"
                    + result.stdout.decode("utf-8", errors="replace")
                    + "\nSTDERR:\n"
                    + result.stderr.decode("utf-8", errors="replace")
                )
            except (subprocess.TimeoutExpired, OSError) as error:
                observation = f"Error: process failed: {error}"
            record("execution", {"command": command, "observation": observation})
            return observation

        agent_module.model = model
        agent_module.execute = execute
        instruction = Path(case["path"], "instruction.md").read_text(encoding="utf-8")
        task = (
            f"代码仓库位于 {case['workdir']}，操作环境是断网的 Linux Bash 容器。\n"
            "请使用容器中已有的工具和依赖，先复现问题，再修改源码并验证。\n"
            "保留已有测试文件，临时复现脚本放在 /tmp。\n"
            "保留代码修改，不创建 Git 提交。完成后回复 finish。\n\n"
            + instruction
        )
        history_ref = agent_module.agent(
            task, container_name=case["agent_container"], workdir=case["workdir"],
            timeout=case["command_timeout"], max_steps=case["max_steps"],
        )
        finished = (
            bool(history_ref)
            and history_ref[-1].get("role") == "assistant"
            and not history_ref[-1].get("tool_calls")
        )
        info["status"] = "finished" if finished else "step_limit"
    except Exception as error:
        info["error"] = f"{type(error).__name__}: {error}"
        info["provider_error"] = type(error).__name__ in {
            "AuthenticationError", "PermissionDeniedError", "NotFoundError",
            "APIConnectionError", "APITimeoutError", "RateLimitError",
        }
        print(f"  智能体异常：{info['error']}", flush=True)
    finally:
        write_json(case_dir / "history.json", history_ref)
        write_json(case_dir / "agent_result.json", info)


def wait_for_worker(case_dir, timeout):
    with (case_dir / "agent.log").open("w", encoding="utf-8", newline="\n") as log:
        child = subprocess.Popen(
            [sys.executable, "-X", "utf8", "-u", str(Path(__file__).resolve()), "--worker", str(case_dir)],
            cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )

        def relay():
            for line in child.stdout:
                log.write(line)
                log.flush()
                print(line, end="", flush=True)

        reader = Thread(target=relay, daemon=True)
        reader.start()
        timed_out = False
        try:
            child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            print("  达到整题时间上限，停止智能体并保留当前补丁。", flush=True)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=10)
            reader.join(timeout=10)
        if timed_out:
            return {"status": "time_limit"}
        result_path = case_dir / "agent_result.json"
        if result_path.is_file():
            return json.loads(result_path.read_text(encoding="utf-8"))
        return {"status": "error", "error": f"智能体子进程退出码：{child.returncode}"}


def grade_verifier(exit_code, reward, output):
    """区分官方测试失败、执行异常和通过，避免把基础设施故障当成通过。"""
    if exit_code == 0 and reward == "1" and "RESULT: PASSED" in output:
        return "passed", 1
    if exit_code == 1 and reward == "0" and "RESULT: FAILED" in output:
        return "failed", 0
    return "error", None


def run_case(task, case_dir, prefix, args):
    case_dir.mkdir(parents=True)
    started = time.monotonic()
    agent_name, verifier_name = prefix + "-agent", prefix + "-verify"
    containers = []
    image_preexisting = True
    result = {
        "instance_id": task["instance_id"], "case_dir": str(case_dir),
        "agent": {"status": "not_started"},
        "evaluation_status": "error", "reward": None,
    }
    try:
        image_preexisting = docker(
            ["image", "inspect", task["image"]], check=False,
        ).returncode == 0
        # 只清理本次运行命名空间中上次中断遗留的容器。
        for name in (agent_name, verifier_name):
            docker(["rm", "-f", name], check=False)
        resources = ["--cpus", task["cpus"], "--memory", f"{task['memory_mb']}m"]
        containers.append(agent_name)
        print("  准备断网的智能体容器……", flush=True)
        docker([
            "run", "-d", "--name", agent_name, "--user", "root", *resources,
            "--network", "none", "--entrypoint", "sleep", task["image"], "infinity",
        ], timeout=task["setup_timeout"])
        workdir = docker([
            "exec", agent_name, "bash", "-lc",
            "git -C /app rev-parse --show-toplevel 2>/dev/null "
            "|| git -C /testbed rev-parse --show-toplevel",
        ]).stdout.decode("utf-8").strip()
        base_head = docker([
            "exec", "-w", workdir, agent_name, "git", "rev-parse", "HEAD",
        ]).stdout.decode("ascii").strip()
        case = {
            **task, "workdir": workdir, "agent_container": agent_name,
            "base_head": base_head, "max_steps": args.max_steps,
            "command_timeout": args.command_timeout,
        }
        write_json(case_dir / "case.json", case)
        result["agent"] = wait_for_worker(case_dir, task["agent_timeout"])
        # 先终止所有容器内进程，再只启动 sleep，导出稳定的文件修改。
        docker(["stop", "--time", "1", agent_name])
        docker(["start", agent_name])
        patch = docker([
            "exec", "-w", workdir, agent_name, "bash", "-lc",
            f"git add -A && git diff --cached --binary {base_head}",
        ]).stdout
        (case_dir / "model.patch").write_bytes(patch)
        docker(["rm", "-f", agent_name])
        containers.remove(agent_name)
        result["patch_bytes"] = len(patch)
        if result["agent"].get("provider_error"):
            result["error"] = "模型服务未能正常完成请求：" + result["agent"].get("error", "")
            return result

        print("  在全新容器中应用补丁并运行官方验证脚本……", flush=True)
        containers.append(verifier_name)
        docker([
            "run", "-d", "--name", verifier_name, "--user", "root", *resources,
            "--network", "bridge", "--entrypoint", "sleep", task["image"], "infinity",
        ], timeout=task["setup_timeout"])
        docker(["cp", str(Path(task["path"]) / "tests"), verifier_name + ":/"])
        if patch:
            docker(["cp", str(case_dir / "model.patch"), verifier_name + ":/tmp/model.patch"])
            applied = docker([
                "exec", "-w", workdir, verifier_name,
                "git", "apply", "--binary", "/tmp/model.patch",
            ], check=False)
            (case_dir / "patch_apply.log").write_bytes(applied.stdout + applied.stderr)
            if applied.returncode:
                result.update(evaluation_status="failed", reward=0, reason="patch_apply_failed")
                return result
        duration = int(task["verifier_timeout"])
        verified = docker([
            "exec", "-w", workdir, verifier_name, "bash", "-lc",
            f"mkdir -p /logs/verifier && timeout -k 30 {duration} bash /tests/test.sh",
        ], timeout=duration + 60, check=False)
        output = (verified.stdout + verified.stderr).decode("utf-8", errors="replace")
        (case_dir / "verifier.log").write_bytes(verified.stdout + verified.stderr)
        docker(["cp", verifier_name + ":/logs/verifier", str(case_dir)], check=False)
        reward_path = case_dir / "verifier" / "reward.txt"
        reward = reward_path.read_text(encoding="utf-8").strip() if reward_path.exists() else ""
        status, value = grade_verifier(verified.returncode, reward, output)
        result.update(evaluation_status=status, reward=value, verifier_exit_code=verified.returncode)
        if status == "error":
            result["error"] = "验证未正常完成，请查看 verifier.log 和 verifier/ 下的日志。"
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
    finally:
        for name in containers:
            try:
                docker(["rm", "-f", name], check=False)
            except Exception as error:
                print(f"  容器清理失败：{name}：{error}", flush=True)
        if not image_preexisting and not args.keep_images:
            try:
                docker(["image", "rm", task["image"]], check=False)
            except Exception as error:
                print(f"  镜像清理失败：{error}", flush=True)
        result["seconds"] = round(time.monotonic() - started, 2)
    return result


def write_reports(output_dir, records, total):
    counts = {
        name: sum(row["evaluation_status"] == name for row in records)
        for name in ("passed", "failed", "error")
    }
    summary = {
        "total": total, "processed": len(records), "pending": total - len(records),
        **counts, "resolved_rate_total": counts["passed"] / total,
    }
    write_json(output_dir / "summary.json", summary)
    (output_dir / "results.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records),
        encoding="utf-8", newline="\n",
    )
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks-dir", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-steps", type=int, default=30)
    parser.add_argument("--command-timeout", type=int, default=180)
    parser.add_argument("--instance", action="append", help="仅用于单题排错；默认运行全部题目。")
    parser.add_argument("--plan", action="store_true", help="只查看计划，不调用模型或 Docker。")
    parser.add_argument("--retry-errors", action="store_true", help="重跑评测执行异常的题目，不重跑已判失败的题目。")
    parser.add_argument("--keep-images", action="store_true", help="保留本次新下载的题目镜像。")
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        run_worker(args.worker)
        return
    if args.max_steps <= 0 or args.command_timeout <= 0:
        parser.error("轮数和命令超时必须大于 0。")
    args.tasks_dir = args.tasks_dir.resolve()
    args.output_dir = args.output_dir.resolve()
    tasks = load_tasks(args.tasks_dir, args.instance)
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
    print(f"题目数：{len(tasks)}；串行运行；每题最多 {args.max_steps} 轮模型调用。")
    print(f"模型：{os.getenv('DEEPSEEK_MODEL', 'deepseek-flash')}；配置来源：{PROJECT_ROOT / '.env'}")
    print("每题时间上限读取 task.toml；智能体断网，验证使用全新联网容器。")
    print(f"结果目录：{args.output_dir}", flush=True)
    if args.plan:
        return

    if not os.getenv("DEEPSEEK_API_KEY"):
        parser.error("请先在原项目 .env 中配置 DEEPSEEK_API_KEY。")
    config = {
        "tasks_dir": str(args.tasks_dir),
        "dataset_commit": subprocess.run(
            ["git", "-C", str(args.tasks_dir), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip(),
        "instance_ids": [task["instance_id"] for task in tasks],
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
        "base_url": os.getenv("DEEPSEEK_BASE_URL"),
        "max_steps": args.max_steps, "command_timeout": args.command_timeout,
    }
    config_path = args.output_dir / "run_config.json"
    if config_path.exists():
        previous = json.loads(config_path.read_text(encoding="utf-8"))
        if any(previous.get(key) != value for key, value in config.items()):
            parser.error("配置与已有运行不同，请使用新的 --output-dir，避免混合不同实验。")
        prefix = previous["container_prefix"]
    else:
        prefix = "pro2-" + uuid4().hex[:10]
        write_json(config_path, {**config, "container_prefix": prefix})
    records = {}
    for index in range(1, len(tasks) + 1):
        path = args.output_dir / "cases" / f"{index:04d}" / "result.json"
        if path.exists():
            records[index] = json.loads(path.read_text(encoding="utf-8"))
    write_reports(args.output_dir, list(records.values()), len(tasks))
    try:
        for index, task in enumerate(tasks, start=1):
            case_root = args.output_dir / "cases" / f"{index:04d}"
            result_path = case_root / "result.json"
            previous_result = records.get(index)
            print(f"\n[{index}/{len(tasks)}] {task['instance_id']}", flush=True)
            if previous_result and not (
                args.retry_errors and previous_result["evaluation_status"] == "error"
            ):
                print(f"  已有结果，跳过：{previous_result['evaluation_status']}", flush=True)
            else:
                case_dir = case_root / ("attempt-" + uuid4().hex[:8])
                result = run_case(task, case_dir, f"{prefix}-{index:04d}", args)
                write_json(result_path, result)
                records[index] = result
                print(f"  结果：{result['evaluation_status']}；奖励：{result['reward']}", flush=True)
            summary = write_reports(args.output_dir, list(records.values()), len(tasks))
            print(
                f"  累计：通过 {summary['passed']}，未通过 {summary['failed']}，"
                f"执行异常 {summary['error']}，待处理 {summary['pending']}", flush=True,
            )
            current = records[index]
            if current.get("error"):
                print(f"  详情：{current['error']}", flush=True)
            if current["agent"].get("provider_error"):
                print("模型服务异常，已停止批量运行。处理后使用 --retry-errors 继续。")
                break
    except KeyboardInterrupt:
        print("\n已中断。再次执行相同命令将跳过已有结果；当前未完成题目会重新开始。")
    print(f"汇总：{args.output_dir / 'summary.json'}")


if __name__ == "__main__":
    main()
