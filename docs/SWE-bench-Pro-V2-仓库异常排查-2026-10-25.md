# SWE-bench Pro V2 仓库集中失败排查

来源：[运行 40177855906](https://github.com/DeianHsu/mini_swe_agent_demo/actions/runs/40177855906) 的汇总和单题产物。第一批 200 题均返回结果，无执行异常或缺失记录；自动接续因批号传为 JSON 数字被 GitHub 拒绝（HTTP 422），与单题测试失败是两个独立问题。修复后批号按字符串传输。

## 当前累计分布

| 仓库 | 已评分 | 通过 | 未通过 |
| --- | ---: | ---: | ---: |
| ansible/ansible | 82 | 76 | 6 |
| element-hq/element-web | 52 | 46 | 6 |
| flipt-io/flipt | 78 | 0 | 78 |
| future-architect/vuls | 58 | 0 | 58 |
| gravitational/teleport | 36 | 5 | 31 |
| 合计 | **306** | **127** | **179** |

另有 336 题未测。Flipt 和 Vuls 合计 136 题，占未通过题目的 75.98%。这些数字是当前各题最新结果，包含历史失败题重试，不能作为单次通过率。

## 已确认的证据与限制

抽查 Flipt 第 135、160、200 题及 Vuls 第 213、230、270 题；六题验证摘要均显示 `Passed tests: 0`，且必需测试全部出现在 `Missing tests` 中。官方测试补丁均已成功应用。这个现象与编译失败、测试未运行或解析问题相容，也不能排除补丁导致编译或测试失败；尚不能认定 136 题均是环境错误。

官方 `tests/test.sh` 把原始测试输出写入 `verifier/run-script-stdout.txt`、`verifier/run-script-stderr.txt`，并保存解析结果 `verifier/output.json`。之前的产物打包没有包含这三个文件，因此目前只有外层摘要，缺少判定根因的原始输出。旧云端执行器已销毁，后续增加日志无法恢复旧文件。

已补充后续产物保存这三个文件；文本各限末尾 32 KiB，总压缩包仍限 512 KiB，并沿用密钥脱敏。现有评分不修改，136 题标记为需要诊断，不能直接归因于模型能力或直接改判通过。

进一步核查应先对 Flipt、Vuls 各选一道失败题，仅在全新容器中重放已保存补丁并运行官方验证，读取原始输出；不必再次调用模型生成补丁。启动此类验证仍由用户决定和操作。

本地汇总和六个抽样产物保存在 `pro_v2_runs/actions/40177855906/`。

## 已准备的专项诊断

官方镜像的小型配置元数据确认：Flipt 第 135 题和 Vuls 第 213 题均把 `/usr/local/go/bin` 和 `/go/bin` 放入 `PATH`，并设有 `GOTOOLCHAIN=local`。诊断前正式启动器使用 `bash -lc`，因此先对比登录式 Shell 是否改变镜像原有的 `PATH`；下述真实诊断已确认此问题。

新增手动工作流 **SWE-bench Pro V2 Go 仓库诊断**（`.github/workflows/diagnose-pro-v2-go.yml`）。打开仓库 Actions，选择该名称，在 `master` 分支点击运行工作流（Run workflow）；没有额外参数，也不需要配置模型密钥。推送不会自动启动。

两台执行器分别处理第 135、213 题，每台下载一个镜像并依次创建四个全新验证容器：

| 对照 | 补丁 | Bash 启动方式 |
| --- | --- | --- |
| oracle-login | 官方参考补丁 | `bash -lc`，与当前正式流程一致 |
| oracle-plain | 官方参考补丁 | `bash -c`，保留镜像的原有环境 |
| model-login | 上次已生成的模型补丁 | `bash -lc` |
| model-plain | 上次已生成的模型补丁 | `bash -c` |

参考补丁只用于验证环境的对照容器；整个流程没有模型调用，也不会把参考答案交给智能体。官方测试文件不修改。每次验证上限 900 秒、每容器 1 CPU 和 4 GiB 内存；超时只能说明诊断未完成，不能直接改判。输出保存在 `pro-v2-go-diagnosis-135-attempt-1` 和 `pro-v2-go-diagnosis-213-attempt-1` 产物中，包括四组的环境、补丁应用日志、原始标准输出/错误和解析结果。

若参考补丁仅在 `oracle-plain` 下通过，且登录式 Bash 中找不到 Go，即有直接证据修复启动方式；若参考补丁在原流程通过而模型补丁不通过，再检查模型补丁。若参考补丁也都不通过，继续依据原始输出定位环境、编译或测试脚本问题。诊断成绩不导入 642 题的正式汇总，也不自动接续全量评测。

## 真实诊断结果与修复

[诊断运行 40185782809](https://github.com/DeianHsu/mini_swe_agent_demo/actions/runs/40185782809) 已完成，原始产物下载到 `pro_v2_runs/diagnosis/40185782809/`。

| 样本 | 参考补丁 + 登录式 Bash | 参考补丁 + 非登录式 Bash | 原模型补丁 + 非登录式 Bash |
| --- | --- | --- | --- |
| Flipt 第 135 题 | 找不到 Go，失败 | 通过，解析到 16 个通过测试 | 未通过，解析到 14 个通过测试 |
| Vuls 第 213 题 | 找不到 Go，失败 | 通过，24 个测试通过 | 通过，24 个测试通过 |

两份环境日志均显示：`bash -lc` 把 `PATH` 改为 `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin`，丢失 `/usr/local/go/bin` 和 `/go/bin`；原始输出为 `go: command not found`。`bash -c` 保留镜像原有路径，能调用 `/usr/local/go/bin/go`，两份参考补丁均通过。这确认旧启动方式存在环境故障；Vuls 第 213 题已经提供了模型补丁被误判的直接样本，但不能据此把其余题直接改判通过。

Flipt 第 135 题环境恢复后仍有真实补丁问题：同时设置 CA 证书内容和路径时，没有返回互斥配置错误；`RedisCacheConfig.InsecureSkipTLS` 的 JSON 标签也未通过项目规范检查。该题仍应按官方验证结果判为未通过。

已把 Docker Bash 工具、智能体执行命令、补丁导出和正式验证统一改为 `bash -c`，避免生成与验证使用不同的环境。生成补丁与重放已有补丁共用 `verify_patch()`，使用相同官方测试、1 CPU/4 GiB 限制及原验证超时，不修改官方测试内容。

## 136 题已有补丁重评

用户已确认准备重评流程，仍由用户手动启动。新工作流为 **SWE-bench Pro V2 Go 补丁重评（不调用模型）**，文件 `.github/workflows/replay-pro-v2-go.yml`。在 Actions 选择该名称，选择 `master` 分支并点击运行工作流（Run workflow），无需参数或模型密钥；推送本身不会运行。

流程从原运行 `40177855906` 下载已保存的补丁，在修复后的正式验证环境中逐题重放，最多 20 路并行，范围仅为 Flipt 78 题和 Vuls 58 题。不会重新生成补丁，不使用参考补丁给模型计分，也不自动继续其他 336 道未测题。结束后 `pro-v2-summary` 合并原有成绩与本次重评，逐题记录 `evaluation_method=patch_replay`、`replay_source_run_id` 和 `verifier_shell`；原运行结果仍保留。

已确认第 178 题的原补丁有 42,289,862 字节，原单题产物因大小限制省略了 `model.patch`，当前无法恢复。它会明确记录为 `error / missing_saved_patch`，不会当成已重评通过或自动重新调用模型。其余 135 题可继续重放；最终通过数量必须以实际验证结果为准。

重评是独立工作流。以后继续全量测试时，需把 `resume_run_id` 明确填为本次重评的运行 ID；主评测的 `latest` 只查找主评测工作流，不能自动选到独立重评结果。如需继续原轮剩余 336 题，沿用 `campaign_id=40177855906`、`batch_number=2`，避免重新生成本轮已经处理过的失败题。
