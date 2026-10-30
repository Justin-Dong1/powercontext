"""Bounded local seekdb launcher for experiment-owned data directories."""

from contextlib import contextmanager
from pathlib import Path
import os, socket, subprocess, time
import pymysql


@contextmanager
def local_server(binary, directory):
    binary, directory = Path(binary).resolve(), Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    process = None
    try:
        with (directory / "console.log").open("w", encoding="utf8") as log:
            process = subprocess.Popen(
                [
                    str(binary),
                    "--nodaemon",
                    "--base-dir",
                    str(directory),
                    "--port",
                    str(port),
                    "--parameter",
                    "mysql_port_mode=specified",
                    "--parameter",
                    "mysql_port=" + str(port),
                    "--parameter",
                    "memory_budget=1G",
                    "--parameter",
                    "datafile_size=32M",
                    "--parameter",
                    "log_disk_size=2G",
                    "--log-level",
                    "WARN",
                ],
                cwd=directory,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(
                        "Kernel exited; see " + str(directory / "console.log")
                    )
                try:
                    c = pymysql.connect(
                        host="127.0.0.1",
                        port=port,
                        user="root",
                        connect_timeout=2,
                        read_timeout=3,
                    )
                    with c.cursor() as cur:
                        cur.execute("SELECT 1")
                    c.close()
                    break
                except pymysql.Error:
                    time.sleep(1)
            else:
                raise TimeoutError("Local kernel did not become ready in 120 seconds")
            yield {"host": "127.0.0.1", "port": port, "user": "root", "password": ""}
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
