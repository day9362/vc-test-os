import json
import re
import shutil
import subprocess
from pathlib import Path

from app.core.errors import AppError

IMAGE = "vc-test-os-sandbox:1"
_BANNED = ("subprocess", "socket", "urllib", "requests", "httpx", "ctypes", "os.system", "os.popen", "eval(", "open(")
_BANNED_KEYS = {"__proto__", "constructor", "prototype", "renderItem"}
_UNSAFE_TEXT = ("javascript:", "<script", "function", "=>")


def reject_code(code: str) -> str:
    folded = code.lower()
    if re.search(r"(^|\n)\s*(import|from)\s+os\b", code):
        return "代码不能使用 os"
    for word in _BANNED:
        if word in folded:
            return f"代码不能使用 {word}"
    return ""


def sanitize_option(value: object, depth: int = 0) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict) or depth > 8:
        raise AppError(502, "AGENT_FAILED", "图表配置不是可用的数据")
    cleaned = _plain(value, depth)
    if not isinstance(cleaned, dict) or not cleaned:
        raise AppError(502, "AGENT_FAILED", "图表配置不是可用的数据")
    return cleaned


def run_in_sandbox(work: Path, out: Path) -> str:
    if shutil.which("docker") is None:
        return "这台机器没有 Docker，分析沙箱没有启动"
    name = f"vcos-{work.name}"
    command = [
        "docker", "run", "--name", name, "--rm",
        "--network", "none", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--memory", "512m", "--pids-limit", "64", "--cpus", "1",
        "--tmpfs", "/tmp:rw,size=64m",
        "-v", f"{work.resolve()}:/work:ro",
        "-v", f"{out.resolve()}:/out",
        "-e", "MPLCONFIGDIR=/tmp",
        IMAGE,
        "python", "/opt/runner/runner.py",
    ]
    try:
        completed = subprocess.run(command, timeout=60, capture_output=True, text=True, check=False)
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "kill", name], timeout=20, capture_output=True, check=False)
        return "执行超过 60 秒"
    except OSError:
        return "分析沙箱没有启动"
    error_file = out / "error.txt"
    if error_file.exists():
        return error_file.read_text(encoding="utf-8")[-2000:]
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        if "No such image" in detail or "Unable to find image" in detail:
            return "分析沙箱镜像还没有准备好"
        return detail[-2000:] or "沙箱执行失败"
    return ""


def read_result(out: Path) -> tuple[dict, bool]:
    path = out / "result.json"
    if not path.exists():
        return {}, False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}, False
    return (data if isinstance(data, dict) else {}), (out / "figure.png").exists()


def _plain(value: object, depth: int) -> object:
    if depth > 8:
        raise AppError(502, "AGENT_FAILED", "图表配置不是可用的数据")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        lowered = value.lower()
        if any(token in lowered for token in _UNSAFE_TEXT):
            raise AppError(502, "AGENT_FAILED", "图表配置里有不能执行的内容")
        return value
    if isinstance(value, list):
        return [_plain(item, depth + 1) for item in value[:500]]
    if isinstance(value, dict):
        cleaned = {}
        for key, item in list(value.items())[:80]:
            name = str(key)
            if name in _BANNED_KEYS:
                raise AppError(502, "AGENT_FAILED", "图表配置里有不能执行的内容")
            cleaned[name] = _plain(item, depth + 1)
        return cleaned
    raise AppError(502, "AGENT_FAILED", "图表配置不是可用的数据")
