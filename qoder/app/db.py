from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from app.documents import DocumentError, ParsedDocument, escape_like

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    relative_source TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    summary TEXT NOT NULL,
    paragraph_count INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (project_id, relative_source, content_sha256)
);
CREATE TABLE IF NOT EXISTS paragraphs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_paragraphs_project ON paragraphs(project_id);
CREATE INDEX IF NOT EXISTS idx_documents_project ON documents(project_id);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as connection:
            await connection.execute("PRAGMA journal_mode=WAL")
            await connection.execute("PRAGMA foreign_keys=ON")
            await connection.executescript(_SCHEMA)
            await connection.commit()

    async def ping(self) -> bool:
        async with aiosqlite.connect(self.path) as connection:
            async with connection.execute("SELECT 1") as cursor:
                return await cursor.fetchone() is not None

    async def list_documents(self, project_id: str) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.path) as connection:
            connection.row_factory = aiosqlite.Row
            async with connection.execute(
                """
                SELECT id, name, relative_source, content_sha256, summary, paragraph_count, created_at
                FROM documents WHERE project_id = ? ORDER BY created_at, name
                """,
                (project_id,),
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    async def add_document(self, project_id: str, parsed: ParsedDocument) -> dict[str, Any]:
        document_id = "doc_" + uuid.uuid4().hex
        created_at = _now()
        try:
            async with aiosqlite.connect(self.path) as connection:
                connection.row_factory = aiosqlite.Row
                await connection.execute("PRAGMA foreign_keys=ON")
                async with connection.execute(
                    "SELECT id FROM documents WHERE project_id = ? AND relative_source = ? AND content_sha256 = ?",
                    (project_id, parsed.relative_source, parsed.content_sha256),
                ) as cursor:
                    if await cursor.fetchone() is not None:
                        raise DocumentError(f"资料来源“{parsed.relative_source}”与内容已导入过。")
                await connection.execute(
                    """
                    INSERT INTO documents
                        (id, project_id, name, relative_source, content_sha256, summary, paragraph_count, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        project_id,
                        parsed.name,
                        parsed.relative_source,
                        parsed.content_sha256,
                        parsed.summary,
                        len(parsed.paragraphs),
                        created_at,
                    ),
                )
                await connection.executemany(
                    "INSERT INTO paragraphs (id, project_id, document_id, ordinal, text) VALUES (?, ?, ?, ?, ?)",
                    [
                        ("par_" + uuid.uuid4().hex, project_id, document_id, index, text)
                        for index, text in enumerate(parsed.paragraphs, start=1)
                    ],
                )
                await connection.commit()
        except aiosqlite.IntegrityError as error:
            raise DocumentError(f"资料来源“{parsed.relative_source}”与内容已导入过。") from error
        return {
            "id": document_id,
            "name": parsed.name,
            "relative_source": parsed.relative_source,
            "summary": parsed.summary,
            "paragraph_count": len(parsed.paragraphs),
            "created_at": created_at,
        }

    async def get_paragraph(self, project_id: str, paragraph_id: str) -> dict[str, Any] | None:
        async with aiosqlite.connect(self.path) as connection:
            connection.row_factory = aiosqlite.Row
            async with connection.execute(
                """
                SELECT p.id, p.ordinal, p.text, p.document_id, d.name AS document_name,
                       d.relative_source
                FROM paragraphs p JOIN documents d ON d.id = p.document_id
                WHERE p.project_id = ? AND p.id = ?
                """,
                (project_id, paragraph_id),
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def search(self, project_id: str, term: str, limit: int = 30) -> list[dict[str, Any]]:
        pattern = f"%{escape_like(term)}%"
        async with aiosqlite.connect(self.path) as connection:
            connection.row_factory = aiosqlite.Row
            async with connection.execute(
                """
                SELECT p.id AS paragraph_id, p.ordinal, p.text, p.document_id,
                       d.name AS document_name, d.relative_source
                FROM paragraphs p JOIN documents d ON d.id = p.document_id
                WHERE p.project_id = ? AND p.text LIKE ? ESCAPE '\\'
                ORDER BY d.created_at, p.ordinal
                LIMIT ?
                """,
                (project_id, pattern, limit),
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    async def stats(self, project_id: str) -> dict[str, int]:
        async with aiosqlite.connect(self.path) as connection:
            async with connection.execute(
                "SELECT COUNT(*) FROM documents WHERE project_id = ?", (project_id,)
            ) as cursor:
                documents = int((await cursor.fetchone())[0])
            async with connection.execute(
                "SELECT COUNT(*) FROM paragraphs WHERE project_id = ?", (project_id,)
            ) as cursor:
                paragraphs = int((await cursor.fetchone())[0])
        return {"documents": documents, "paragraphs": paragraphs}

    async def has_source(self, project_id: str, relative_source: str) -> bool:
        async with aiosqlite.connect(self.path) as connection:
            async with connection.execute(
                "SELECT 1 FROM documents WHERE project_id = ? AND relative_source = ? LIMIT 1",
                (project_id, relative_source),
            ) as cursor:
                return await cursor.fetchone() is not None
