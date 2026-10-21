import subprocess
import sys
from pathlib import Path

dir = Path(__file__).resolve().parent / "workspace"


def inspect_files() -> str:
    files = ""
    for file in dir.iterdir():
        if file.is_file():
            files += file.name + "\n"
    return files


def read_file(filename: str) -> str:
    filepath = dir.joinpath(filename).resolve()
    if not filepath.is_relative_to(dir):
        return "Error: access denied"
    if not filepath.is_file():
        return "Error: file not found"
    try:
        with open(filepath, "r") as f:
            content = f.read()
        return content
    except OSError:
        return "Error: process failed"
    except UnicodeError:
        return "Error: unicode error"


def write_file(filename: str, content: str) -> str:
    filepath = dir.joinpath(filename).resolve()
    if not filepath.is_relative_to(dir):
        return "Error: access denied"
    if not filepath.parent.exists():
        filepath.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(filepath, "w") as f:
            f.write(content)
        return "Success"
    except OSError:
        return "Error: process failed"


def run_tests() -> str:
    try:
        result = subprocess.run(
            args=[sys.executable, "-m", "unittest", "discover"],
            shell=False,
            cwd=dir,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        output = ""
        output += f"Exit code:{result.returncode}\n"
        output += "STDOUT:\n" + result.stdout + "\n"
        output += "STDERR:\n" + result.stderr + "\n"
        return output
    except subprocess.TimeoutExpired:
        return "Error: test timeout"
    except OSError:
        return "Error: process failed"
