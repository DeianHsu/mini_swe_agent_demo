from textwrap import dedent

from mini_swe_agent_demo.powershell.environment import *
from mini_swe_agent_demo.powershell.use_llm import *


def model(task: str, history: list) -> str:
    messages = []
    prompt = dedent("""
        你是一个通过 PowerShell 操作文件的智能体。
        执行环境是 Windows PowerShell 5.1，当前目录为工作区。
        需要操作时，只返回可直接执行的 PowerShell 脚本，可以包含多行。
        不要输出解释，不要使用 Markdown 代码围栏。
        每次脚本都在独立进程中执行，请根据收到的执行结果继续操作。
        任务完成时，只返回 finish。
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
    response = use_llm(messages)
    return response.strip()


def agent(task: str) -> list:
    history = []
    for i in range(0, 10):
        command = model(task, history)
        history.append({
            "role": "assistant",
            "content": command,
        })
        if command == "finish":
            break
        else:
            result = execute(command)
            history.append({
                "role": "user",
                "content": result,
            })

    return history


if __name__ == "__main__":
    task = dedent(r"""
        查看工作区中的文件列表，然后读取 hello.txt 的完整内容。
        只执行查看操作，完成后回复 finish。
    """).strip()
    history = agent(task)
    for msg in history:
        print(msg)
