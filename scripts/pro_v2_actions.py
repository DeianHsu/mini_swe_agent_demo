"""GitHub Actions 的任务选择、单题执行和结果归并；默认不运行评测。"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from mini_swe_agent_demo.docker_bash import run_pro_v2 as core

CONFIG_KEYS = ("dataset_commit", "model", "base_url", "max_steps", "command_timeout")
VALID_RESULTS = {"passed", "failed"}
ARCHIVE_LIMIT = 512 * 1024


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def timestamp(seconds=None):
    value = datetime.now(timezone.utc) if seconds is None else datetime.fromtimestamp(seconds, timezone.utc)
    return value.isoformat(timespec="microseconds")


def redact(text):
    key = os.environ.get("DEEPSEEK_API_KEY")
    return text.replace(key, "[REDACTED]") if key else text


def compact_result(result, number, source, updated_at=None):
    record = {
        key: result[key] for key in (
            "instance_id", "evaluation_status", "reward", "seconds", "agent",
            "patch_bytes", "download_image", "error", "reason",
        ) if key in result
    }
    record.update(number=number, source=source, updated_at=updated_at or timestamp())
    if source == "actions":
        record.update(github_run_id=os.environ.get("GITHUB_RUN_ID"),
                      github_run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT"))
    return json.loads(redact(json.dumps(record, ensure_ascii=False)))


def export_local(source, output):
    cfg = read_json(source / "run_config.json")
    records = [
        compact_result(read_json(path), int(path.parent.name), "local", timestamp(path.stat().st_mtime))
        for path in sorted((source / "cases").glob("*/result.json"))
    ]
    core.write_json(output, {"config": {key: cfg[key] for key in CONFIG_KEYS},
                             "total": len(cfg["instance_ids"]), "records": records})
    print(f"已导出 {len(records)} 条本地结果：{output}")


def checkpoints(directory):
    if not directory or not directory.exists():
        return
    for path in sorted(directory.rglob("checkpoint.json")):
        yield read_json(path)
    for path in sorted(directory.rglob("case-*.zip")):
        with zipfile.ZipFile(path) as archive:
            # 只读 JSON，不解压镜像、补丁或任意路径到执行器。
            yield json.loads(archive.read("checkpoint.json"))


def merge_records(config, base, incoming, all_ids):
    known = {instance: index for index, instance in enumerate(all_ids, start=1)}
    records = {}
    for checkpoint in [base, *incoming]:
        if checkpoint["config"] != config or checkpoint["total"] != len(all_ids):
            raise ValueError("续跑记录的数据集、模型或执行上限不同，不能混合结果。")
        for row in checkpoint["records"]:
            instance = row["instance_id"]
            if instance not in known or row["number"] != known[instance]:
                raise ValueError(f"结果题号与固定数据集不一致：{instance}")
            if row["evaluation_status"] not in {"passed", "failed", "error"}:
                raise ValueError(f"未知结果状态：{instance}")
            previous = records.get(instance)
            if previous is None or row["updated_at"] > previous["updated_at"]:
                records[instance] = row
    return sorted(records.values(), key=lambda row: row["number"])


def select_numbers(all_ids, records, limit):
    if not 1 <= limit <= 200:
        raise ValueError("每批题数必须在 1–200 之间。")
    completed = {row["instance_id"] for row in records if row["evaluation_status"] in VALID_RESULTS}
    return [index for index, instance in enumerate(all_ids, start=1) if instance not in completed][:limit]


def plan(args):
    baseline = read_json(args.baseline)
    config = baseline["config"]
    for key, variable in (("model", "DEEPSEEK_MODEL"), ("base_url", "DEEPSEEK_BASE_URL")):
        if os.environ.get(variable, config[key]) != config[key]:
            raise ValueError(f"{variable} 与本地结果的配置不同，请先分开实验结果。")
    revision_result = subprocess.run(
        ["git", "-C", str(args.tasks_dir), "rev-parse", "HEAD"],
        capture_output=True, text=True,
    )
    if revision_result.returncode:
        raise ValueError("无法读取任务仓库提交：" + revision_result.stderr.strip())
    revision = revision_result.stdout.strip()
    if revision != config["dataset_commit"]:
        raise ValueError("任务仓库提交与本地结果不一致。")
    all_ids = [task["instance_id"] for task in core.load_tasks(args.tasks_dir)]
    records = merge_records(config, baseline, checkpoints(args.resume_dir), all_ids)
    selected = select_numbers(all_ids, records, args.limit)
    data = {"config": config, "all_instance_ids": all_ids, "records": records, "selected": selected}
    core.write_json(args.output / "plan.json", data)
    core.write_json(args.output / "checkpoint.json", {"config": config, "total": len(all_ids), "records": records})
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
            handle.write("matrix=" + json.dumps({"case": selected or [0]}, separators=(",", ":")) + "\n")
            handle.write(f"count={len(selected)}\n")
    print(f"已有有效评分 {sum(row['evaluation_status'] in VALID_RESULTS for row in records)} 题，本批选择 {len(selected)} 题。")


def selected_task(data, number):
    if number not in data["selected"]:
        raise ValueError("此题不在本批计划中。")
    return data["all_instance_ids"][number - 1]


def run_one(args):
    data = read_json(args.plan)
    instance = selected_task(data, args.number)
    config = data["config"]
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise ValueError("缺少 DEEPSEEK_API_KEY。")
    for key, variable in (("model", "DEEPSEEK_MODEL"), ("base_url", "DEEPSEEK_BASE_URL")):
        if os.environ.get(variable, config[key]) != config[key]:
            raise ValueError(f"{variable} 与计划不一致。")
        os.environ[variable] = config[key]
    task = core.load_tasks(args.tasks_dir, [instance])[0]
    args.output.mkdir(parents=True, exist_ok=True)
    images = core.ImageCache(args.output / "image_cache.json", workers=1, registry="ghcr.io")
    options = argparse.Namespace(max_steps=config["max_steps"], command_timeout=config["command_timeout"])
    try:
        if shutil.disk_usage(args.output).free < 10 * 1024 ** 3:
            raise RuntimeError("执行器可用磁盘不足 10 GiB，未启动模型，请查看执行器磁盘日志。")
        images.stage([(args.number, task)])
        prefix = f"pro2gha-{os.environ.get('GITHUB_RUN_ID', 'manual')}-{args.number}"
        result = core.run_case(task, args.output / "case", prefix, options, images)
    except Exception as error:
        result = {"instance_id": instance, "evaluation_status": "error", "reward": None,
                  "agent": {"status": "not_started"}, "error": f"{type(error).__name__}: {error}"}
    finally:
        images.close()
    agent_error = result.get("agent", {}).get("status") == "error"
    if agent_error:
        result.update(evaluation_status="error", reward=None,
                      error=result["agent"].get("error", "智能体进程异常，未完成有效评测。"))
    record = compact_result(result, args.number, "actions")
    core.write_json(args.output / "checkpoint.json", {"config": config, "total": len(data["all_instance_ids"]), "records": [record]})
    print(f"第 {args.number} 题：{record['evaluation_status']}；奖励：{record['reward']}")
    # 评分未通过是评测数据；模型服务错误才让矩阵尽快停止，避免持续消耗费用。
    return 2 if agent_error or result.get("agent", {}).get("provider_error") else 0


def archive_bytes(checkpoint, files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr("checkpoint.json", json.dumps(checkpoint, ensure_ascii=False, indent=2))
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def pack(args):
    data = read_json(args.plan)
    instance = selected_task(data, args.number)
    checkpoint_path = args.output / "checkpoint.json"
    if checkpoint_path.exists():
        checkpoint = read_json(checkpoint_path)
    else:
        checkpoint = {
            "config": data["config"], "total": len(data["all_instance_ids"]), "records": [compact_result({
                "instance_id": instance, "evaluation_status": "error", "reward": None,
                "agent": {"status": "unknown"}, "error": "评测步骤中断或未能完成；请查看工作流日志。",
            }, args.number, "actions")],
        }
    checkpoint = json.loads(redact(json.dumps(checkpoint, ensure_ascii=False)))
    checkpoint["omitted_files"] = {}
    files = {}
    for name in ("agent_result.json", "model.patch", "verifier.log"):
        path = args.output / "case" / name
        if not path.is_file():
            continue
        raw = path.read_bytes()
        if name == "verifier.log" and len(raw) > 32768:
            raw = b"[Only the last 32768 bytes retained]\n" + raw[-32768:]
        if name == "model.patch":
            key = os.environ.get("DEEPSEEK_API_KEY")
            content = raw.replace(key.encode(), b"[REDACTED]") if key else raw
        else:
            content = redact(raw.decode("utf-8", errors="replace")).encode("utf-8")
        candidate = {**files, name: content}
        if len(archive_bytes(checkpoint, candidate)) <= ARCHIVE_LIMIT - 2048:
            files = candidate
        else:
            checkpoint["omitted_files"][name] = {"bytes": path.stat().st_size, "reason": "artifact_size_limit"}
    payload = archive_bytes(checkpoint, files)
    if len(payload) > ARCHIVE_LIMIT:
        raise ValueError("压缩结果超过单题 512 KiB 上限。")
    args.artifacts.mkdir(parents=True, exist_ok=True)
    (args.artifacts / f"case-{args.number:04d}.zip").write_bytes(payload)
    print(f"单题产物 {len(payload)} 字节；省略文件：{list(checkpoint['omitted_files'])}")


def summarize(data, records):
    counts = Counter(row["evaluation_status"] for row in records)
    total = len(data["all_instance_ids"])
    valid = counts["passed"] + counts["failed"]
    return {
        "total": total, "processed": len(records), "passed": counts["passed"], "failed": counts["failed"],
        "error": counts["error"], "pending": total - len(records), "remaining_to_evaluate": total - valid,
        "valid_scored": valid, "pass_rate_scored": counts["passed"] / valid if valid else None,
        "known_passed_per_total": counts["passed"] / total,
    }


def batch_progress(data, records, run_id):
    current = [row for row in records if row["source"] == "actions"
               and row.get("github_run_id") == run_id and row["number"] in data["selected"]]
    return {"batch_selected": len(data["selected"]), "batch_received": len(current),
            "batch_errors": sum(row["evaluation_status"] == "error" for row in current),
            "batch_missing": len(data["selected"]) - len(current)}


def next_batch_inputs(summary, batch_number, batch_size, parallelism, run_id):
    if batch_number not in (1, 2, 3) or not 1 <= batch_size <= 200 or not 1 <= parallelism <= 20:
        raise ValueError("自动接续参数超出范围。")
    if (batch_number == 3 or summary["remaining_to_evaluate"] == 0
            or summary["batch_errors"] or summary["batch_missing"] or summary["batch_received"] == 0):
        return None
    return {"batch_size": str(batch_size), "parallelism": str(parallelism),
            "resume_run_id": str(run_id), "auto_continue": True, "batch_number": batch_number + 1}


def dispatch_next(args):
    summary = read_json(args.summary)
    inputs = next_batch_inputs(summary, args.batch_number, args.batch_size, args.parallelism,
                               os.environ["GITHUB_RUN_ID"])
    if inputs is None:
        print("不再自动接续：已全部完成、已到第三批，或本批存在异常/缺失记录。")
        return
    payload = {"ref": os.environ["GITHUB_REF_NAME"], "inputs": inputs}
    path = args.summary.parent / "next-batch.json"
    core.write_json(path, payload)
    subprocess.run([
        "gh", "api", "--method", "POST",
        f"repos/{os.environ['GITHUB_REPOSITORY']}/actions/workflows/swe-bench-pro-v2.yml/dispatches",
        "--input", str(path),
    ], check=True)
    message = f"已自动安排第 {inputs['batch_number']}/3 批；接续本次运行结果，最多 {args.parallelism} 路并行。"
    print(message)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write("\n" + message + "\n")


def merge(args):
    data = read_json(args.plan)
    base = {"config": data["config"], "total": len(data["all_instance_ids"]), "records": data["records"]}
    records = merge_records(data["config"], base, checkpoints(args.resume_dir), data["all_instance_ids"])
    summary = summarize(data, records)
    summary.update(batch_progress(data, records, os.environ.get("GITHUB_RUN_ID")))
    checkpoint = {"config": data["config"], "total": summary["total"], "records": records}
    core.write_json(args.output / "checkpoint.json", checkpoint)
    core.write_json(args.output / "summary.json", summary)
    (args.output / "results.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records), encoding="utf-8",
    )
    text = (
        "# SWE-bench Pro V2 测试结果\n\n"
        f"本批选择 {summary['batch_selected']} 题，收到 {summary['batch_received']} 条记录；"
        f"异常 {summary['batch_errors']} 题，缺失记录 {summary['batch_missing']} 题。\n\n"
        f"累计：通过 **{summary['passed']}**，未通过 **{summary['failed']}**，执行异常 **{summary['error']}**，"
        f"尚无结果 **{summary['pending']}**。\n\n"
        f"有效评分 {summary['valid_scored']} / {summary['total']}；"
        + (f"已评分样本通过率 **{summary['pass_rate_scored']:.2%}**。\n\n" if summary['pass_rate_scored'] is not None else "尚无有效评分。\n\n")
        + f"仍需有效评分 **{summary['remaining_to_evaluate']}** 题（包括执行异常）。\n\n"
        "checkpoint.json 包含本地基线与历次云端的最新结果。启用自动接续时，正常完成后最多运行三批；"
        "出现异常或缺失记录时停止。手动恢复选择 latest；不要用 Re-run all jobs 重跑已有计划。\n\n"
        "未测题不判失败；样本通过率不代表全量成绩。单题补丁和限长日志保存在各 case 产物中；完整消息历史未上传。\n"
    )
    (args.output / "summary.md").write_text(text, encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write(text)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("--source", type=Path, default=ROOT / "pro_v2_runs/full")
    export.add_argument("--output", type=Path, default=ROOT / "benchmarks/pro_v2/baseline.json")
    planner = commands.add_parser("plan")
    planner.add_argument("--tasks-dir", type=Path, required=True)
    planner.add_argument("--baseline", type=Path, default=ROOT / "benchmarks/pro_v2/baseline.json")
    planner.add_argument("--resume-dir", type=Path)
    planner.add_argument("--limit", type=int, default=200)
    planner.add_argument("--output", type=Path, default=Path("cloud-plan"))
    dispatch = commands.add_parser("dispatch-next")
    dispatch.add_argument("--summary", type=Path, default=Path("cloud-summary/summary.json"))
    dispatch.add_argument("--batch-number", type=int, required=True)
    dispatch.add_argument("--batch-size", type=int, default=200)
    dispatch.add_argument("--parallelism", type=int, default=20)
    for command in ("run", "pack", "merge"):
        sub = commands.add_parser(command)
        sub.add_argument("--plan", type=Path, default=Path("cloud-plan/plan.json"))
        sub.add_argument("--output", type=Path, default=Path("cloud-run"))
        if command in ("run", "pack"):
            sub.add_argument("--number", type=int, required=True)
        if command == "run":
            sub.add_argument("--tasks-dir", type=Path, required=True)
        elif command == "pack":
            sub.add_argument("--artifacts", type=Path, default=Path("cloud-artifacts"))
        else:
            sub.add_argument("--resume-dir", type=Path)
    args = parser.parse_args()
    if args.command == "export":
        export_local(args.source, args.output)
    else:
        return {"plan": plan, "run": run_one, "pack": pack, "merge": merge,
                "dispatch-next": dispatch_next}[args.command](args)


if __name__ == "__main__":
    sys.exit(main() or 0)
