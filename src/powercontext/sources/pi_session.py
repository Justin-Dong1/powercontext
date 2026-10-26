# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Pi v3 session history parsing and incremental captured-event ingestion."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import quote

from pydantic import BaseModel, JsonValue

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.connectors import ConnectorRunCompletion, ConnectorRunSession, ConnectorRunStatus
from powercontext.sources.definitions import AdapterSourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

PI_EVENT_SOURCE_NAME = "pi-event"
PI_SESSION_CONNECTOR_NAME = "pi-session-history"


class PiSessionInput(BaseModel):
    """One complete Pi v3 JSONL session and an optional selected leaf."""

    content: bytes
    leaf_id: str | None = None


class PiEventInput(BaseModel):
    """One visible event on the selected Pi session branch."""

    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


class PiEventSource(Source):
    """A captured Pi event retaining its complete original JSON record."""

    source_id: str
    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


def pi_event_source_id(session_id: str, event_id: str) -> str:
    """Return a delimiter-safe identity derived only from session and event IDs."""

    if not session_id or not event_id:
        raise ValueError("session_id and event_id must be non-empty")
    source_id = f"pi:{quote(session_id, safe='')}:{quote(event_id, safe='')}"
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"source_id must not exceed {MAX_SOURCE_ID_LENGTH} characters")
    return source_id


def _parse_archive(content: bytes) -> tuple[str, dict[str, dict[str, JsonValue]], tuple[str, ...]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("Pi session must be valid UTF-8") from error

    records: list[object] = []
    try:
        for line in text.splitlines():
            if line.strip():
                records.append(json.loads(line))
    except json.JSONDecodeError as error:
        raise ValueError("Pi session must contain valid JSONL records") from error
    if not records or not isinstance(records[0], dict):
        raise ValueError("Pi session must start with a session header")

    header = records[0]
    session_id = header.get("id")
    if (
        header.get("type") != "session"
        or header.get("version") != 3
        or not isinstance(session_id, str)
        or not session_id
    ):
        raise ValueError("Pi session header must declare type=session, version=3, and a non-empty id")

    by_id: dict[str, dict[str, JsonValue]] = {}
    order: list[str] = []
    for value in records[1:]:
        if not isinstance(value, dict):
            raise ValueError("Pi session event records must be JSON objects")
        event_id = value.get("id")
        parent_id = value.get("parentId")
        if not isinstance(event_id, str) or not event_id:
            raise ValueError("Pi session event ids must be non-empty strings")
        if event_id in by_id:
            raise ValueError("Pi session event ids must be unique")
        if parent_id is not None and (not isinstance(parent_id, str) or parent_id not in by_id):
            raise ValueError("Pi session parents must be null or refer to an earlier event")
        by_id[event_id] = value  # type: ignore[assignment]
        order.append(event_id)
    return session_id, by_id, tuple(order)


def _visible_parts(content: object, *, include_tools: bool = True) -> tuple[str, ...]:
    if isinstance(content, str):
        return (content,) if content else ()
    if not isinstance(content, list):
        return ()
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text" and isinstance(block.get("text"), str):
            parts.append(block["text"])
        elif block_type == "toolCall" and include_tools:
            name = block.get("name")
            call_id = block.get("id")
            if isinstance(name, str) and isinstance(call_id, str):
                arguments = json.dumps(
                    block.get("arguments"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                parts.append(f"[tool_call {name} {call_id}] {arguments}")
    return tuple(parts)


def _visible_event(session_id: str, record: dict[str, JsonValue]) -> PiEventInput | None:
    event_id = record["id"]
    parent_id = record.get("parentId")
    event_type = record.get("type")
    if not isinstance(event_id, str) or not isinstance(parent_id, (str, type(None))) or not isinstance(event_type, str):
        raise ValueError("Pi session events must contain valid id, parentId, and type fields")

    role: str
    body: str
    if event_type == "message":
        message = record.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("role"), str):
            return None
        role = message["role"]
        if role == "toolResult":
            tool_name = message.get("toolName")
            tool_call_id = message.get("toolCallId")
            if not isinstance(tool_name, str) or not isinstance(tool_call_id, str):
                return None
            text = "\n".join(_visible_parts(message.get("content"), include_tools=False))
            body = f"[tool_result {tool_name} {tool_call_id}] {text}"
        elif role == "bashExecution":
            command = message.get("command")
            output = message.get("output")
            if not isinstance(command, str) or not isinstance(output, str):
                return None
            body = f"$ {command}\n{output}"
        else:
            body = "\n".join(_visible_parts(message.get("content")))
    elif event_type in {"compaction", "branch_summary"}:
        summary = record.get("summary")
        if not isinstance(summary, str):
            return None
        role, body = event_type, summary
    elif event_type == "custom_message":
        role = "custom"
        body = "\n".join(_visible_parts(record.get("content"), include_tools=False))
    else:
        return None
    if not body:
        return None
    return PiEventInput(
        session_id=session_id,
        event_id=event_id,
        parent_id=parent_id,
        event_type=event_type,
        role=role,
        content=f"{role}: {body}",
        record=record,
    )


def _events_for_leaf(
    session_id: str,
    by_id: dict[str, dict[str, JsonValue]],
    order: tuple[str, ...],
    leaf_id: str | None,
) -> tuple[PiEventInput, ...]:
    if not order:
        if leaf_id is not None:
            raise ValueError("selected Pi session leaf does not exist")
        return ()
    selected = leaf_id if leaf_id is not None else order[-1]
    if selected not in by_id:
        raise ValueError("selected Pi session leaf does not exist")

    path: list[dict[str, JsonValue]] = []
    seen: set[str] = set()
    current: str | None = selected
    while current is not None:
        if current in seen:
            raise ValueError("Pi session graph contains a cycle")
        seen.add(current)
        record = by_id[current]
        path.append(record)
        parent = record.get("parentId")
        current = parent if isinstance(parent, str) else None
    path.reverse()
    return tuple(event for record in path if (event := _visible_event(session_id, record)) is not None)


def parse_pi_session(value: PiSessionInput) -> tuple[PiEventInput, ...]:
    """Parse all visible events on the selected Pi session branch, root first."""

    session_id, by_id, order = _parse_archive(value.content)
    return _events_for_leaf(session_id, by_id, order, value.leaf_id)


class PiEventSourceAdapter:
    input_class = PiEventInput
    name = PI_EVENT_SOURCE_NAME
    source_class = PiEventSource

    async def resolve(self, value: PiEventInput, /) -> PiEventSource:
        source_id = pi_event_source_id(value.session_id, value.event_id)
        return PiEventSource(
            name=source_id,
            source_id=source_id,
            materialization=SourceMaterialization.CAPTURED,
            **value.model_dump(),
        )

    async def read(self, source: PiEventSource, /) -> PiEventInput:
        return PiEventInput.model_validate(
            source.model_dump(
                include={"session_id", "event_id", "parent_id", "event_type", "role", "content", "record"}
            )
        )


class PiEventTextEvidenceProjection:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PiEventSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PiEventSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PI_EVENT_SOURCE_NAME,
            source_id=source.source_id,
            content=source.content,
            metadata={
                "session_id": source.session_id,
                "event_id": source.event_id,
                "parent_id": source.parent_id,
                "event_type": source.event_type,
                "role": source.role,
            },
        )


PI_EVENT_SOURCE_ADAPTER = PiEventSourceAdapter()
PI_EVENT_SOURCE_DEFINITION = AdapterSourceDefinition(
    PI_EVENT_SOURCE_ADAPTER,
    projections=(PiEventTextEvidenceProjection(),),
)


def _record_digest(record: dict[str, JsonValue]) -> str:
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class PiSessionConnector:
    """Incrementally submit visible events while persisting immutable-event checksums."""

    name = PI_SESSION_CONNECTOR_NAME
    version = "1"
    source_definitions = frozenset({PI_EVENT_SOURCE_NAME})

    def __init__(self, path: str | Path, leaf_id: str | None = None) -> None:
        self.path = Path(path)
        self.leaf_id = leaf_id

    async def run(self, session: ConnectorRunSession, /) -> ConnectorRunCompletion:
        content = self.path.read_bytes()
        session_id, by_id, order = _parse_archive(content)
        events = _events_for_leaf(session_id, by_id, order, self.leaf_id)
        imported = self._checkpoint_events(session.checkpoint, session_id)

        for event_id, digest in imported.items():
            current = by_id.get(event_id)
            if current is None or _record_digest(current) != digest:
                raise ValueError(f"previously imported Pi event {event_id!r} was changed")

        next_imported = dict(imported)
        for event in events:
            digest = _record_digest(event.record)
            if event.event_id in imported:
                continue
            await session.submit(pi_event_source_id(session_id, event.event_id), PI_EVENT_SOURCE_NAME, event)
            next_imported[event.event_id] = digest

        return ConnectorRunCompletion(
            status=ConnectorRunStatus.COMPLETE,
            checkpoint={"session_id": session_id, "events": next_imported},
        )

    @staticmethod
    def _checkpoint_events(checkpoint: JsonValue | None, session_id: str) -> dict[str, str]:
        if checkpoint is None:
            return {}
        if not isinstance(checkpoint, dict) or checkpoint.get("session_id") != session_id:
            raise ValueError("Pi connector checkpoint does not match the current session")
        events = checkpoint.get("events")
        if not isinstance(events, dict) or not all(
            isinstance(event_id, str) and isinstance(digest, str) for event_id, digest in events.items()
        ):
            raise ValueError("Pi connector checkpoint is invalid")
        return dict(events)


__all__ = [
    "PI_EVENT_SOURCE_ADAPTER",
    "PI_EVENT_SOURCE_DEFINITION",
    "PI_EVENT_SOURCE_NAME",
    "PI_SESSION_CONNECTOR_NAME",
    "PiEventInput",
    "PiEventSource",
    "PiEventSourceAdapter",
    "PiEventTextEvidenceProjection",
    "PiSessionConnector",
    "PiSessionInput",
    "parse_pi_session",
    "pi_event_source_id",
]
