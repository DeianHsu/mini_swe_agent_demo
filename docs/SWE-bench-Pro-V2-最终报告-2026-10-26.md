# SWE-bench Pro V2 最终评测报告

最终运行于北京时间 **2026 年 10 月 26 日 00:41** 结束：[40211832852](https://github.com/DeianHsu/mini_swe_agent_demo/actions/runs/40211832852)。本轮评测已完成，不再派发后续任务。

## 最终结果

| 指标 | 题数 |
| --- | ---: |
| 总题数 | 642 |
| 有效评分 | **642** |
| 通过 | **542** |
| 正常未通过 | **100** |
| 执行异常 | **0** |
| 未测 | **0** |

累计通过占比 **542/642 = 84.42%**。该成绩按每题最新结果合并，包含历史失败重试、Go 补丁重评及异常补测，**不能称为单次通过率（pass@1）**，也未向官方排行榜提交。

数据集固定提交 `66f92766bba642462d4bbe5479e83f91f9211862`；模型 `deepseek-flash`，每题最多 30 轮，命令最多 180 秒，每批最多 200 题、20 路并行。官方测试与判分规则保持原样。

## 各仓库结果

| 仓库 | 通过 | 未通过 | 有效评分 |
| --- | ---: | ---: | ---: |
| ansible/ansible | 77 | 5 | 82 |
| element-hq/element-web | 48 | 4 | 52 |
| flipt-io/flipt | 69 | 9 | 78 |
| future-architect/vuls | 55 | 3 | 58 |
| gravitational/teleport | 54 | 14 | 68 |
| internetarchive/openlibrary | 65 | 17 | 82 |
| navidrome/navidrome | 46 | 6 | 52 |
| NodeBB/NodeBB | 21 | 17 | 38 |
| protonmail/webclients | 41 | 14 | 55 |
| qutebrowser/qutebrowser | 64 | 9 | 73 |
| tutao/tutanota | 2 | 2 | 4 |

## 本轮批次

起始固定队列为 405 题；另外保留起始基线中已通过的 237 题。本轮共执行 416 次单题任务：405 次正常队列、8 次异常顺延、3 次最终补测。相同题目的多次尝试只保留最新评分计入最终 642 题，原始尝试记录另存。

| 运行 | 本批题数 | 累计通过 | 累计未通过 | 异常 | 未测 | 有效评分 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| [40191159974](https://github.com/DeianHsu/mini_swe_agent_demo/actions/runs/40191159974) | 200 | 385 | 52 | 0 | 205 | 437 |
| [40196704281](https://github.com/DeianHsu/mini_swe_agent_demo/actions/runs/40196704281) | 200 | 536 | 94 | 7 | 5 | 630 |
| [40201792112](https://github.com/DeianHsu/mini_swe_agent_demo/actions/runs/40201792112) | 12 | 541 | 97 | 4 | 0 | 638 |
| [40207176387](https://github.com/DeianHsu/mini_swe_agent_demo/actions/runs/40207176387) | 1 | 542 | 97 | 3 | 0 | 639 |
| [40211832852](https://github.com/DeianHsu/mini_swe_agent_demo/actions/runs/40211832852) | 3 | 542 | 100 | 0 | 0 | 642 |

## 最终三题

514、522、535 原先因命令输出导致上下文超限，修复 `0f088b7` 后仅对这三题执行一次最终补测。三题均运行到 30 轮上限，并完成官方判分，奖励均为 0，判为正常未通过；不再有模型上下文超限或执行异常。未增加轮数、时限或资源，未重跑其他正常未通过题。

| 题号 | 官方判定 | 模型轮数 | 补丁字节数 |
| --- | --- | ---: | ---: |
| 514 | 未通过 | 30 | 9523 |
| 522 | 未通过 | 30 | 10397 |
| 535 | 未通过 | 30 | 0 |

对应补丁、官方验证摘要与原始输出、工作流日志均已归档。此处按官方判定记录成绩，不将正常未通过改为异常或通过。

## 保存与验证

- 仓库基线：`benchmarks/pro_v2/baseline.json`，包含 642 条最新记录，可在不依赖本地大日志的情况下确认全部已评分。
- 本机最终目录：`pro_v2_runs/combined-40191159974/`，保存 `checkpoint.json`、`summary.json`、`summary.md`、`results.jsonl`、`final-report.md`、空的 `unresolved-errors.json` 及 416 条本轮尝试记录 `campaign-attempts.jsonl`。
- 每批原始计划和汇总：`pro_v2_runs/actions/<运行编号>/`。本机原始本地评测、旧快照及合并前基线继续保留。
- 最终三题的单题产物及工作流日志：`pro_v2_runs/actions/40211832852/cases/` 与 `jobs/`。
- 输出限制修复已通过 35 项离线测试；本次归并另核对服务器汇总、642 条唯一题目、416 次唯一尝试及空的后续异常队列，并通过同步后的 23 项调度与基线测试。

官方验证器对具体补丁的判定已实际执行；本次收尾不重复调用模型或重新运行全部 642 题。

定时任务 `swe-bench` 已删除，跟进状态 `finished=true`，本轮不再自动派发。
