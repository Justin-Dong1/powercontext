from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

PARAGRAPH_ID_PATTERN = r"^par_[a-f0-9]{32}$"


def _strip(value: str) -> str:
    return value.strip()


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    goal: str = Field(min_length=1, max_length=2000)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        cleaned = _strip(value)
        if not cleaned:
            raise ValueError("不能只包含空白字符。")
        if any(char in cleaned for char in "\r\n") or any(ord(char) < 32 for char in cleaned):
            raise ValueError("项目名称必须是单行文本。")
        return cleaned

    @field_validator("goal")
    @classmethod
    def clean_goal(cls, value: str) -> str:
        cleaned = _strip(value)
        if not cleaned:
            raise ValueError("不能只包含空白字符。")
        return cleaned


class ProgressUpdate(BaseModel):
    goal: str = Field(min_length=1, max_length=2000)
    progress: str = Field(default="", max_length=4000)
    next_steps: str = Field(default="", max_length=4000)

    @field_validator("goal")
    @classmethod
    def clean_goal(cls, value: str) -> str:
        cleaned = _strip(value)
        if not cleaned:
            raise ValueError("研究目标不能为空。")
        return cleaned

    @field_validator("progress", "next_steps")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return value.replace("\r\n", "\n").strip()


class EvidenceCreate(BaseModel):
    paragraph_id: str = Field(pattern=PARAGRAPH_ID_PATTERN)
    note: str = Field(default="", max_length=500)

    @field_validator("note")
    @classmethod
    def clean_note(cls, value: str) -> str:
        return value.replace("\r\n", "\n").strip()


class SearchQuery(BaseModel):
    q: str

    @field_validator("q")
    @classmethod
    def clean(cls, value: str) -> str:
        cleaned = _strip(value)
        if not cleaned:
            raise ValueError("请输入检索关键词。")
        if len(cleaned) > 80:
            raise ValueError("检索关键词过长（最多 80 个字符）。")
        return cleaned


def valid_scope_id(value: str) -> bool:
    return re.fullmatch(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,127}$", value) is not None


def valid_paragraph_id(value: str) -> bool:
    return re.fullmatch(PARAGRAPH_ID_PATTERN, value) is not None


def valid_evidence_id(value: str) -> bool:
    return re.fullmatch(r"^art_[a-f0-9]{16,64}$", value) is not None
