# 在 GitHub Actions 中继续 SWE-bench Pro V2 评测

## 方案

使用公开仓库的标准 `ubuntu-24.04` x64 执行器。每台执行器只处理一道题，保持本地的 1 CPU、4 GiB 容器限制、30 轮模型上限及原有评分流程。运行后虚拟机销毁，镜像不进入构建产物或 Actions 缓存。[执行器规格](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)

| 项目 | 配置与原因 |
| --- | --- |
| 触发方式 | 首次手动启动，正常完成后自动接续，最多三批；推送、拉取请求均不触发 |
| 每批题数 | 默认 200，可选 20、50、100、200；低于每个矩阵 256 个任务的上限 |
| 并行执行器 | 默认 20，可选 4、8、12、16、20；账户或组织共享额度不足时由 GitHub 排队 |
| 单题任务时限 | 执行步骤由 `timeout` 限制为 150 分钟，整个任务上限 180 分钟，低于标准任务 6 小时上限 |
| 镜像来源 | 云端直接使用官方 `ghcr.io`，不经过本机 VPN 或南京大学镜像服务 |
| 磁盘处理 | 仅在云端清理预装 Android/.NET/Haskell 工具；一次只准备一个题目镜像；启动前检查至少 10 GiB 可用空间 |
| 数据集版本 | 固定提交 `66f92766bba642462d4bbe5479e83f91f9211862`，与本地记录一致 |
| 依赖 | `uv sync --frozen` 使用项目现有锁文件与 Python 3.14 |
| 重复触发 | 同一仓库的本流程串行排队，避免两轮同时处理同一批题 |

标准执行器资源是每台独立分配，并非 20 个任务共用一台机器。20 是本流程请求的最大并行数，实际启动数量仍受账户或组织的共享并发上限及其他任务占用影响。当前没有查询账户套餐和其他任务占用。

公开仓库标准执行器计算时间免费，外部模型调用仍收费。本流程只在公开仓库启用；没有配置更大规格执行器或付费云平台。矩阵任务数量与同时运行数量分别控制，任务最长时间也单独限制。[Actions 限制](https://docs.github.com/en/actions/reference/limits)、[矩阵并发设置](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/run-job-variations)

## 如何沿用本地结果

`benchmarks/pro_v2/baseline.json` 保存本地 119 条结果的精简副本，不包含密钥、消息历史或 Windows 路径。

- 92 道通过和 25 道未通过，共 117 道已有有效评分，默认跳过。
- 2 道镜像下载异常和 523 道尚未完成的题目，共 525 道仍需评分。
- 在没有新增异常的情况下，按每批 200 题，依次为 **200、200、125** 题。只需手动启动一次，后两批自动接续；若出现执行异常、缺失记录或手动取消，则保存进度并停止，处理后再恢复。

本地结果副本由以下命令导出，不调用模型或 Docker：

```powershell
& '.\.venv\Scripts\python.exe' scripts/pro_v2_actions.py export
```

初始副本已经生成，不必为启动云端测试重新导出。只有本地结果继续更新时才需要重新生成并提交。

## 首次配置

1. 工作流文件需提交并推送至仓库默认分支，网页上才会出现手动运行入口。[手动运行要求](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)。推送本身不会启动评测。
2. 在仓库的设置（Settings）→ 密钥和变量（Secrets and variables）→ Actions → 新建仓库密钥（New repository secret）中，添加 **`DEEPSEEK_API_KEY`**，填入现有模型服务密钥。不要把 `.env` 提交到公开仓库。
3. 模型默认是 `deepseek-flash`，接口默认是 `https://api.deepseek.com`，与本地基线一致。通常无需配置额外变量；如配置 `DEEPSEEK_MODEL` 或 `DEEPSEEK_BASE_URL`，必须与基线匹配，否则会在解题前停止，避免混合不同实验。
4. 在仓库的 Actions 页面，选择 **SWE-bench Pro V2 后续评测**，点击运行工作流（Run workflow）。
5. 使用默认输入：`batch_size=200`、`parallelism=20`、`resume_run_id=latest`、`auto_continue=true`、`batch_number=1`。首次保留批号 1，之后由流程自动填写批号 2、3。若缩小每批题数，三批可能无法覆盖全部剩余任务。

密钥配置页面：[仓库的 Actions 密钥设置](https://github.com/DeianHsu/mini_swe_agent_demo/settings/secrets/actions)。只需添加 `DEEPSEEK_API_KEY`，不需要另建 GitHub 个人访问令牌。

仓库地址：[DeianHsu/mini_swe_agent_demo](https://github.com/DeianHsu/mini_swe_agent_demo)。

## 下一批与断点续跑

默认不需要手动启动第二、第三批。每批汇总完成后，若本批选中的题目全部返回记录且没有执行异常、仍有剩余任务、当前未到第三批，汇总任务就自动启动下一批，并明确指定接续本次运行 ID。验证脚本给出 `failed` 是正常评分结果，不会阻止接续。

只有汇总任务获得 `actions: write` 权限，使用 GitHub 自动提供的 `GITHUB_TOKEN` 派发下一批；不需要用户填写额外令牌。这是 GitHub 支持的 `workflow_dispatch` 触发方式。[官方说明](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)

自动接续最多三批；遇到异常、缺失记录或整体任务失败时停止。在修复问题后，如需恢复，再手动点击一次 **Run workflow**，使用 `resume_run_id=latest`、`batch_number=1`。重新运行已有任务（Re-run）不会自动派发下一批，以免重复创建后续运行。

准备任务会寻找同分支最近一次有可用产物的已结束运行，下载其 `pro-v2-*` 产物，将最新结果与本地基线合并，只选择尚未有效评分的题目。准备阶段失败且没有可用产物的运行会自动跳过。已有 `passed`、`failed` 均跳过，`error` 和缺少最终记录的题目会补跑。任务目录按显式忽略大小写的名称顺序排序，确保 Windows 与 Linux 题号一致。

| `resume_run_id` | 含义 |
| --- | --- |
| `latest` | 默认，接续同分支最近一次有可用产物的已结束运行 |
| 数字运行 ID | 接续指定的一次运行；ID 可从工作流运行页面地址获取 |
| `none` | 仅使用仓库内本地基线，会重新处理此前仅在云端评分的题目，谨慎选择 |

**不要用 Re-run all jobs 作为恢复入口**，它会重新执行同一批计划。需要人工恢复时，应新建一次 Run workflow，让准备任务重新选择剩余题目。

如果上次在准备阶段就失败、没有可用 `pro-v2-*` 产物，`latest` 会自动跳过并继续寻找更早的记录；只有准备失败、尚无任何云端记录时会直接使用本地基线。若旧运行已进入评测但记录不可用，或历史产物下载失败，则停止并要求指定有效运行 ID，避免从头重复调用模型。

手动取消时，已经上传的单题记录仍可合并；取消或机器中断可能使正在处理的题目来不及上传，该题下次需重新执行。整轮取消不保证汇总任务一定完成，但续跑也能读取已上传的单题压缩包。

## 结果与存储

工作流汇总任务生成 `pro-v2-summary` 产物，保存 30 天：

- `summary.md`：供阅读的累计结果。
- `summary.json`：通过、未通过、异常、未测数量及明确分母的通过比例。
- `results.jsonl`：本地与历次云端的逐题最新结果。
- `checkpoint.json`：完整精简续跑记录，建议下载留存；同题多次执行按最新记录合并，不挑选最高分。

每题上传一个 `pro-v2-case-编号-attempt-次数` 产物，保存 7 天。内部压缩包优先保留评分记录、智能体结束状态、补丁及最后 32 KiB 验证日志，**压缩后每题最多 512 KiB**。超限文件会省略，并在包内 `checkpoint.json` 的 `omitted_files` 中注明；完整消息历史、轨迹、镜像和依赖缓存不上传。

每批 200 题的单题压缩内容上限约 100 MiB；525 题正常各执行一次合计约 263 MiB，另有小型计划、汇总及平台包装开销。历史批次、重复运行和账户其他仓库产物也占用额度，因此这不是对账户 500 MB 剩余额度的保证。下载所需报告后，可在运行页面删除不再需要的旧产物；续跑依赖的最新汇总记录应先保留或另存。

`pro-v2-plan` 保存 7 天；Docker 镜像不占用 Actions 的 10 GB 仓库缓存额度。Windows 本机不会下载测试镜像，手动下载结果产物仍可能产生少量本机网络或 VPN 流量。

验证脚本判定未通过时，任务仍正常结束并保存 `failed`。下载等基础设施异常记录为 `error`，后续补跑。模型服务异常或智能体进程错误会使任务失败并停止尚在排队的矩阵任务，以免整个批次持续调用故障接口。

释放预装工具能争取磁盘空间，但不保证任意题目镜像都能放入标准执行器。若出现空间不足，应按具体题目的日志处理，不自动切换付费执行器。

## 已验证与尚未验证

本地核对任务选择、结果合并、产物大小限制与工作流配置；真实 Ubuntu 执行器上的镜像拉取、模型访问、磁盘占用和整批速度，需要首次手动运行后确认。配置文件没有触发真实评测。
