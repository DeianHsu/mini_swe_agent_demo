# mini-swe-agent-demo

一个参考 [mini-SWE-agent](https://github.com/SWE-agent/mini-swe-agent) 手写的 Python 智能体（Agent）学习项目。

模型通过命令读取文件、修改代码和运行测试，程序将执行结果写回消息历史，驱动下一轮操作。项目围绕模型接口、执行环境和智能体循环展开，保留两种调用协议与两套执行环境，便于阅读和比较。

## 功能

- 文本协议：将模型正文作为 PowerShell 脚本执行。
- 原生工具调用（Function Calling）：解析模型返回的工具参数，执行命令并反馈结果。
- 两套执行环境：本机 Windows PowerShell，以及 Docker 容器中的 Linux Bash。
- SWE-bench Pro V2 本地批量评测入口。

| 协议 | 动作来源 | 结果反馈 | 执行环境 |
| --- | --- | --- | --- |
| 文本协议 | 模型回复正文 | `user` 消息 | PowerShell |
| 原生工具调用 | `tool_calls` 中的 `command` | 关联调用编号的 `tool` 消息 | PowerShell、Docker Bash |

## 项目结构

```text
src/mini_swe_agent_demo/
├── powershell/
│   ├── mini_agent_text.py   # 文本协议
│   ├── mini_agent.py        # 原生工具调用
│   ├── environment.py       # PowerShell 命令执行
│   └── use_llm.py           # 模型接口
├── docker_bash/
│   ├── mini_agent.py        # 原生工具调用
│   ├── environment.py       # Docker Bash 命令执行
│   ├── use_llm.py           # 模型接口
│   └── run_pro_v2.py        # Pro V2 评测入口
└── workspace/              # 本机示例文件
```

`model()` 组织提示与消息历史，`agent()` 控制循环并调度工具，`execute()` 执行命令并返回退出码和输出。两套环境各自维护代码，共用项目依赖和模型配置。

## 安装与配置

需要 Python 3.14+ 和 uv。PowerShell 示例使用 Windows PowerShell 5.1；Docker 示例需要 Docker Desktop 的 Linux 引擎。

在项目根目录安装依赖：

```powershell
uv sync
```

在根目录创建 `.env`，填写模型服务配置：

```dotenv
DEEPSEEK_API_KEY=你的密钥
DEEPSEEK_BASE_URL=模型接口地址
DEEPSEEK_MODEL=模型名称
```

模型接口通过 OpenAI Python SDK 调用。当前请求使用 DeepSeek 的 `thinking` 参数，原生工具调用版本还要求服务支持 `tools`。`.env` 已加入 Git 忽略规则。

## 运行示例

以下命令均在项目根目录的 PowerShell 中执行，运行时会调用配置的模型服务。

### PowerShell

```powershell
# 文本协议：列出文件并读取 hello.txt
& '.\.venv\Scripts\python.exe' -m mini_swe_agent_demo.powershell.mini_agent_text

# 原生工具调用：修复工作区中的 calc.py
& '.\.venv\Scripts\python.exe' -m mini_swe_agent_demo.powershell.mini_agent
```

示例任务位于入口文件的 `if __name__ == "__main__":` 中。本机工作区是 `src/mini_swe_agent_demo/workspace/`；修复示例中的 Python 解释器路径需按本机环境调整。

### Docker Bash

首次创建示例容器并准备文件：

```powershell
docker run -d --name mini-swe-learning -w /workspace python:3.14-slim sleep infinity
docker exec -w /workspace mini-swe-learning bash -lc 'echo Hello Agent! > hello.txt'
```

容器运行后启动智能体：

```powershell
& '.\.venv\Scripts\python.exe' -m mini_swe_agent_demo.docker_bash.mini_agent
```

已有容器停止后可通过 `docker start mini-swe-learning` 再次启动。容器内工作区与本机示例目录相互独立。

### SWE-bench Pro V2

评测入口需要 Git 和 [SWE-bench Pro 任务仓库](https://github.com/scaleapi/SWE-bench_Pro-os)。默认从本项目同级的 `SWE-bench-Pro-V2/v2/tasks/` 读取任务：

```powershell
& '.\.venv\Scripts\python.exe' -X utf8 -u -m mini_swe_agent_demo.docker_bash.run_pro_v2
```

结果默认保存在 `pro_v2_runs/full/`。完整参数可通过该模块的 `--help` 查看。
