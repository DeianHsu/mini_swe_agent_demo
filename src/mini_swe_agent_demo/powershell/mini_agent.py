import json
from textwrap import dedent

from ai.testing import tool_call

from mini_swe_agent_demo.powershell.use_llm import *
from mini_swe_agent_demo.powershell.environment import execute


def model(task: str, history: list) -> dict:
    messages = []
    prompt = dedent("""
        你是一个文件检查 Agent。
        执行环境是 Windows PowerShell 5.1，当前目录为工作区。
        需要执行操作时，通过 execute 工具调用提交 PowerShell 脚本。
        查看、修改文件和运行测试都通过该工具完成。
        任务完成后，以普通文本回复 finish。
        完成任务时只返回 finish。
        根据执行结果继续操作；每轮都是独立进程。
    """).strip()
    messages.append({
        "role": "system",
        "content": prompt
    })
    messages.append({
        "role": "user",
        "content": task
    })
    messages.extend(history)
    response = use_llm_with_tools(messages)
    return response


def agent(task: str) -> list:
    history = []
    for i in range(0, 10):
        assistant_message = model(task, history)
        history.append(assistant_message)
        tool_calls = assistant_message.get("tool_calls") or []
        if not tool_calls:
            print("模型正文：", assistant_message.get("content"))
            break
        else:
            for tool_call in tool_calls:
                tool_name = tool_call["function"]["name"]

                if tool_name != "execute":
                    result = f"Error: 未知工具 {tool_name}"
                else:
                    try:
                        arguments = json.loads(tool_call["function"]["arguments"])
                    except (json.JSONDecodeError, TypeError) as e:
                        result = f"Error: 参数解析失败：{e}"
                    else:
                        if not isinstance(arguments, dict):
                            result = "Error: 参数必须是 JSON 对象"
                        elif not isinstance(arguments.get("command"), str):
                            result = "Error: command 必须是字符串"
                        else:
                            result = execute(arguments["command"])
                history.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": result
                })

    return history


if __name__ == "__main__":
    task = dedent(r"""
        工作区中的 calc.py 存在错误，test_calc.py 定义了预期行为。
        只允许修改 calc.py，保持测试文件不变。

        必须使用以下 PowerShell 脚本运行测试，
        将这两行作为一次 execute 工具调用的完整脚本：

        & 'D:\Study\Pycharm\Projects\mini_swe_agent_demo\.venv\Scripts\python.exe' -m unittest -v test_calc
        exit $LASTEXITCODE

        先运行测试确认失败，再检查并修复 calc.py，
        最后使用相同脚本重新测试，全部通过后回复 finish。
    """).strip()
    history = agent(task)
    for msg in history:
        print(msg)
