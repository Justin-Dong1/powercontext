from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from importlib.metadata import version as package_version
from typing import Any

from powercontext.client import PowerContextClient, ServerResponseError, TransportError
from powercontext.http import (
    AtomicMemoryInput,
    AtomicMemoryLifecycleRequest,
    AtomicMemoryRecord,
    AtomicMemoryState,
    CreateScopeRequest,
    ListMemoryEntriesRequest,
    RememberMemoryRequest,
    ScopeDescriptor,
    ScopeExternalReference,
    UpdateScopeRequest,
)

logger = logging.getLogger("researchtrail.memory")

PROJECT_MARKER_KIND = "researchtrail.project"
PROJECT_MARKER_VALUE = "v1"
PROGRESS_KIND = "research.progress"
EVIDENCE_KIND = "research.evidence"
MAX_MEMORY_BYTES = 8000


class MemoryError(RuntimeError):
    """Base failure when PowerContext cannot satisfy a request."""


class PowerContextUnavailable(MemoryError):
    """The PowerContext Server is not reachable."""


class ProjectNotFound(MemoryError):
    """The requested scope is not a ResearchTrail project."""


class MemoryRejected(MemoryError):
    """PowerContext rejected a write or lifecycle change."""


@dataclass(frozen=True)
class Project:
    scope_id: str
    title: str
    goal: str
    version: int


@dataclass(frozen=True)
class Record:
    artifact_id: str
    revision: int
    kind: str
    text: str
    state: str
    state_version: int


def _record(record: AtomicMemoryRecord) -> Record:
    return Record(
        artifact_id=record.artifact.artifact_id,
        revision=record.artifact.revision,
        kind=record.kind,
        text=record.text,
        state=str(record.state),
        state_version=record.state_version,
    )


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class MemoryGateway:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.client = PowerContextClient(base_url)
        self.package_version = package_version("powercontext")

    async def close(self) -> None:
        await self.client.aclose()

    async def health(self) -> dict[str, Any]:
        try:
            await self.client.get_liveness()
            return {"ok": True, "url": self.base_url, "version": self.package_version}
        except (TransportError, ServerResponseError) as error:
            logger.warning("PowerContext health check failed: %s", error)
            return {"ok": False, "url": self.base_url, "version": self.package_version, "error": str(error)}

    async def list_projects(self) -> list[Project]:
        projects: list[Project] = []
        cursor: str | None = None
        while True:
            try:
                page = await self.client.list_scopes(limit=100, cursor=cursor)
            except (TransportError, ServerResponseError) as error:
                raise self._translate(error, scope_lookup=False) from error
            for scope in page.items:
                if _is_project_scope(scope):
                    projects.append(_project(scope))
            cursor = page.next_cursor
            if not cursor:
                break
        projects.sort(key=lambda item: item.title)
        return projects

    async def get_project(self, scope_id: str) -> Project:
        try:
            scope = await self.client.get_scope(scope_id)
        except (TransportError, ServerResponseError) as error:
            raise self._translate(error, scope_lookup=True) from error
        if not _is_project_scope(scope):
            raise ProjectNotFound(scope_id)
        return _project(scope)

    async def create_project(self, title: str, goal: str) -> Project:
        request = CreateScopeRequest(
            title=title,
            summary=goal,
            external_references=[ScopeExternalReference(kind=PROJECT_MARKER_KIND, value=PROJECT_MARKER_VALUE)],
            idempotency_key=f"researchtrail:{uuid.uuid4().hex}",
        )
        try:
            scope = await self.client.create_scope(request)
        except (TransportError, ServerResponseError) as error:
            raise self._translate(error, scope_lookup=False) from error
        return _project(scope)

    async def update_goal(self, scope_id: str, goal: str) -> None:
        scope = await self._raw_scope(scope_id)
        request = UpdateScopeRequest(
            expected_version=scope.version,
            title=scope.title,
            summary=goal,
            parent_scope_id=scope.parent_scope_id,
            context_references=scope.context_references,
            external_references=scope.external_references,
        )
        try:
            await self.client.update_scope(scope_id, request)
        except ServerResponseError as error:
            if error.status_code != 409:
                raise self._translate(error, scope_lookup=False) from error
            scope = await self._raw_scope(scope_id)
            retry = request.model_copy(update={"expected_version": scope.version})
            try:
                await self.client.update_scope(scope_id, retry)
            except (TransportError, ServerResponseError) as retry_error:
                raise self._translate(retry_error, scope_lookup=False) from retry_error
        except TransportError as error:
            raise self._translate(error, scope_lookup=False) from error

    async def list_records(self, scope_id: str, kind: str | None = None) -> list[Record]:
        records: list[Record] = []
        cursor: str | None = None
        while True:
            request = ListMemoryEntriesRequest(scope_id=scope_id, limit=100, cursor=cursor)
            try:
                page = await self.client.list_memory_entries(request)
            except (TransportError, ServerResponseError) as error:
                raise self._translate(error, scope_lookup=True) from error
            records.extend(_record(item) for item in page.entries)
            cursor = page.next_cursor
            if not cursor:
                break
        if kind is not None:
            records = [item for item in records if item.kind == kind]
        return [item for item in records if item.state == "active"]

    async def remember(self, scope_id: str, kind: str, payload: dict[str, Any]) -> Record:
        encoded = _json_bytes(payload)
        if len(encoded) > MAX_MEMORY_BYTES:
            raise MemoryRejected("记录内容过大，无法写入 PowerContext Memory（上限 8000 字节）。")
        request = RememberMemoryRequest(scope_id=scope_id, kind=kind, text=encoded.decode("utf-8"))
        try:
            response = await self.client.remember_memory(request)
        except (TransportError, ServerResponseError) as error:
            raise self._translate(error, scope_lookup=True) from error
        if not response.records:
            raise MemoryRejected("PowerContext Memory 未返回写入记录。")
        return _record(response.records[0])

    async def forget(self, scope_id: str, record: Record) -> None:
        request = AtomicMemoryLifecycleRequest(
            scope_id=scope_id,
            target=AtomicMemoryInput(
                artifact={
                    "family": "atomic-memory",
                    "artifact_id": record.artifact_id,
                    "revision": record.revision,
                },
                state_version=record.state_version,
            ),
            state=AtomicMemoryState.FORGOTTEN,
        )
        try:
            await self.client.change_atomic_memory_lifecycle(request)
        except (TransportError, ServerResponseError) as error:
            raise self._translate(error, scope_lookup=True) from error

    async def _raw_scope(self, scope_id: str) -> ScopeDescriptor:
        try:
            return await self.client.get_scope(scope_id)
        except (TransportError, ServerResponseError) as error:
            raise self._translate(error, scope_lookup=True) from error

    @staticmethod
    def _translate(error: Exception, *, scope_lookup: bool) -> MemoryError:
        if isinstance(error, TransportError):
            return PowerContextUnavailable("无法连接 PowerContext Server，请确认服务已启动。")
        if isinstance(error, ServerResponseError):
            if error.status_code == 404 and scope_lookup:
                return ProjectNotFound("项目不存在或已被移除。")
            if error.status_code == 409:
                return MemoryRejected("PowerContext 记录发生并发变更，请重试。")
            if error.status_code in {400, 422}:
                return MemoryRejected(error.server_message or "PowerContext 拒绝了本次请求。")
            if error.status_code >= 500:
                return PowerContextUnavailable("PowerContext Server 暂时不可用。")
        return MemoryRejected(str(error))


def _is_project_scope(scope: ScopeDescriptor) -> bool:
    return any(
        reference.kind == PROJECT_MARKER_KIND and reference.value == PROJECT_MARKER_VALUE
        for reference in scope.external_references
    )


def _project(scope: ScopeDescriptor) -> Project:
    return Project(scope_id=scope.scope_id, title=scope.title, goal=scope.summary, version=scope.version)
