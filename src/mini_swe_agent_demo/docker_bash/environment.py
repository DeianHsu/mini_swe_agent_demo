import subprocess
import sys
from pathlib import Path

dir = Path(__file__).resolve().parent.parent / "workspace"


def execute(command: str, *, container_name: str = "mini-swe-learning", workdir: str = "/workspace",
            timeout: int = 10, ) -> str:
    args = [
        "docker",
        "exec",
        "-w",
        workdir,
        container_name,
        "bash",
        "-c",
        command,
    ]

    try:
        result = subprocess.run(
            args=args,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            encoding="utf-8",
        )
        output = ""
        output += f"Exit code:{result.returncode}\n"
        output += "STDOUT:\n" + result.stdout + "\n"
        output += "STDERR:\n" + result.stderr + "\n"
        return output
    except subprocess.TimeoutExpired:
        return "Error: command timeout"
    except OSError as e:
        return f"Error: process failed: {e}"

