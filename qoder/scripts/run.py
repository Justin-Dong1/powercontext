"""One-command launcher: PowerContext Server + ResearchTrail web app.

Usage:
    python scripts/run.py            # start both, Ctrl+C to stop
    python scripts/run.py --reuse    # reuse an already running PowerContext

Environment variables are read from .env when present (see .env.example).
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

APP_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(APP_ROOT / ".env")
sys.path.insert(0, str(APP_ROOT))

DEFAULT_PC_URL = "http://127.0.0.1:8765"


def _path_from_env(name: str, default: Path) -> Path:
    raw = os.environ.get(name, "").strip()
    return Path(raw).expanduser().resolve() if raw else default.resolve()


def _wait_healthy(url: str, deadline: float, process: subprocess.Popen[bytes] | None, log_path: Path) -> None:
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            tail = ""
            if log_path.exists():
                tail = "\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-20:])
            raise SystemExit(f"PowerContext Server 提前退出（code={process.returncode}）。\n--- 日志 ---\n{tail}")
        try:
            with urllib.request.urlopen(f"{url}/health/live", timeout=1.5) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.5)
    raise SystemExit(f"等待 PowerContext Server 就绪超时：{url}/health/live（日志：{log_path}）")


def _port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def main() -> int:
    parser = argparse.ArgumentParser(description="启动 PowerContext Server 与 ResearchTrail")
    parser.add_argument("--reuse", action="store_true", help="复用已运行的 PowerContext Server")
    parser.add_argument("--no-powercontext", action="store_true", help="只启动 Web 应用（需已有 Server）")
    args = parser.parse_args()

    pc_url = os.environ.get("RT_POWERCONTEXT_URL", DEFAULT_PC_URL).rstrip("/")
    parity = urlsplit(pc_url)
    pc_host = parity.hostname or "127.0.0.1"
    pc_port = parity.port or 8765

    data_dir = _path_from_env("RT_DATA_DIR", APP_ROOT / "data" / "app")
    database_path = _path_from_env("RT_DATABASE_PATH", data_dir / "researchtrail.sqlite3")
    pc_home = _path_from_env("POWERCONTEXT_HOME", APP_ROOT / "data" / "powercontext")
    log_dir = _path_from_env("RT_LOG_DIR", APP_ROOT / "data" / "logs")
    for directory in (data_dir, database_path.parent, pc_home, log_dir):
        directory.mkdir(parents=True, exist_ok=True)

    os.environ["RT_DATA_DIR"] = str(data_dir)
    os.environ["RT_DATABASE_PATH"] = str(database_path)
    os.environ["RT_POWERCONTEXT_URL"] = pc_url
    os.environ["POWERCONTEXT_HOME"] = str(pc_home)
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    pc_process: subprocess.Popen[bytes] | None = None
    pc_log = log_dir / "powercontext.log"
    reuse = args.reuse or args.no_powercontext or os.environ.get("RT_REUSE_POWERCONTEXT") == "1"

    already_up = _port_open(pc_host, pc_port)
    if already_up and not reuse:
        print(f"[run] {pc_url} 已被占用：将复用该 PowerContext Server（数据目录可能不同）。")
        reuse = True

    if not reuse:
        print(f"[run] 启动 PowerContext Server: {pc_url}  POWERCONTEXT_HOME={pc_home}")
        command = [
            sys.executable,
            "-c",
            "from powercontext.cli.app import main; main()",
            "server",
            "run",
            "--host",
            pc_host,
            "--port",
            str(pc_port),
            "--role",
            "all",
            "--no-env-file",
        ]
        with pc_log.open("ab") as log_file:
            pc_process = subprocess.Popen(
                command,
                cwd=APP_ROOT,
                env=os.environ.copy(),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
            )
        try:
            _wait_healthy(pc_url, time.monotonic() + 90, pc_process, pc_log)
        except SystemExit:
            if pc_process.poll() is None:
                pc_process.terminate()
            raise
        print(f"[run] PowerContext 就绪（日志：{pc_log}）")
    else:
        _wait_healthy(pc_url, time.monotonic() + 15, None, pc_log)
        print(f"[run] 复用 PowerContext Server: {pc_url}")

    host = os.environ.get("RT_HOST", "127.0.0.1")
    port = int(os.environ.get("RT_PORT", "8000"))
    print(f"[run] ResearchTrail: http://{host}:{port}  （Ctrl+C 停止）")
    print(f"[run] 数据目录: {data_dir}")
    print("[run] 未启动浏览器，请手动打开上面的地址。")

    import uvicorn

    try:
        uvicorn.run("app.main:app", host=host, port=port, log_level="info", app_dir=str(APP_ROOT))
    finally:
        if pc_process is not None and pc_process.poll() is None:
            print("[run] 停止 PowerContext Server ...")
            pc_process.terminate()
            try:
                pc_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pc_process.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
