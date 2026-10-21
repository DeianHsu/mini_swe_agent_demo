import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_BASE_URL"),
)

def use_llm(messages: list[dict]) -> str:
    response = client.chat.completions.create(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
        messages=messages,
        extra_body={
            "thinking": {"type": "disabled"}
        },
    )
    return response.choices[0].message.content or ""


def use_llm_with_tools(messages: list[dict]) -> dict:
    tools_schema = [
        {
            "type": "function",
            "function": {
                "name": "execute",
                "description": "在容器工作区执行 Bash 脚本",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "需要执行的 Bash 脚本"
                        }
                    },
                    "required": ["command"]
                }
            }
        }
    ]

    response = client.chat.completions.create(
        tools=tools_schema,
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
        messages=messages,
        extra_body={
            "thinking": {"type": "disabled"}
        },
    )
    return response.choices[0].message.to_dict()
