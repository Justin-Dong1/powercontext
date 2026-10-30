from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Path as PathParam, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.config import Settings
from app.db import Database
from app.documents import DocumentError, parse_document
from app.memory import (
    EVIDENCE_KIND,
    MAX_MEMORY_BYTES,
    PROGRESS_KIND,
    MemoryError,
    MemoryGateway,
    MemoryRejected,
    PowerContextUnavailable,
    Project,
    ProjectNotFound,
    Record,
)
from app.models import (
    EvidenceCreate,
    ProgressUpdate,
    ProjectCreate,
    valid_evidence_id,
    valid_scope_id,
)

logger = logging.getLogger("researchtrail")


def _json_response(content: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=content, headers={"Cache-Control": "no-store"})


def _loads(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _project_json(project: Project) -> dict[str, Any]:
    return {"id": project.scope_id, "title": project.title, "goal": project.goal}


def _progress_json(data: dict[str, Any], record: Record | None, source: str) -> dict[str, Any]:
    return {
        "goal": str(data.get("goal", "")),
        "progress": str(data.get("progress", "")),
        "next_steps": str(data.get("next_steps", "")),
        "updated_at": data.get("updated_at"),
        "source": source,
        "memory_id": record.artifact_id if record else None,
    }


def _evidence_json(record: Record) -> dict[str, Any] | None:
    data = _loads(record.text)
    if data is None:
        return None
    required = ("paragraph_id", "document_name", "relative_source", "quote")
    if any(not isinstance(data.get(key), str) for key in required):
        return None
    return {
        "evidence_id": record.artifact_id,
        "paragraph_id": data["paragraph_id"],
        "document_id": str(data.get("document_id", "")),
        "document_name": data["document_name"],
        "relative_source": data["relative_source"],
        "paragraph_ordinal": int(data.get("paragraph_ordinal", 0)),
        "quote": data["quote"],
        "note": str(data.get("note", "")),
        "created_at": str(data.get("created_at", "")),
    }


def _evidence_items(records: list[Record]) -> list[dict[str, Any]]:
    items = [item for record in records if (item := _evidence_json(record)) is not None]
    items.sort(key=lambda item: (item["created_at"], item["evidence_id"]), reverse=True)
    return items


def _latest_progress(records: list[Record]) -> tuple[dict[str, Any], Record] | None:
    candidates: list[tuple[str, dict[str, Any], Record]] = []
    for record in records:
        data = _loads(record.text)
        if data is not None and isinstance(data.get("goal"), str):
            candidates.append((str(data.get("updated_at") or ""), data, record))
    if not candidates:
        return None
    _, data, record = max(candidates, key=lambda item: item[0])
    return data, record


def _markdown_quote(text: str) -> str:
    return "\n".join("> " + line if line else ">" for line in text.splitlines())


def _export_markdown(
    project: Project,
    progress: dict[str, Any],
    evidence: list[dict[str, Any]],
    exported_at: str,
) -> str:
    lines = [
        f"# {project.title} · 证据清单",
        "",
        f"> 研究目标：{progress.get('goal') or project.goal}",
        f"> 导出时间：{exported_at}",
        "> 说明：证据收藏与备注由 PowerContext Memory 持久化。",
        "",
    ]
    if not evidence:
        lines.extend(["当前项目还没有收藏证据。", ""])
        return "\n".join(lines)
    for index, item in enumerate(sorted(evidence, key=lambda value: value["created_at"]), start=1):
        lines.extend(
            [
                f"## {index}. {item['document_name']}",
                "",
                f"- 来源：`{item['relative_source']}` · 第 {item['paragraph_ordinal']} 段",
                "- 原文：",
                _markdown_quote(item["quote"]),
                f"- 我的备注：{item['note'] or '（无）'}",
                "",
            ]
        )
    return "\n".join(lines)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.ensure_dirs()
        database = Database(settings.database_path)
        await database.initialize()
        gateway = MemoryGateway(settings.powercontext_url)
        app.state.settings = settings
        app.state.database = database
        app.state.memory = gateway
        logger.info("ResearchTrail started: data=%s powercontext=%s", settings.data_dir, settings.powercontext_url)
        try:
            yield
        finally:
            await gateway.close()

    app = FastAPI(title="研途 ResearchTrail", version="1.0.0", lifespan=lifespan)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_failure(request: Request, exc: RequestValidationError):
        detail = exc.errors()[0].get("msg", "输入不合法") if exc.errors() else "输入不合法"
        return _json_response({"detail": f"输入校验失败：{detail}"}, status_code=422)

    @app.exception_handler(MemoryError)
    async def memory_failure(request: Request, exc: MemoryError):
        if isinstance(exc, ProjectNotFound):
            status = 404
        elif isinstance(exc, PowerContextUnavailable):
            status = 503
        elif isinstance(exc, MemoryRejected):
            status = 409
        else:
            status = 500
        return _json_response({"detail": str(exc)}, status_code=status)

    def database(request: Request) -> Database:
        return request.app.state.database

    def memory(request: Request) -> MemoryGateway:
        return request.app.state.memory

    def require_scope_id(project_id: str = PathParam(min_length=1, max_length=128)) -> str:
        if not valid_scope_id(project_id):
            raise HTTPException(status_code=400, detail="项目标识格式不合法。")
        return project_id

    def require_evidence_id(evidence_id: str = PathParam(min_length=1, max_length=80)) -> str:
        if not valid_evidence_id(evidence_id):
            raise HTTPException(status_code=400, detail="证据标识格式不合法。")
        return evidence_id

    async def require_project(project_id: str, gateway: MemoryGateway) -> Project:
        return await gateway.get_project(project_id)

    @app.get("/api/health")
    async def health(request: Request):
        db_ok, pc_health = await asyncio.gather(
            request.app.state.database.ping(),
            request.app.state.memory.health(),
        )
        ok = bool(db_ok and pc_health.get("ok"))
        return _json_response(
            {
                "ok": ok,
                "app": {"ok": True, "data_dir": str(settings.data_dir)},
                "database": {"ok": db_ok},
                "powercontext": pc_health,
            }
        )

    @app.get("/api/projects")
    async def list_projects(gateway: MemoryGateway = Depends(memory)):
        projects = await gateway.list_projects()
        return _json_response({"projects": [_project_json(project) for project in projects]})

    @app.post("/api/projects", status_code=201)
    async def create_project(body: ProjectCreate, gateway: MemoryGateway = Depends(memory)):
        project = await gateway.create_project(body.title, body.goal)
        payload = {
            "schema": 1,
            "goal": body.goal,
            "progress": "",
            "next_steps": "",
            "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        try:
            await gateway.remember(project.scope_id, PROGRESS_KIND, payload)
        except MemoryError as error:
            logger.warning("Initial progress write failed for %s: %s", project.scope_id, error)
        return _json_response({"project": _project_json(project)}, status_code=201)

    @app.get("/api/projects/{project_id}")
    async def get_project(
        project_id: str = Depends(require_scope_id),
        gateway: MemoryGateway = Depends(memory),
        db: Database = Depends(database),
    ):
        project = await require_project(project_id, gateway)
        stats = await db.stats(project_id)
        evidence_records = await gateway.list_records(project_id, EVIDENCE_KIND)
        stats["evidence"] = len(_evidence_items(evidence_records))
        return _json_response({"project": _project_json(project), "stats": stats})

    @app.get("/api/projects/{project_id}/documents")
    async def list_documents(
        project_id: str = Depends(require_scope_id),
        gateway: MemoryGateway = Depends(memory),
        db: Database = Depends(database),
    ):
        await require_project(project_id, gateway)
        documents = await db.list_documents(project_id)
        return _json_response({"documents": documents})

    @app.post("/api/projects/{project_id}/documents")
    async def import_documents(
        project_id: str = Depends(require_scope_id),
        files: list[UploadFile] = File(...),
        relative_paths: list[str] | None = Form(default=None),
        gateway: MemoryGateway = Depends(memory),
        db: Database = Depends(database),
    ):
        await require_project(project_id, gateway)
        if not files:
            raise HTTPException(status_code=400, detail="请选择要导入的资料文件。")
        if len(files) > 20:
            raise HTTPException(status_code=400, detail="单次最多导入 20 个文件。")
        stats = await db.stats(project_id)
        paths = relative_paths or []
        imported: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for index, upload in enumerate(files):
            label = upload.filename or f"文件{index + 1}"
            try:
                if stats["documents"] + len(imported) >= settings.max_documents_per_project:
                    raise DocumentError(f"单个项目最多导入 {settings.max_documents_per_project} 份资料。")
                data = await upload.read(settings.max_upload_bytes + 1)
                if len(data) > settings.max_upload_bytes:
                    raise DocumentError("文件超过 2 MB 上限。")
                relative_path = paths[index] if index < len(paths) and paths[index].strip() else None
                parsed = parse_document(data, label, relative_path)
                document = await db.add_document(project_id, parsed)
                imported.append(document)
            except DocumentError as error:
                errors.append({"name": label, "message": str(error)})
            finally:
                await upload.close()
        payload = {"imported": imported, "errors": errors}
        if not imported:
            message = errors[0]["message"] if errors else "没有可导入的资料。"
            payload["detail"] = f"未能导入任何资料：{message}"
            return _json_response(payload, status_code=400)
        return _json_response(payload)

    @app.post("/api/projects/{project_id}/demo")
    async def import_demo(
        project_id: str = Depends(require_scope_id),
        gateway: MemoryGateway = Depends(memory),
        db: Database = Depends(database),
    ):
        await require_project(project_id, gateway)
        files = sorted(
            path for path in settings.sample_dir.glob("*") if path.suffix.lower() in {".md", ".txt"}
        )
        if not files:
            raise HTTPException(status_code=404, detail="未找到演示资料。")
        imported: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        stats = await db.stats(project_id)
        for path in files:
            source = f"演示资料/{path.name}"
            try:
                if stats["documents"] + len(imported) >= settings.max_documents_per_project:
                    raise DocumentError(f"单个项目最多导入 {settings.max_documents_per_project} 份资料。")
                parsed = parse_document(path.read_bytes(), path.name, source)
                imported.append(await db.add_document(project_id, parsed))
            except (DocumentError, OSError) as error:
                errors.append({"name": source, "message": str(error)})
        return _json_response({"imported": imported, "errors": errors})

    @app.get("/api/projects/{project_id}/search")
    async def search_documents(
        project_id: str = Depends(require_scope_id),
        q: str = Query(default=""),
        gateway: MemoryGateway = Depends(memory),
        db: Database = Depends(database),
    ):
        cleaned = q.strip()
        if not cleaned:
            raise HTTPException(status_code=400, detail="请输入检索关键词。")
        if len(cleaned) > 80:
            raise HTTPException(status_code=400, detail="检索关键词过长（最多 80 个字符）。")
        await require_project(project_id, gateway)
        results = await db.search(project_id, cleaned)
        payload: dict[str, Any] = {"query": cleaned, "results": results, "count": len(results)}
        if not results:
            payload["message"] = "未找到匹配段落，请尝试其他关键词。"
        return _json_response(payload)

    @app.get("/api/projects/{project_id}/evidence")
    async def list_evidence(
        project_id: str = Depends(require_scope_id),
        gateway: MemoryGateway = Depends(memory),
    ):
        await require_project(project_id, gateway)
        records = await gateway.list_records(project_id, EVIDENCE_KIND)
        return _json_response({"evidence": _evidence_items(records)})

    @app.post("/api/projects/{project_id}/evidence", status_code=201)
    async def create_evidence(
        body: EvidenceCreate,
        project_id: str = Depends(require_scope_id),
        gateway: MemoryGateway = Depends(memory),
        db: Database = Depends(database),
    ):
        await require_project(project_id, gateway)
        paragraph = await db.get_paragraph(project_id, body.paragraph_id)
        if paragraph is None:
            raise HTTPException(status_code=400, detail="段落不存在，或不属于当前项目。")
        existing = await gateway.list_records(project_id, EVIDENCE_KIND)
        for item in _evidence_items(existing):
            if item["paragraph_id"] == body.paragraph_id:
                raise HTTPException(status_code=409, detail="该段落已经收藏。")
        payload = {
            "schema": 1,
            "paragraph_id": paragraph["id"],
            "document_id": paragraph["document_id"],
            "document_name": paragraph["document_name"],
            "relative_source": paragraph["relative_source"],
            "paragraph_ordinal": paragraph["ordinal"],
            "quote": paragraph["text"],
            "note": body.note,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        record = await gateway.remember(project_id, EVIDENCE_KIND, payload)
        evidence = _evidence_json(record)
        if evidence is None:
            raise HTTPException(status_code=500, detail="证据保存后无法读取。")
        return _json_response({"evidence": evidence}, status_code=201)

    @app.delete("/api/projects/{project_id}/evidence/{evidence_id}")
    async def delete_evidence(
        evidence_id: str = Depends(require_evidence_id),
        project_id: str = Depends(require_scope_id),
        gateway: MemoryGateway = Depends(memory),
    ):
        await require_project(project_id, gateway)
        records = await gateway.list_records(project_id, EVIDENCE_KIND)
        record = next((item for item in records if item.artifact_id == evidence_id), None)
        if record is None:
            raise HTTPException(status_code=404, detail="证据不存在或已取消收藏。")
        await gateway.forget(project_id, record)
        return _json_response({"deleted": True, "evidence_id": evidence_id})

    @app.get("/api/projects/{project_id}/evidence/export")
    async def export_evidence(
        project_id: str = Depends(require_scope_id),
        gateway: MemoryGateway = Depends(memory),
    ):
        project = await require_project(project_id, gateway)
        progress_records = await gateway.list_records(project_id, PROGRESS_KIND)
        latest = _latest_progress(progress_records)
        progress = latest[0] if latest else {"goal": project.goal}
        records = await gateway.list_records(project_id, EVIDENCE_KIND)
        evidence = _evidence_items(records)
        exported_at = datetime.now(UTC).astimezone().isoformat(timespec="seconds")
        markdown = _export_markdown(project, progress, evidence, exported_at)
        filename = f"研途-{project.title}-证据清单.md"
        encoded = urllib.parse.quote(filename, safe="")
        headers = {
            "Content-Disposition": f"attachment; filename=\"researchtrail-evidence.md\"; filename*=UTF-8''{encoded}",
            "Cache-Control": "no-store",
        }
        return Response(content=markdown, media_type="text/markdown; charset=utf-8", headers=headers)

    @app.get("/api/projects/{project_id}/progress")
    async def get_progress(
        project_id: str = Depends(require_scope_id),
        gateway: MemoryGateway = Depends(memory),
    ):
        project = await require_project(project_id, gateway)
        records = await gateway.list_records(project_id, PROGRESS_KIND)
        latest = _latest_progress(records)
        if latest is None:
            data = {"goal": project.goal, "progress": "", "next_steps": "", "updated_at": None}
            return _json_response({"progress": _progress_json(data, None, "scope")})
        data, record = latest
        return _json_response({"progress": _progress_json(data, record, "powercontext")})

    @app.put("/api/projects/{project_id}/progress")
    async def save_progress(
        body: ProgressUpdate,
        project_id: str = Depends(require_scope_id),
        gateway: MemoryGateway = Depends(memory),
    ):
        project = await require_project(project_id, gateway)
        payload = {
            "schema": 1,
            "goal": body.goal,
            "progress": body.progress,
            "next_steps": body.next_steps,
            "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > MAX_MEMORY_BYTES:
            raise HTTPException(
                status_code=422,
                detail=f"进度内容过大（{len(encoded)} 字节），请控制在 {MAX_MEMORY_BYTES} 字节以内。",
            )
        previous = await gateway.list_records(project_id, PROGRESS_KIND)
        record = await gateway.remember(project_id, PROGRESS_KIND, payload)
        archived = 0
        for item in previous:
            if item.artifact_id == record.artifact_id:
                continue
            try:
                await gateway.forget(project_id, item)
                archived += 1
            except MemoryError as error:
                logger.warning("Could not archive old progress %s: %s", item.artifact_id, error)
        try:
            await gateway.update_goal(project_id, body.goal)
        except MemoryError as error:
            logger.warning("Could not update scope summary for %s: %s", project.scope_id, error)
        return _json_response(
            {
                "progress": _progress_json(payload, record, "powercontext"),
                "archived_progress_records": archived,
            }
        )

    app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")
    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(settings.static_dir / "index.html")

    @app.get("/favicon.svg", include_in_schema=False)
    async def favicon():
        return FileResponse(settings.static_dir / "favicon.svg", media_type="image/svg+xml")

    return app


app = create_app()
