from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

MAX_PARAGRAPH_CHARS = 1200
MAX_PARAGRAPHS = 3000
ALLOWED_SUFFIXES = {".md", ".txt"}
_SENTENCE_END = "。！？!?；;"


class DocumentError(ValueError):
    """Raised when an imported document cannot be accepted."""


@dataclass(frozen=True)
class ParsedDocument:
    name: str
    relative_source: str
    content_sha256: str
    summary: str
    paragraphs: tuple[str, ...]


def decode_utf8(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise DocumentError("文件不是有效的 UTF-8 文本，请转换编码后重试。") from error


def normalize_relative_source(raw: str) -> str:
    value = (raw or "").strip().replace("\\", "/")
    if not value:
        raise DocumentError("资料来源路径不能为空。")
    while value.startswith("./"):
        value = value[2:]
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise DocumentError("资料来源必须是相对路径，不能使用绝对路径。")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise DocumentError("资料来源路径不能包含空段、'.' 或 '..'。")
    if len(value) > 300:
        raise DocumentError("资料来源路径过长（最多 300 个字符）。")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise DocumentError("资料来源路径包含控制字符。")
    suffix = PurePosixPath(value).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise DocumentError("仅支持导入 UTF-8 编码的 .md 或 .txt 文件。")
    name = parts[-1]
    if len(name) > 200:
        raise DocumentError("文件名过长（最多 200 个字符）。")
    return value


def split_paragraphs(text: str) -> tuple[str, ...]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise DocumentError("资料没有可导入的正文。")
    blocks = re.split(r"\n[ \t]*\n", normalized)
    paragraphs: list[str] = []
    for block in blocks:
        cleaned = block.strip()
        if not cleaned:
            continue
        paragraphs.extend(_split_long_block(cleaned))
        if len(paragraphs) > MAX_PARAGRAPHS:
            raise DocumentError(f"资料段落过多（最多 {MAX_PARAGRAPHS} 段）。")
    if not paragraphs:
        raise DocumentError("资料没有可导入的正文。")
    return tuple(paragraphs)


def _split_long_block(block: str) -> list[str]:
    if len(block) <= MAX_PARAGRAPH_CHARS:
        return [block]
    chunks: list[str] = []
    rest = block
    while len(rest) > MAX_PARAGRAPH_CHARS:
        window = rest[:MAX_PARAGRAPH_CHARS]
        cut = max((window.rfind(char) for char in _SENTENCE_END), default=-1)
        cut = cut + 1 if cut >= 300 else MAX_PARAGRAPH_CHARS
        chunks.append(rest[:cut].strip())
        rest = rest[cut:].lstrip()
    if rest:
        chunks.append(rest)
    return [chunk for chunk in chunks if chunk]


def summarize(paragraphs: tuple[str, ...]) -> str:
    joined = re.sub(r"\s+", " ", " ".join(paragraphs)).strip()
    if len(joined) <= 160:
        return joined
    return joined[:160].rstrip() + "…"


def parse_document(data: bytes, filename: str, relative_path: str | None) -> ParsedDocument:
    if not data:
        raise DocumentError("文件内容为空。")
    source = normalize_relative_source(relative_path or filename or "")
    text = decode_utf8(data)
    paragraphs = split_paragraphs(text)
    name = PurePosixPath(source).name
    return ParsedDocument(
        name=name,
        relative_source=source,
        content_sha256=hashlib.sha256(data).hexdigest(),
        summary=summarize(paragraphs),
        paragraphs=paragraphs,
    )


def escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
