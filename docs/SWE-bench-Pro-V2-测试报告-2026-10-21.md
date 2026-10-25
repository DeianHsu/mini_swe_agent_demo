# SWE-bench Pro V2 本地测试报告

报告日期：2026 年 10 月 21 日。所有时间均为北京时间（UTC+8）。

## 1. 测试结论

本次使用项目手写的智能体（Agent），以 `deepseek-flash` 为模型，在本机 Docker Linux 容器中运行 SWE-bench Pro V2。因运行时间较长、镜像下载流量消耗较大，用户手动停止测试。

截至停止时，**119 道题保存了最终结果：92 道通过、25 道未通过、2 道镜像下载超时**。其中，完成有效评分的 117 道题通过率为 **78.63%（92/117）**。第 120 题执行中断，没有最终评分。

这是一份**部分样本的本地测试报告**。题目按目录名排序执行，当前仅覆盖 Ansible 和 Element Web 两个仓库，不能据此认定该智能体在全量 SWE-bench Pro V2 上的通过率为 78.63%。

## 2. 结果汇总与统计口径

| 指标 | 数值 | 说明 |
| --- | ---: | --- |
| 本地任务总数 | 642 | 来自本次运行配置中的任务列表 |
| 已保存最终结果 | 119 | 包含通过、未通过及执行异常 |
| 完成有效评分 | 117 | 92 道通过 + 25 道未通过 |
| 通过（passed） | 92 | 补丁在全新容器中通过题目提供的验证脚本 |
| 未通过（failed） | 25 | 验证脚本判定必需测试未全部通过 |
| 执行异常（error） | 2 | 镜像下载超时，两题均未启动模型解题 |
| 尚无最终结果 | 523 | 包括执行中断的第 120 题，以及后续 522 题 |

| 比例 | 计算方式 | 结果 |
| --- | --- | ---: |
| 有结果记录的任务覆盖率 | 119 / 642 | 18.54% |
| 有效评分样本通过率 | 92 / 117 | **78.63%** |
| 包含执行异常的已处理样本通过比例 | 92 / 119 | 77.31% |
| 已确认通过题目占全量任务的比例 | 92 / 642 | 14.33% |

`summary.json` 中的 `resolved_rate_total` 对应最后一行的 14.33%。它只说明当前已经确认通过 92 道题，**不是本次已测样本通过率，也不是完成全量评测后的成绩**。未测题目没有被判为失败。

## 3. 运行配置与评分方式

| 项目 | 本次配置 |
| --- | --- |
| 智能体 | 本项目 `docker_bash/mini_agent.py` 中的 `agent()` |
| 批量入口 | `docker_bash/run_pro_v2.py` |
| 模型名称 | `deepseek-flash` |
| 模型接口 | `https://api.deepseek.com` |
| 思考模式 | 请求参数 `thinking.type = disabled` |
| 调用协议 | 原生工具调用（Function Calling），单一 `execute` 工具执行 Bash 命令 |
| 每题模型轮数上限 | 30 轮 |
| 单条工具命令超时 | 180 秒 |
| 题目配置中的解题时间上限 | 3000 秒 |
| 题目配置中的验证时间上限 | 3000 秒 |
| 镜像准备时间预算 | 1800 秒；优化后最多三次下载尝试共享此预算 |
| 容器资源限制 | 每个任务容器 1 个 CPU、4096 MB 内存 |
| 解题阶段网络 | `--network none`，模型接口调用在 Windows 宿主机上完成 |
| 验证阶段网络 | 在全新容器中使用 `--network bridge` |
| 题目执行并行度 | 1；镜像下载可以与解题及验证重叠 |
| 数据集仓库提交 | `66f92766bba642462d4bbe5479e83f91f9211862` |

本次运行沿用了 30 轮上限等本地配置，因此应以本报告所列条件解释结果；没有通过官方托管评测流程提交排行榜成绩。

评分流程如下：读取题目说明 → 智能体在断网容器中修改代码 → 导出 Git 补丁 → 在同一题目镜像创建的全新容器中应用补丁 → 运行题目提供的 `tests/test.sh` → 读取退出码、结果标记和奖励文件。

通过判定同时要求验证退出码为 `0`、奖励文件为 `1`、日志包含 `RESULT: PASSED`。未通过判定要求退出码为 `1`、奖励文件为 `0`、日志包含 `RESULT: FAILED`。其他情况记录为执行异常。模型正文中自行声称“已完成、验证通过”不作为评分依据。

## 4. 样本覆盖范围

| 仓库 | 数据集题目数 | 已记录 | 通过 | 未通过 | 执行异常 | 有效评分样本通过率 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `ansible/ansible` | 82 | 82 | 66 | 16 | 0 | 80.49%（66/82） |
| `element-hq/element-web` | 52 | 37 | 26 | 9 | 2 | 74.29%（26/35） |
| 其他 9 个仓库 | 508 | 0 | 0 | 0 | 0 | 未测试 |
| **合计** | **642** | **119** | **92** | **25** | **2** | **78.63%（92/117）** |

执行顺序为第 1–82 题 Ansible、第 83–119 题 Element Web。尚未记录结果的 523 题，由 Element Web 剩余 15 题及其他仓库的 508 题组成。

其他仓库为 `flipt-io/flipt`、`future-architect/vuls`、`gravitational/teleport`、`internetarchive/openlibrary`、`navidrome/navidrome`、`NodeBB/NodeBB`、`protonmail/webclients`、`qutebrowser/qutebrowser`、`tutao/tutanota`。

这些样本不是随机抽样，仓库、语言和题目分布存在偏差。当前结果适合用于评估已覆盖任务和复盘实现，不适合推算全量成绩。

## 5. 运行耗时与下载优化

第一条已保存结果所对应的尝试起始时间，按结果文件时间与记录耗时估算为 **10:19:51**；最后一条完整结果保存于 **19:18:55**，跨度约 **8 小时 59 分钟**。该跨度包含历史重试、暂停及其他等待，并非连续计算时长，也不代表准确的手动停止时间。

119 条最终结果的 `seconds` 合计约 **7 小时 30 分钟**，平均每题 **3 分 47 秒**，中位数约 **3 分 2 秒**。其中两个下载异常对应的本题处理时间合计约 **42 分 13 秒**。

| 环节 | 按最终尝试记录估算的累计时间 |
| --- | ---: |
| 智能体执行，含模型等待和工具命令执行 | 226.1 分钟 |
| 官方验证及其前置准备 | 87.5 分钟 |
| 镜像等待、容器管理、补丁导出等其他步骤 | 136.4 分钟 |
| **合计** | **450.0 分钟** |

环节拆分根据产物文件时间近似计算。`seconds` 仅统计各题最终保存结果对应的尝试，不包含所有历史重试、未完成的第 120 题及部分循环外缓存维护时间。后台下载与当前题执行可以重叠，以上数字不能用于计算网络流量。

第 28 题开始使用优化后的启动器：两路镜像并行下载、提前准备后续两题、保留最近两题及待执行题目的镜像缓存、下载失败自动重试。模型轮数、解题串行方式和评分条件保持原配置。

| 运行阶段 | 题数 | 平均每题记录耗时 |
| --- | ---: | ---: |
| 优化前，Ansible 第 1–27 题 | 27 | 3 分 53 秒 |
| 优化后，Ansible 第 28–82 题 | 55 | 2 分 18 秒 |
| 优化后，Element Web 第 83–119 题 | 37 | 5 分 55 秒，包含两个下载异常 |
| 优化后全部已记录题目 | 92 | 3 分 45 秒 |

在 Ansible 样本中，镜像准备等其他步骤的平均开销由约 **134 秒**降至约 **21 秒**，表明预下载和缓存确实减少了前台等待。但前后是不同题目，并非同题重跑的对照实验，不能将平均耗时差直接解释为固定加速倍数。后续 Element Web 的模型执行时间较长，还发生下载超时，整体耗时随之上升。

此前“剩余约 23 小时”的估计基于优化后最早 7 道题的速度；后续记录说明，这个小样本不足以稳定预测其他仓库的运行时间。

### 流量与费用记录的限制

启动器没有保存逐题镜像下载字节数、网络流量计数、模型 Token 用量或接口账单金额，因此本报告**不能准确计算总流量及模型调用费用**。镜像缓存大小、补丁大小和模型轮数均不能直接代替这些数据。

并行预下载主要缩短等待时间，不会自动减少每道新题所需的镜像数据量。缓存可复用共同镜像层，但本次没有足够的网络计量数据量化节省幅度；停止时已预下载的后续镜像也可能消耗流量，却不会计入已完成题数。

## 6. 未通过、异常和中断的区别

### 6.1 智能体结束状态

| 解题阶段结束状态 | 通过 | 未通过 | 执行异常 | 合计 |
| --- | ---: | ---: | ---: | ---: |
| 模型不再发出工具调用后结束（finished） | 69 | 4 | 0 | 73 |
| 达到轮数上限后结束（step_limit） | 23 | 21 | 0 | 44 |
| 尚未启动解题（not_started） | 0 | 0 | 2 | 2 |

117 道进入解题的已评分题目累计记录 **2590 轮模型调用尝试**，不包含第 120 题及被旧尝试覆盖的记录。该轮数不等同于成功请求数或账单请求数。

25 道未通过题目中，有 21 道达到轮数上限；这说明轮数限制值得在复盘时关注，但不能仅凭相关性认定增加轮数就会通过。也有 23 道达到上限的题目最终通过了官方验证。

### 6.2 镜像下载异常

| 本地编号 | 仓库 | 记录耗时 | 异常 |
| --- | --- | ---: | --- |
| [0102](/D:/Study/Pycharm/Projects/mini_swe_agent_demo/pro_v2_runs/full/cases/0102/result.json) | Element Web | 20 分 56 秒 | 镜像下载达到准备时间上限，模型未启动 |
| [0110](/D:/Study/Pycharm/Projects/mini_swe_agent_demo/pro_v2_runs/full/cases/0110/result.json) | Element Web | 21 分 16 秒 | 镜像下载达到准备时间上限，模型未启动 |

这两题记为执行异常，不归入 25 道修复未通过题目。由于下载可以提前开始，记录的本题耗时不等于该镜像全部下载尝试的总时长。

此前第 15、16 题出现过下载中断，恢复运行后两题均已通过；本报告按每题当前最终结果统计，没有将历史下载故障重复计入现存的两个异常。

### 6.3 手动停止时的第 120 题

题号：`instance_element-hq__element-web-b7fea97bb68c6628a644580076f840109132f074-vnan`。

该题留下了消息历史、轨迹和解题日志，记录到第 **18** 轮，并出现 `KeyboardInterrupt`。没有最终 `result.json`、导出的 `model.patch` 或官方评分结果，因此**不计入 119 条最终结果，也不判为未通过**；它包含在尚无最终结果的 523 题中。

## 7. 未通过题目明细

下表的“必需测试通过数”取自验证日志的 `Required tests that passed`，分母取自 `Required tests`。日志中的 `Passed tests` 可能包含额外测试，不能直接用于判断是否满足全部必需测试。

“测试线索”仅概括未通过测试所在模块，不代表已经定位源码根因。点击本地编号可查看完整题号及对应尝试目录。

| 本地编号 | 仓库 | 必需测试通过数 | 模型轮数 | 测试线索 |
| --- | --- | ---: | ---: | --- |
| [0010](/D:/Study/Pycharm/Projects/mini_swe_agent_demo/pro_v2_runs/full/cases/0010/result.json) | Ansible | 21 / 25 | 30 | YAML 序列化、信任信息与来源信息 |
| [0020](/D:/Study/Pycharm/Projects/mini_swe_agent_demo/pro_v2_runs/full/cases/0020/result.json) | Ansible | 38 / 48 | 30 | 挂载信息、去重与超时处理 |
| [0022](/D:/Study/Pycharm/Projects/mini_swe_agent_demo/pro_v2_runs/full/cases/0022/result.json) | Ansible | 18 / 20 | 30 | 委托主机变量 |
| [0035](/D:/Study/Pycharm/Projects/mini_swe_agent_demo/pro_v2_runs/full/cases/0035/result.json) | Ansible | 23 / 41 | 15 | NXOS VRF 路由目标 |
| [0036](/D:/Study/Pycharm/Projects/mini_swe_agent_demo/pro_v2_runs/full/cases/0036/result.json) | Ansible | 3 / 5 | 30 | ICX 链路聚合 |
| [0042](/D:/Study/Pycharm/Projects/mini_swe_agent_demo/pro_v2_runs/full/cases/0042/result.json) | Ansible | 0 / 74 | 30 | Galaxy 集合与令牌相关测试 |
| [0052](/D:/Study/Pycharm/Projects/mini_swe_agent_demo/pro_v2_runs/full/cases/0052/result.json) | Ansible | 45 / 46 | 30 | 多部分表单构造 |
| [0057](/D:/Study/Pycharm/Projects/mini_swe_agent_demo/pro_v2_runs/full/cases/0057/result.json) | Ansible | 3 / 6 | 30 | F5 消息路由 |
| [0060](/D:/Study/Pycharm/Projects/mini_swe_agent_demo/pro_v2_runs/full/cases/0060/result.json) | Ansible | 1 / 2 | 10 | Linux 硬件信息采集 |
| [0061](/D:/Study/Pycharm/Projects/mini_swe_agent_demo/pro_v2_runs/full/cases/0061/result.json) | Ansible | 69 / 71 | 25 | 集合清单生成与参数互斥 |
| [0064](/D:/Study/Pycharm/Projects/mini_swe_agent_demo/pro_v2_runs/full/cases/0064/result.json) | Ansible | 47 / 48 | 30 | gzip 响应处理 |
| [0067](/D:/Study/Pycharm/Projects/mini_swe_agent_demo/pro_v2_runs/full/cases/0067/result.json) | Ansible | 1 / 5 | 30 | NXOS 接口 |
| [0069](/D:/Study/Pycharm/Projects/mini_swe_agent_demo/pro_v2_runs/full/cases/0069/result.json) | Ansible | 9 / 10 | 30 | pip 模块探测异常处理 |
| [0070](/D:/Study/Pycharm/Projects/mini_swe_agent_demo/pro_v2_runs/full/cases/0070/result.json) | Ansible | 49 / 58 | 30 | Galaxy 接口缓存 |
| [0076](/D:/Study/Pycharm/Projects/mini_swe_agent_demo/pro_v2_runs/full/cases/0076/result.json) | Ansible | 157 / 168 | 30 | Galaxy 命令行集合安装与路径 |
| [0080](/D:/Study/Pycharm/Projects/mini_swe_agent_demo/pro_v2_runs/full/cases/0080/result.json) | Ansible | 11 / 15 | 30 | PowerShell 错误流解析 |
| [0084](/D:/Study/Pycharm/Projects/mini_swe_agent_demo/pro_v2_runs/full/cases/0084/result.json) | Element Web | 0 / 3 | 30 | 外部链接组件 |
| [0091](/D:/Study/Pycharm/Projects/mini_swe_agent_demo/pro_v2_runs/full/cases/0091/result.json) | Element Web | 173 / 174 | 30 | 安全设置中的集成管理器 |
| [0095](/D:/Study/Pycharm/Projects/mini_swe_agent_demo/pro_v2_runs/full/cases/0095/result.json) | Element Web | 47 / 48 | 30 | 会话重命名 |
| [0096](/D:/Study/Pycharm/Projects/mini_swe_agent_demo/pro_v2_runs/full/cases/0096/result.json) | Element Web | 351 / 352 | 30 | 消息差异的复杂转换 |
| [0100](/D:/Study/Pycharm/Projects/mini_swe_agent_demo/pro_v2_runs/full/cases/0100/result.json) | Element Web | 60 / 61 | 30 | 退出会话后的账户数据清理 |
| [0103](/D:/Study/Pycharm/Projects/mini_swe_agent_demo/pro_v2_runs/full/cases/0103/result.json) | Element Web | 60 / 63 | 30 | 语音广播播放与时间状态 |
| [0116](/D:/Study/Pycharm/Projects/mini_swe_agent_demo/pro_v2_runs/full/cases/0116/result.json) | Element Web | 199 / 201 | 30 | 用户与房间标记组件 |
| [0117](/D:/Study/Pycharm/Projects/mini_swe_agent_demo/pro_v2_runs/full/cases/0117/result.json) | Element Web | 281 / 283 | 30 | 置顶消息横幅 |
| [0119](/D:/Study/Pycharm/Projects/mini_swe_agent_demo/pro_v2_runs/full/cases/0119/result.json) | Element Web | 6 / 7 | 9 | 数组平滑重采样 |

## 8. 证据来源与核对范围

- [汇总统计 summary.json](/D:/Study/Pycharm/Projects/mini_swe_agent_demo/pro_v2_runs/full/summary.json)：任务总数、各结果状态数量及待处理数量。
- [逐题结果 results.jsonl](/D:/Study/Pycharm/Projects/mini_swe_agent_demo/pro_v2_runs/full/results.jsonl)：119 条最终结果。
- [运行配置 run_config.json](/D:/Study/Pycharm/Projects/mini_swe_agent_demo/pro_v2_runs/full/run_config.json)：题目列表、数据集提交、模型、接口及执行上限。
- [逐题记录目录 cases](/D:/Study/Pycharm/Projects/mini_swe_agent_demo/pro_v2_runs/full/cases)：每题的结果、轨迹、补丁和验证日志；具体尝试目录以各题 `result.json` 的 `case_dir` 为准。
- [批量启动器源码](/D:/Study/Pycharm/Projects/mini_swe_agent_demo/src/mini_swe_agent_demo/docker_bash/run_pro_v2.py)：评分、缓存及续跑逻辑。

生成报告时，已核对汇总数量、119 份逐题结果和 119 行结果清单的一致性，并逐一检查 117 道有效评分题目的验证日志结果标记与奖励文件；未发现不一致。25 道未通过题目的必需测试计数也来自各自验证日志。

本报告保存的是停止后的结果快照。未重新运行模型、Docker 容器或基准测试，未修改原始评测记录，也未逐题审查补丁正确性或重新判定未通过题目的根因。
