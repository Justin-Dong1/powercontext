"""Real end-to-end acceptance run for ResearchTrail.

Starts an isolated PowerContext Server and the web app on dedicated ports,
exercises every required flow, kills both processes, restarts them, and
verifies that project state, documents, evidence and progress survive.

Run:
    .venv/Scripts/python.exe scripts/verify_acceptance.py
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

APP_ROOT = Path(__file__).resolve().parent.parent
RUN_ID = datetime.now().strftime("%Y%m%d-%H%M%S")
RUN_DIR = APP_ROOT / "data" / "acceptance" / RUN_ID
LOG_DIR = RUN_DIR / "logs"
PC_PORT = 18765
APP_PORT = 18000
PC_URL = f"http://127.0.0.1:{PC_PORT}"
APP_URL = f"http://127.0.0.1:{APP_PORT}"
EVIDENCE_OUT = APP_ROOT / "evidence" / "logs"
QUERY = "缩放点积注意力"
EXPECTED_SNIPPET = "缩放点积注意力先计算查询向量与键向量的点积"
EXPECTED_SOURCE = "演示资料/01-注意力机制课程笔记.md"


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def wait_http(url: str, timeout: float, predicate=None) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                body = json.loads(response.read().decode("utf-8"))
                if predicate is None or predicate(body):
                    return body
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            pass
        time.sleep(0.5)
    return None


@dataclass
class Stack:
    processes: list[subprocess.Popen[bytes]] = field(default_factory=list)
    handles: list[Any] = field(default_factory=list)

    def _spawn(self, name: str, command: list[str], env: dict[str, str]) -> subprocess.Popen[bytes]:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handle = (LOG_DIR / f"{name}.log").open("ab")
        self.handles.append(handle)
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        process = subprocess.Popen(
            command,
            cwd=APP_ROOT,
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=flags,
        )
        self.processes.append(process)
        return process

    def start(self) -> None:
        env = os.environ.copy()
        env.update(
            {
                "POWERCONTEXT_HOME": str(RUN_DIR / "powercontext"),
                "RT_DATA_DIR": str(RUN_DIR / "app"),
                "RT_DATABASE_PATH": str(RUN_DIR / "app" / "researchtrail.sqlite3"),
                "RT_POWERCONTEXT_URL": PC_URL,
                "RT_HOST": "127.0.0.1",
                "RT_PORT": str(APP_PORT),
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
            }
        )
        (RUN_DIR / "powercontext").mkdir(parents=True, exist_ok=True)
        (RUN_DIR / "app").mkdir(parents=True, exist_ok=True)
        pc = self._spawn(
            "powercontext",
            [
                sys.executable,
                "-c",
                "from powercontext.cli.app import main; main()",
                "server",
                "run",
                "--host",
                "127.0.0.1",
                "--port",
                str(PC_PORT),
                "--role",
                "all",
                "--no-env-file",
            ],
            env,
        )
        if wait_http(f"{PC_URL}/health/live", 120) is None:
            raise RuntimeError(f"PowerContext 启动失败，日志：{LOG_DIR / 'powercontext.log'}")
        self._spawn(
            "app",
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(APP_PORT),
                "--log-level",
                "info",
            ],
            env,
        )
        if wait_http(f"{APP_URL}/api/health", 60, lambda body: body.get("ok") is True) is None:
            raise RuntimeError(f"ResearchTrail 启动失败，日志：{LOG_DIR / 'app.log'}")
        _ = pc

    def stop(self) -> None:
        for process in reversed(self.processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
        self.processes.clear()
        for handle in self.handles:
            handle.close()
        self.handles.clear()


class Checks:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def check(self, name: str, ok: bool, detail: str) -> bool:
        self.items.append({"name": name, "ok": bool(ok), "detail": detail, "at": now()})
        marker = "PASS" if ok else "FAIL"
        print(f"[{marker}] {name} :: {detail}", flush=True)
        return bool(ok)

    def require(self, name: str, ok: bool, detail: str) -> None:
        if not self.check(name, ok, detail):
            raise RuntimeError(f"必须通过的检查失败：{name}")

    @property
    def failed(self) -> int:
        return sum(1 for item in self.items if not item["ok"])


def create_project(client: httpx.Client, title: str, goal: str) -> dict[str, Any]:
    response = client.post(f"{APP_URL}/api/projects", json={"title": title, "goal": goal})
    response.raise_for_status()
    return response.json()["project"]


def progress_of(client: httpx.Client, project_id: str) -> dict[str, Any]:
    response = client.get(f"{APP_URL}/api/projects/{project_id}/progress")
    response.raise_for_status()
    return response.json()["progress"]


def pc_snapshot() -> dict[str, Any]:
    from powercontext.client import PowerContextClient
    from powercontext.http import ListMemoryEntriesRequest

    async def collect() -> dict[str, Any]:
        client = PowerContextClient(PC_URL)
        try:
            scopes = await client.list_scopes(limit=100)
            result: dict[str, Any] = {"scopes": [], "entries": {}}
            for scope in scopes.items:
                marker = any(
                    ref.kind == "researchtrail.project" and ref.value == "v1"
                    for ref in scope.external_references
                )
                result["scopes"].append(
                    {
                        "scope_id": scope.scope_id,
                        "title": scope.title,
                        "marker": marker,
                        "summary": scope.summary,
                    }
                )
                entries = []
                cursor = None
                while True:
                    page = await client.list_memory_entries(
                        ListMemoryEntriesRequest(scope_id=scope.scope_id, limit=100, cursor=cursor)
                    )
                    entries.extend(
                        {
                            "kind": entry.kind,
                            "state": str(entry.state),
                            "artifact_id": entry.artifact.artifact_id,
                            "text": entry.text,
                        }
                        for entry in page.entries
                    )
                    cursor = page.next_cursor
                    if not cursor:
                        break
                result["entries"][scope.scope_id] = entries
            return result
        finally:
            await client.aclose()

    return asyncio.run(collect())


def active(entries: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [item for item in entries if item["kind"] == kind and item["state"] == "active"]


def database_files() -> list[dict[str, Any]]:
    files = []
    for path in sorted((RUN_DIR / "powercontext").rglob("*")):
        if path.is_file():
            files.append({"path": str(path.relative_to(RUN_DIR)), "bytes": path.stat().st_size})
    return files


def write_artifacts(checks: Checks, state: dict[str, Any], error: str | None) -> None:
    EVIDENCE_OUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": RUN_ID,
        "started": RUN_ID,
        "finished": now(),
        "environment": {
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "powercontext_url": PC_URL,
            "app_url": APP_URL,
            "run_dir": str(RUN_DIR),
        },
        "checks": checks.items,
        "failed": checks.failed,
        "error": error,
        "state": state,
    }
    (EVIDENCE_OUT / "acceptance.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        f"# ResearchTrail 验收结果（{RUN_ID}）",
        "",
        f"- 执行时间：{RUN_ID} → {now()}",
        f"- 独立数据目录：`{RUN_DIR.relative_to(APP_ROOT)}`",
        f"- PowerContext：{PC_URL}（独立实例，role=all，SQLite）",
        f"- 应用：{APP_URL}",
        f"- 结论：{'全部通过' if checks.failed == 0 and not error else f'存在失败（{checks.failed}）'}",
        "",
        "| # | 检查项 | 结果 | 实测细节 |",
        "| --- | --- | --- | --- |",
    ]
    for index, item in enumerate(checks.items, start=1):
        detail = item["detail"].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {index} | {item['name']} | {'PASS' if item['ok'] else 'FAIL'} | {detail} |")
    if error:
        lines.extend(["", f"运行错误：`{error}`"])
    lines.extend(
        [
            "",
            "原始 JSON：`evidence/logs/acceptance.json`；服务日志：`evidence/logs/servers.log`。",
            "",
        ]
    )
    (EVIDENCE_OUT / "acceptance.md").write_text("\n".join(lines), encoding="utf-8")

    log_parts = [f"===== run {RUN_ID} ====="]
    for name in ("powercontext", "app"):
        path = LOG_DIR / f"{name}.log"
        if path.exists():
            log_parts.append(f"--- {name}.log ---")
            log_parts.append(path.read_text(encoding="utf-8", errors="replace"))
    (EVIDENCE_OUT / "servers.log").write_text("\n".join(log_parts), encoding="utf-8")


def run_checks(checks: Checks, state: dict[str, Any]) -> None:
    headers = {"Accept": "application/json"}
    with httpx.Client(timeout=30, headers=headers) as client:
        health = client.get(f"{APP_URL}/api/health")
        checks.require(
            "健康检查：应用 / SQLite / PowerContext 均可用",
            health.status_code == 200 and health.json().get("ok") is True,
            f"HTTP {health.status_code} {json.dumps(health.json(), ensure_ascii=False)}",
        )

        project_a = create_project(client, "演示项目 A · 注意力机制复习", "梳理注意力机制的核心概念，并整理可引用的课程证据。")
        project_b = create_project(client, "演示项目 B · RAG 实验", "比较检索增强与滑动窗口上下文方案，记录实验结论。")
        a_id, b_id = project_a["id"], project_b["id"]
        state["phase1"] = {"projects": {"A": project_a, "B": project_b}}
        checks.require(
            "创建两个隔离的研究项目",
            a_id != b_id and project_a["title"].startswith("演示项目 A") and project_b["title"].startswith("演示项目 B"),
            f"A={a_id} B={b_id}",
        )

        demo = client.post(f"{APP_URL}/api/projects/{a_id}/demo")
        demo_body = demo.json()
        checks.require(
            "导入固定演示资料（3 份合成笔记）",
            demo.status_code == 200 and len(demo_body["imported"]) == 3 and not demo_body["errors"],
            f"HTTP {demo.status_code} imported={len(demo_body.get('imported', []))} errors={demo_body.get('errors')}",
        )

        docs = client.get(f"{APP_URL}/api/projects/{a_id}/documents").json()["documents"]
        names = sorted(item["name"] for item in docs)
        total_paragraphs = sum(item["paragraph_count"] for item in docs)
        state["phase1"]["documents"] = docs
        checks.require(
            "资料保留文件名、相对来源、摘要与段落数",
            len(docs) == 3
            and total_paragraphs > 0
            and all(item["relative_source"].startswith("演示资料/") and item["summary"] for item in docs),
            f"documents={len(docs)} paragraphs={total_paragraphs} names={names}",
        )

        search = client.get(f"{APP_URL}/api/projects/{a_id}/search", params={"q": QUERY}).json()
        target = next(
            (
                item
                for item in search["results"]
                if EXPECTED_SNIPPET in item["text"] and item["relative_source"] == EXPECTED_SOURCE
            ),
            None,
        )
        state["phase1"]["search"] = search
        checks.require(
            "关键词检索返回原文段落与准确来源",
            search["count"] > 0 and target is not None,
            f"q={QUERY} count={search['count']} 命中段={target['paragraph_id'] if target else '无'}",
        )

        no_match = client.get(f"{APP_URL}/api/projects/{a_id}/search", params={"q": "量子纠缠冷聚变"}).json()
        checks.check(
            "无匹配时明确提示",
            no_match["count"] == 0 and "未找到" in no_match.get("message", ""),
            f"count={no_match['count']} message={no_match.get('message')}",
        )

        empty = client.get(f"{APP_URL}/api/projects/{a_id}/search", params={"q": "   "})
        checks.check(
            "空检索词被拒绝",
            empty.status_code == 400,
            f"HTTP {empty.status_code} detail={empty.json().get('detail')}",
        )

        sample_path = APP_ROOT / "samples" / "01-注意力机制课程笔记.md"
        duplicate = client.post(
            f"{APP_URL}/api/projects/{a_id}/documents",
            files={"files": (sample_path.name, sample_path.read_bytes(), "text/markdown")},
            data={"relative_paths": EXPECTED_SOURCE},
        )
        checks.check(
            "重复导入同一资料被拒绝",
            duplicate.status_code == 400 and "已导入" in duplicate.text,
            f"HTTP {duplicate.status_code} detail={duplicate.json().get('detail')}",
        )

        evidence_response = client.post(
            f"{APP_URL}/api/projects/{a_id}/evidence",
            json={"paragraph_id": target["paragraph_id"], "note": "用于组会引言，需与论文原文核对。"},
        )
        evidence = evidence_response.json().get("evidence", {})
        state["phase1"]["evidence"] = evidence
        checks.require(
            "收藏证据并保存备注（PowerContext Memory）",
            evidence_response.status_code == 201
            and evidence.get("quote") == target["text"]
            and evidence.get("note") == "用于组会引言，需与论文原文核对。"
            and evidence.get("relative_source") == EXPECTED_SOURCE,
            f"HTTP {evidence_response.status_code} evidence_id={evidence.get('evidence_id')} source={evidence.get('relative_source')}",
        )

        duplicate_evidence = client.post(
            f"{APP_URL}/api/projects/{a_id}/evidence",
            json={"paragraph_id": target["paragraph_id"], "note": "重复收藏"},
        )
        checks.check(
            "同一段落重复收藏被拒绝",
            duplicate_evidence.status_code == 409,
            f"HTTP {duplicate_evidence.status_code} detail={duplicate_evidence.json().get('detail')}",
        )

        export = client.get(f"{APP_URL}/api/projects/{a_id}/evidence/export")
        expected_quote = "\n".join("> " + line if line else ">" for line in target["text"].splitlines())
        checks.require(
            "导出 Markdown 证据清单，原文/来源/备注一致",
            export.status_code == 200
            and expected_quote in export.text
            and f"`{EXPECTED_SOURCE}`" in export.text
            and "用于组会引言，需与论文原文核对。" in export.text
            and "01-注意力机制课程笔记.md" in export.text,
            f"HTTP {export.status_code} bytes={len(export.content)} content_type={export.headers.get('content-type')} disposition={export.headers.get('content-disposition')}",
        )
        state["phase1"]["export"] = export.text

        progress_a = {
            "goal": "梳理注意力机制的核心概念，形成可引用的证据清单。",
            "progress": "已完成缩放点积与多头注意力的笔记整理，收藏 1 条证据。",
            "next_steps": "补充显存占用实验，并核对课程小实验的结论边界。",
        }
        saved_a = client.put(f"{APP_URL}/api/projects/{a_id}/progress", json=progress_a)
        body_a = saved_a.json().get("progress", {})
        checks.require(
            "保存项目 A 的研究目标、进度与下一步",
            saved_a.status_code == 200
            and body_a.get("progress") == progress_a["progress"]
            and body_a.get("next_steps") == progress_a["next_steps"]
            and body_a.get("source") == "powercontext"
            and body_a.get("memory_id"),
            f"HTTP {saved_a.status_code} source={body_a.get('source')} memory_id={body_a.get('memory_id')} archived={saved_a.json().get('archived_progress_records')}",
        )

        progress_b = {
            "goal": "比较检索增强与滑动窗口上下文方案。",
            "progress": "已完成三组对照实验记录初稿。",
            "next_steps": "固定随机种子重复三次，并补充无匹配资料对照组。",
        }
        saved_b = client.put(f"{APP_URL}/api/projects/{b_id}/progress", json=progress_b)
        body_b = saved_b.json().get("progress", {})
        checks.require(
            "保存项目 B 的不同进度",
            saved_b.status_code == 200
            and body_b.get("progress") == progress_b["progress"]
            and body_b.get("next_steps") == progress_b["next_steps"],
            f"HTTP {saved_b.status_code} memory_id={body_b.get('memory_id')}",
        )
        state["phase1"]["progress"] = {"A": progress_of(client, a_id), "B": progress_of(client, b_id)}

        cross_search = client.get(f"{APP_URL}/api/projects/{b_id}/search", params={"q": "注意力"}).json()
        cross_evidence = client.get(f"{APP_URL}/api/projects/{b_id}/evidence").json()["evidence"]
        cross_docs = client.get(f"{APP_URL}/api/projects/{b_id}/documents").json()["documents"]
        cross_collect = client.post(
            f"{APP_URL}/api/projects/{b_id}/evidence",
            json={"paragraph_id": target["paragraph_id"], "note": "跨项目尝试"},
        )
        checks.require(
            "项目隔离：B 无法看到 A 的资料/证据，也不能收藏 A 的段落",
            cross_search["count"] == 0
            and len(cross_evidence) == 0
            and len(cross_docs) == 0
            and cross_collect.status_code == 400,
            f"B 检索={cross_search['count']} 证据={len(cross_evidence)} 资料={len(cross_docs)} 跨项目收藏 HTTP={cross_collect.status_code}",
        )

        bad_id = client.get(f"{APP_URL}/api/projects/bad%20id")
        missing = client.get(f"{APP_URL}/api/projects/scope_missing_000")
        bad_evidence = client.delete(f"{APP_URL}/api/projects/{a_id}/evidence/not-an-id")
        checks.check(
            "非法项目标识/不存在项目/非法证据标识被合理处理",
            bad_id.status_code == 400 and missing.status_code == 404 and bad_evidence.status_code == 400,
            f"bad_id={bad_id.status_code} missing={missing.status_code} bad_evidence={bad_evidence.status_code}",
        )

        snapshot = pc_snapshot()
        entries_a = snapshot["entries"].get(a_id, [])
        entries_b = snapshot["entries"].get(b_id, [])
        project_scopes = [item for item in snapshot["scopes"] if item["marker"]]
        project_scope_ids = {item["scope_id"] for item in project_scopes}
        marker_ok = project_scope_ids == {a_id, b_id}
        checks.require(
            "PowerContext 中真实存在项目 Scope 与 Memory 记录",
            marker_ok
            and len(active(entries_a, "research.evidence")) == 1
            and len(active(entries_a, "research.progress")) == 1
            and len(active(entries_b, "research.progress")) == 1
            and len(active(entries_b, "research.evidence")) == 0,
            f"项目 Scope={len(project_scopes)}（总计 {len(snapshot['scopes'])}） A证据={len(active(entries_a, 'research.evidence'))} A进度={len(active(entries_a, 'research.progress'))} B进度={len(active(entries_b, 'research.progress'))}",
        )
        state["phase1"]["powercontext"] = {
            "scopes": snapshot["scopes"],
            "active_counts": {
                a_id: {kind: len(active(entries_a, kind)) for kind in ("research.progress", "research.evidence")},
                b_id: {kind: len(active(entries_b, kind)) for kind in ("research.progress", "research.evidence")},
            },
            "database_files": database_files(),
        }

    state["phase1"]["finished"] = now()


def run_after_restart(checks: Checks, state: dict[str, Any]) -> None:
    a_id = state["phase1"]["projects"]["A"]["id"]
    b_id = state["phase1"]["projects"]["B"]["id"]
    with httpx.Client(timeout=30) as client:
        health = client.get(f"{APP_URL}/api/health")
        checks.require(
            "结束进程并重启后，应用与 PowerContext 再次就绪",
            health.status_code == 200 and health.json().get("ok") is True,
            f"HTTP {health.status_code}",
        )

        docs = client.get(f"{APP_URL}/api/projects/{a_id}/documents").json()["documents"]
        docs_b = client.get(f"{APP_URL}/api/projects/{b_id}/documents").json()["documents"]
        checks.require(
            "重启后资料仍在且项目间不串数据",
            len(docs) == 3 and len(docs_b) == 0,
            f"A 资料={len(docs)} B 资料={len(docs_b)}",
        )

        progress_a = progress_of(client, a_id)
        progress_b = progress_of(client, b_id)
        expected_a = state["phase1"]["progress"]["A"]
        expected_b = state["phase1"]["progress"]["B"]
        checks.require(
            "重启后两份项目的进度分别准确恢复",
            progress_a["goal"] == expected_a["goal"]
            and progress_a["progress"] == expected_a["progress"]
            and progress_a["next_steps"] == expected_a["next_steps"]
            and progress_b["goal"] == expected_b["goal"]
            and progress_b["progress"] == expected_b["progress"]
            and progress_b["next_steps"] == expected_b["next_steps"]
            and progress_a["memory_id"] == expected_a["memory_id"]
            and progress_b["memory_id"] == expected_b["memory_id"],
            f"A.progress={progress_a['progress']!r} B.progress={progress_b['progress']!r}",
        )

        evidence = client.get(f"{APP_URL}/api/projects/{a_id}/evidence").json()["evidence"]
        evidence_b = client.get(f"{APP_URL}/api/projects/{b_id}/evidence").json()["evidence"]
        expected_evidence = state["phase1"]["evidence"]
        checks.require(
            "重启后证据收藏、备注与来源保持一致",
            len(evidence) == 1
            and len(evidence_b) == 0
            and evidence[0]["evidence_id"] == expected_evidence["evidence_id"]
            and evidence[0]["quote"] == expected_evidence["quote"]
            and evidence[0]["note"] == expected_evidence["note"]
            and evidence[0]["relative_source"] == expected_evidence["relative_source"],
            f"A 证据={len(evidence)} B 证据={len(evidence_b)} evidence_id={evidence[0]['evidence_id'] if evidence else '无'}",
        )

        export = client.get(f"{APP_URL}/api/projects/{a_id}/evidence/export")
        expected_quote = "\n".join(
            "> " + line if line else ">" for line in expected_evidence["quote"].splitlines()
        )
        checks.require(
            "重启后导出的原文/来源/备注仍一致",
            export.status_code == 200
            and expected_quote in export.text
            and f"`{EXPECTED_SOURCE}`" in export.text
            and expected_evidence["note"] in export.text,
            f"HTTP {export.status_code} bytes={len(export.content)}",
        )

        snapshot = pc_snapshot()
        entries_a = snapshot["entries"].get(a_id, [])
        entries_b = snapshot["entries"].get(b_id, [])
        checks.require(
            "重启后 PowerContext 记录仍为活跃状态（真实持久化）",
            len(active(entries_a, "research.evidence")) == 1
            and len(active(entries_a, "research.progress")) == 1
            and len(active(entries_b, "research.progress")) == 1,
            f"A证据={len(active(entries_a, 'research.evidence'))} A进度={len(active(entries_a, 'research.progress'))} B进度={len(active(entries_b, 'research.progress'))}",
        )
        state["phase2"] = {
            "progress": {"A": progress_a, "B": progress_b},
            "evidence": evidence,
            "export": export.text,
            "powercontext": {
                "scopes": snapshot["scopes"],
                "database_files": database_files(),
            },
        }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    checks = Checks()
    state: dict[str, Any] = {}
    error: str | None = None
    stack = Stack()
    print(f"[acceptance] run_id={RUN_ID} dir={RUN_DIR}", flush=True)
    try:
        stack.start()
        run_checks(checks, state)
        print("[acceptance] 结束应用与 PowerContext 进程 ...", flush=True)
        stack.stop()
        print("[acceptance] 使用同一数据目录重启 ...", flush=True)
        stack.start()
        run_after_restart(checks, state)
    except Exception as exc:  # noqa: BLE001 - report any failure faithfully
        error = f"{type(exc).__name__}: {exc}"
        checks.check("验收流程无异常", False, error)
    finally:
        stack.stop()
        write_artifacts(checks, state, error)

    total = len(checks.items)
    passed = total - checks.failed
    print(f"[acceptance] {passed}/{total} 项通过；结果写入 evidence/logs/acceptance.md", flush=True)
    return 0 if checks.failed == 0 and error is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
