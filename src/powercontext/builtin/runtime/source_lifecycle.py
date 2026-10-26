# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0.

"""Persistent Source dependency lifecycle propagation."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.builtin.artifacts.memory import MemoryService
from powercontext.builtin.persistence.artifacts import ArtifactRepository
from powercontext.builtin.persistence.database import AsyncDatabase
from powercontext.builtin.persistence.errors import RepositoryNotFoundError
from powercontext.builtin.persistence.sources import SourceRepository
from powercontext.builtin.persistence.tables import SOURCE_LIFECYCLE_NODES_TABLE
from powercontext.builtin.persistence.topic_memory import TopicMemoryRepository
from powercontext.sources import SourceRef


class SourceLifecycleError(ValueError):
    """Reject an invalid lifecycle graph, event, or generation lookup."""


class SourceLifecycleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    revision: int = Field(gt=0, strict=True)
    sequence: int = Field(gt=0, strict=True)
    available: bool = Field(strict=True)
    reason: str

    @field_validator("node_id", "reason")
    @classmethod
    def require_nonblank(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must be a non-empty string")  # noqa: TRY003
        return value


class SourceLifecycleApplication:
    def __init__(self, factory: Callable[[str], ScopedSourceLifecycleService]) -> None:
        self._factory = factory

    def for_scope(self, scope_id: str, /) -> ScopedSourceLifecycleService:
        return self._factory(scope_id)


class ScopedSourceLifecycleService:
    def __init__(
        self,
        *,
        database: AsyncDatabase,
        scope_id: str,
        sources: SourceRepository,
        artifacts: ArtifactRepository,
        topics: TopicMemoryRepository,
        memory: Callable[[], MemoryService],
    ) -> None:
        self._database = database
        self._scope_id = scope_id
        self._sources = sources
        self._artifacts = artifacts
        self._topics = topics
        self._memory = memory

    async def register_source(self, node_id: str, reference: SourceRef, /, *, revision: int) -> None:
        _validate_node_id(node_id)
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise SourceLifecycleError("revision")
        async with self._database.transaction() as connection:
            try:
                await self._sources.get(connection, self._scope_id, reference)
            except RepositoryNotFoundError as error:
                raise SourceLifecycleError("source-reference") from error
            await self._register(
                connection,
                node_id,
                kind="source",
                reference=reference.model_dump(mode="json"),
                parents=(),
                policy="all",
                available=True,
                revision=revision,
            )

    async def register_memory(
        self,
        node_id: str,
        reference: MemoryCitation,
        /,
        *,
        parents: Sequence[str],
        policy: Literal["all", "any"],
    ) -> None:
        await self._register_derived(node_id, reference, parents, policy, kind="memory")

    async def register_topic(
        self,
        node_id: str,
        reference: ArtifactRef,
        /,
        *,
        parents: Sequence[str],
        policy: Literal["all", "any"],
    ) -> None:
        await self._register_derived(node_id, reference, parents, policy, kind="topic")

    async def apply(self, event: SourceLifecycleEvent, /) -> list[str]:
        async with self._database.transaction() as connection:
            rows = await self._rows(connection)
            row = rows.get(event.node_id)
            if row is None or row["kind"] != "source":
                raise SourceLifecycleError("source-node")
            if int(row["source_revision"]) != event.revision:
                raise SourceLifecycleError("revision")
            previous = int(row["last_sequence"])
            if event.sequence < previous:
                raise SourceLifecycleError("sequence")
            if event.sequence == previous:
                if bool(row["last_available"]) != event.available or str(row["last_reason"]) != event.reason:
                    raise SourceLifecycleError("event-conflict")
            else:
                await connection.execute(
                    update(SOURCE_LIFECYCLE_NODES_TABLE)
                    .where(
                        SOURCE_LIFECYCLE_NODES_TABLE.c.scope_id == self._scope_id,
                        SOURCE_LIFECYCLE_NODES_TABLE.c.node_id == event.node_id,
                    )
                    .values(
                        available=event.available,
                        last_sequence=event.sequence,
                        last_available=event.available,
                        last_reason=event.reason,
                    )
                )

        async with self._database.connection() as connection:
            rows = await self._rows(connection)
        desired = _availability(rows)
        for node_id in sorted(desired):
            row = rows[node_id]
            if row["kind"] == "memory":
                await self._set_memory(_memory_reference(row), desired[node_id], event.reason)
            elif row["kind"] == "topic":
                await self._set_topic(_artifact_reference(row), desired[node_id])
        async with self._database.transaction() as connection:
            for node_id, available in desired.items():
                await connection.execute(
                    update(SOURCE_LIFECYCLE_NODES_TABLE)
                    .where(
                        SOURCE_LIFECYCLE_NODES_TABLE.c.scope_id == self._scope_id,
                        SOURCE_LIFECYCLE_NODES_TABLE.c.node_id == node_id,
                    )
                    .values(available=available)
                )
        return sorted(node_id for node_id, available in desired.items() if available)

    async def resolve(
        self, node_id: str, /, *, purpose: Literal["generation", "audit"]
    ) -> SourceRef | MemoryCitation | ArtifactRef:
        if purpose not in {"generation", "audit"}:
            raise SourceLifecycleError("purpose")
        async with self._database.connection() as connection:
            row = (
                (
                    await connection.execute(
                        select(SOURCE_LIFECYCLE_NODES_TABLE).where(
                            SOURCE_LIFECYCLE_NODES_TABLE.c.scope_id == self._scope_id,
                            SOURCE_LIFECYCLE_NODES_TABLE.c.node_id == node_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
        if row is None or (purpose == "generation" and not bool(row["available"])):
            raise SourceLifecycleError("node-unavailable")
        if row["kind"] == "source":
            return SourceRef.model_validate(_payload(row["reference_payload"]))
        if row["kind"] == "memory":
            return _memory_reference(row)
        return _artifact_reference(row)

    async def _register_derived(self, node_id, reference, parents, policy, *, kind: str) -> None:
        _validate_node_id(node_id)
        parent_ids = tuple(parents)
        if policy not in {"all", "any"} or not parent_ids or len(set(parent_ids)) != len(parent_ids):
            raise SourceLifecycleError("parents")
        if node_id in parent_ids:
            raise SourceLifecycleError("cycle")
        if kind == "memory":
            try:
                await self._memory().validate_citation(reference)
            except Exception as error:
                raise SourceLifecycleError("memory-reference") from error
        else:
            async with self._database.connection() as connection:
                try:
                    await self._artifacts.get(connection, self._scope_id, reference)
                except RepositoryNotFoundError as error:
                    raise SourceLifecycleError("topic-reference") from error
        async with self._database.transaction() as connection:
            rows = await self._rows(connection)
            if any(parent not in rows for parent in parent_ids):
                raise SourceLifecycleError("parent")
            available = all(bool(rows[parent]["available"]) for parent in parent_ids)
            if policy == "any":
                available = any(bool(rows[parent]["available"]) for parent in parent_ids)
            await self._register(
                connection,
                node_id,
                kind=kind,
                reference=reference.model_dump(mode="json"),
                parents=parent_ids,
                policy=policy,
                available=available,
                revision=None,
            )
        if kind == "memory":
            await self._set_memory(reference, available, "source lifecycle registration")
        else:
            await self._set_topic(reference, available)

    async def _register(self, connection, node_id, *, kind, reference, parents, policy, available, revision):
        payload = {
            "scope_id": self._scope_id,
            "node_id": node_id,
            "kind": kind,
            "reference_payload": _dump(reference),
            "reference_id": reference.get("artifact_id"),
            "reference_revision": reference.get("revision"),
            "parents_payload": _dump(list(parents)),
            "policy": policy,
            "available": available,
            "source_revision": revision,
            "last_sequence": 0,
        }
        existing = (
            (
                await connection.execute(
                    select(SOURCE_LIFECYCLE_NODES_TABLE).where(
                        SOURCE_LIFECYCLE_NODES_TABLE.c.scope_id == self._scope_id,
                        SOURCE_LIFECYCLE_NODES_TABLE.c.node_id == node_id,
                    )
                )
            )
            .mappings()
            .first()
        )
        if existing is not None:
            comparable = (kind, reference, list(parents), policy, revision)
            stored = (
                existing["kind"],
                _payload(existing["reference_payload"]),
                _payload(existing["parents_payload"]),
                existing["policy"],
                existing["source_revision"],
            )
            if stored != comparable:
                raise SourceLifecycleError("node-conflict")
            return
        await connection.execute(insert(SOURCE_LIFECYCLE_NODES_TABLE).values(**payload))

    async def _rows(self, connection: AsyncConnection):
        result = await connection.execute(
            select(SOURCE_LIFECYCLE_NODES_TABLE).where(SOURCE_LIFECYCLE_NODES_TABLE.c.scope_id == self._scope_id)
        )
        return {str(row["node_id"]): row for row in result.mappings()}

    async def _set_memory(self, citation: MemoryCitation, active: bool, reason: str) -> None:
        service = self._memory()
        await service.validate_citation(citation)
        current = await service.head(citation.memory_ref.artifact_id)
        entries = await service.entries(current)
        entry = next((item for item in entries if item.entry_id == citation.entry_id), None)
        manifest = next((item for item in current.content.manifest.entries if item.entry_id == citation.entry_id), None)
        if entry is None or manifest is None:
            raise SourceLifecycleError("memory-reference")
        if (manifest.state == "active") == active:
            return
        if active:
            await service.reactivate(current, entries=(entry,), reason=reason)
        else:
            await service.forget(current, entries=(entry,), reason=reason)

    async def _set_topic(self, reference: ArtifactRef, active: bool) -> None:
        async with self._database.transaction() as connection:
            await self._topics.set_lifecycle_active(connection, self._scope_id, reference, active=active)


def _availability(rows) -> dict[str, bool]:
    active = {node_id: bool(row["available"]) for node_id, row in rows.items() if row["kind"] == "source"}
    remaining = {node_id for node_id in rows if node_id not in active}
    while remaining:
        progressed = False
        for node_id in tuple(remaining):
            row = rows[node_id]
            parents = tuple(_payload(row["parents_payload"]))
            if not all(parent in active for parent in parents):
                continue
            support = [active[parent] for parent in parents]
            active[node_id] = all(support) if row["policy"] == "all" else any(support)
            remaining.remove(node_id)
            progressed = True
        if not progressed:
            raise SourceLifecycleError("cycle")
    return active


def _memory_reference(row) -> MemoryCitation:
    return MemoryCitation.model_validate(_payload(row["reference_payload"]))


def _artifact_reference(row) -> ArtifactRef:
    return ArtifactRef.model_validate(_payload(row["reference_payload"]))


def _dump(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _payload(value) -> object:
    return json.loads(bytes(value).decode())


def _validate_node_id(value: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise SourceLifecycleError("node-id")
