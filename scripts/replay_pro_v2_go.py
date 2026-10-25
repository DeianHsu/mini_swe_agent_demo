"""仅重放两个 Go 仓库的 136 份已存模型补丁；不调用模型。"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import time

from scripts import diagnose_pro_v2_go as diagnostic
from scripts import pro_v2_actions as ci


SOURCE_RUN_ID = "40177855906"


def prepare(args):
    source = ci.read_json(args.source)
    baseline = ci.read_json(ci.ROOT / "benchmarks/pro_v2/baseline.json")
    revision = subprocess.run(["git", "-C", str(args.tasks_dir), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    if revision != diagnostic.DATASET_COMMIT:
        raise ValueError("任务仓库版本与原评测不一致。")
    tasks = ci.core.load_tasks(args.tasks_dir)
    all_ids = [task["instance_id"] for task in tasks]
    records = ci.merge_records(baseline["config"], baseline, [source], all_ids)
    source_rows = {row["instance_id"]: row for row in source["records"]}
    selected = [number for number, instance in enumerate(all_ids, start=1)
                if instance.startswith(tuple(diagnostic.SAMPLES.values()))]
    if len(selected) != 136 or any(all_ids[number - 1] not in source_rows for number in selected):
        raise ValueError("原运行缺少两个仓库的 136 份记录，停止以免重复生成补丁。")
    data = {"config": baseline["config"], "all_instance_ids": all_ids, "records": records,
            "selected": selected, "campaign": source["campaign"],
            "evaluation_method": "patch_replay", "replay_source_run_id": SOURCE_RUN_ID}
    ci.core.write_json(args.output / "plan.json", data)
    ci.core.write_json(args.output / "checkpoint.json", {
        "config": data["config"], "total": len(all_ids), "records": records, "campaign": source["campaign"]})
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
            handle.write("matrix=" + json.dumps({"case": selected}, separators=(",", ":")) + "\n")
    print(f"重评计划：Flipt 78 题 + Vuls 58 题 = {len(selected)} 题；不调用模型。")


def run(args):
    data = ci.read_json(args.plan)
    instance = ci.selected_task(data, args.number)
    try:
        source, patch = diagnostic.read_case_archive(args.case_archive, args.number, expected_instance=instance)
    except diagnostic.MissingPatchError as error:
        if args.plan_only:
            print(f"第 {args.number} 题缺少已保存补丁：{error}")
            return
        source = next(row for row in data["records"] if row["instance_id"] == instance)
        record = ci.compact_result({
            "instance_id": instance, "agent": source.get("agent", {}), "evaluation_status": "error", "reward": None,
            "evaluation_method": "patch_replay", "replay_source_run_id": SOURCE_RUN_ID,
            "reason": "missing_saved_patch", "error": str(error),
        }, args.number, "actions")
        ci.core.write_json(args.output / "checkpoint.json", {
            "config": data["config"], "total": len(data["all_instance_ids"]), "records": [record]})
        print(f"第 {args.number} 题无法重评：{error}", flush=True)
        return
    if source.get("github_run_id") != SOURCE_RUN_ID:
        raise ValueError("已有补丁不属于指定的原评测运行。")
    task = ci.core.load_tasks(args.tasks_dir, [instance])[0]
    print(f"重放第 {args.number} 题：{instance}；已有补丁 {len(patch)} 字节，不调用模型。", flush=True)
    if args.plan_only:
        return
    case_dir = args.output / "case"
    case_dir.mkdir(parents=True, exist_ok=False)
    (case_dir / "model.patch").write_bytes(patch)
    result = {"instance_id": instance, "agent": source.get("agent", {}), "patch_bytes": len(patch),
              "evaluation_method": "patch_replay", "replay_source_run_id": SOURCE_RUN_ID,
              "evaluation_status": "error", "reward": None}
    started = time.monotonic()
    images = ci.core.ImageCache(args.output / "image-cache.json", workers=1)
    try:
        images.stage([(args.number, task)])
        images.wait(task["image"])
        result["download_image"] = images.download_image(task["image"])
        name = f"pro2replay-{os.environ.get('GITHUB_RUN_ID', 'manual')}-{args.number}"
        result.update(ci.core.verify_patch(task, case_dir, name))
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
    finally:
        images.close()
    result["seconds"] = round(time.monotonic() - started, 2)
    record = ci.compact_result(result, args.number, "actions")
    ci.core.write_json(args.output / "checkpoint.json", {
        "config": data["config"], "total": len(data["all_instance_ids"]), "records": [record]})
    print(f"重评结果：{record['evaluation_status']}；奖励：{record['reward']}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    planner = commands.add_parser("prepare")
    planner.add_argument("--tasks-dir", type=Path, required=True)
    planner.add_argument("--source", type=Path, default=Path("replay-source/checkpoint.json"))
    planner.add_argument("--output", type=Path, default=Path("cloud-plan"))
    worker = commands.add_parser("run")
    worker.add_argument("--tasks-dir", type=Path, required=True)
    worker.add_argument("--plan", type=Path, default=Path("cloud-plan/plan.json"))
    worker.add_argument("--number", type=int, required=True)
    worker.add_argument("--case-archive", type=Path, required=True)
    worker.add_argument("--output", type=Path, default=Path("cloud-run"))
    worker.add_argument("--plan-only", action="store_true", help="只核对补丁，不执行 Docker。")
    args = parser.parse_args()
    {"prepare": prepare, "run": run}[args.command](args)


if __name__ == "__main__":
    main()
