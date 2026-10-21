import subprocess
import sys
from pathlib import Path

dir = Path(__file__).resolve().parent.parent / "workspace"


def execute(command: str) -> str:
    script = "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new();\n" + command
    args = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        script,
    ]

    try:
        result = subprocess.run(
            args=args,
            shell=False,
            cwd=dir,
            capture_output=True,
            text=True,
            timeout=10,
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
