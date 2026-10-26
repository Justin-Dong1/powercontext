# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Serializable full and incremental representations of prepared context."""

# The protocol deliberately reports a small, stable set of boundary failures.
# ruff: noqa: TRY003

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from typing import Any, ClassVar, cast


class ContextPackError(ValueError):
    """A context pack or delta violates the wire protocol."""


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _decode_object(payload: bytes | bytearray | memoryview, *, fields: frozenset[str]) -> dict[str, Any]:
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise ContextPackError("wire payload must be bytes")
    try:
        value = json.loads(bytes(payload).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContextPackError("invalid JSON payload") from error
    if not isinstance(value, dict) or frozenset(value) != fields:
        raise ContextPackError("invalid wire fields")
    return value


def _encode_items(items: tuple[bytes, ...]) -> list[str]:
    return [base64.b64encode(item).decode("ascii") for item in items]


def _decode_items(value: object) -> tuple[bytes, ...]:
    if not isinstance(value, list):
        raise ContextPackError("encoded items must be a list")
    decoded: list[bytes] = []
    for item in value:
        if not isinstance(item, str):
            raise ContextPackError("encoded item must be a string")
        try:
            raw = base64.b64decode(item, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ContextPackError("invalid base64 item") from error
        if base64.b64encode(raw).decode("ascii") != item:
            raise ContextPackError("non-canonical base64 item")
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ContextPackError("context item must contain valid UTF-8") from error
        decoded.append(raw)
    return tuple(decoded)


def _validate_items(items: object) -> tuple[bytes, ...]:
    if not isinstance(items, tuple):
        raise ContextPackError("items must be a bytes tuple")
    for item in items:
        if not isinstance(item, bytes):
            raise ContextPackError("items must be a bytes tuple")
        try:
            item.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ContextPackError("context item must contain valid UTF-8") from error
    return cast("tuple[bytes, ...]", items)


def _validate_digest(value: object) -> str:
    if not isinstance(value, str) or len(value) != 71 or not value.startswith("sha256:"):
        raise ContextPackError("invalid SHA-256 digest")
    try:
        int(value[7:], 16)
    except ValueError as error:
        raise ContextPackError("invalid SHA-256 digest") from error
    if value[7:] != value[7:].lower():
        raise ContextPackError("invalid SHA-256 digest")
    return value


@dataclass(frozen=True, slots=True)
class ContextPack:
    """A complete prepared context split into independently valid UTF-8 chunks."""

    SCHEMA: ClassVar[str] = "powercontext.context-pack.v1"
    _FIELDS: ClassVar[frozenset[str]] = frozenset({"schema", "items", "digest", "byte_count"})

    items: tuple[bytes, ...]
    digest: str
    byte_count: int

    @classmethod
    def build(cls, items: tuple[bytes, ...]) -> ContextPack:
        checked = _validate_items(items)
        unsigned = {"schema": cls.SCHEMA, "items": _encode_items(checked)}
        digest = "sha256:" + hashlib.sha256(_canonical_json(unsigned)).hexdigest()

        # byte_count is part of the document whose size it describes. Its decimal
        # width can change the size, so compute the small fixed point explicitly.
        byte_count = 0
        for _ in range(8):
            payload = {**unsigned, "digest": digest, "byte_count": byte_count}
            measured = len(_canonical_json(payload))
            if measured == byte_count:
                return cls(checked, digest, byte_count)
            byte_count = measured
        raise ContextPackError("could not determine pack byte count")

    @classmethod
    def from_content(cls, content: str, *, chunk_bytes: int = 512) -> ContextPack:
        if not isinstance(content, str):
            raise ContextPackError("content must be text")
        if type(chunk_bytes) is not int or chunk_bytes <= 0:
            raise ContextPackError("chunk_bytes must be a positive integer")
        if not content:
            return cls.build(())

        chunks: list[bytes] = []
        characters: list[str] = []
        size = 0
        for character in content:
            encoded = character.encode("utf-8")
            if len(encoded) > chunk_bytes:
                raise ContextPackError("chunk limit cannot contain one UTF-8 character")
            if characters and size + len(encoded) > chunk_bytes:
                chunks.append("".join(characters).encode("utf-8"))
                characters = []
                size = 0
            characters.append(character)
            size += len(encoded)
        if characters:
            chunks.append("".join(characters).encode("utf-8"))
        return cls.build(tuple(chunks))

    def to_bytes(self) -> bytes:
        payload = {
            "schema": self.SCHEMA,
            "items": _encode_items(_validate_items(self.items)),
            "digest": _validate_digest(self.digest),
            "byte_count": self.byte_count,
        }
        encoded = _canonical_json(payload)
        if type(self.byte_count) is not int or self.byte_count < 0 or len(encoded) != self.byte_count:
            raise ContextPackError("invalid pack byte count")
        expected = self.build(self.items)
        if self.digest != expected.digest:
            raise ContextPackError("invalid pack digest")
        return encoded

    @classmethod
    def from_bytes(cls, payload: bytes | bytearray | memoryview) -> ContextPack:
        value = _decode_object(payload, fields=cls._FIELDS)
        if value.get("schema") != cls.SCHEMA:
            raise ContextPackError("unsupported pack schema")
        items = _decode_items(value.get("items"))
        digest = _validate_digest(value.get("digest"))
        byte_count = value.get("byte_count")
        if type(byte_count) is not int or byte_count < 0 or byte_count != len(bytes(payload)):
            raise ContextPackError("invalid pack byte count")
        expected = cls.build(items)
        if digest != expected.digest or byte_count != expected.byte_count:
            raise ContextPackError("pack integrity check failed")
        return expected


@dataclass(frozen=True, slots=True)
class ContextPackDelta:
    """A target context represented as a retained prefix and replacement suffix."""

    SCHEMA: ClassVar[str] = "powercontext.context-pack-delta.v1"
    _FIELDS: ClassVar[frozenset[str]] = frozenset({
        "schema",
        "base_digest",
        "target_digest",
        "prefix_items",
        "appended",
    })

    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    @classmethod
    def between(cls, base: ContextPack, target: ContextPack) -> ContextPackDelta:
        if not isinstance(base, ContextPack) or not isinstance(target, ContextPack):
            raise ContextPackError("base and target must be context packs")
        # Validate callers cannot smuggle manually constructed, inconsistent packs.
        base.to_bytes()
        target.to_bytes()
        prefix = 0
        for old, new in zip(base.items, target.items, strict=False):
            if old != new:
                break
            prefix += 1
        return cls(base.digest, target.digest, prefix, target.items[prefix:])

    @property
    def byte_count(self) -> int:
        return len(self.to_bytes())

    def to_bytes(self) -> bytes:
        if type(self.prefix_items) is not int or self.prefix_items < 0:
            raise ContextPackError("prefix_items must be a non-negative integer")
        payload = {
            "schema": self.SCHEMA,
            "base_digest": _validate_digest(self.base_digest),
            "target_digest": _validate_digest(self.target_digest),
            "prefix_items": self.prefix_items,
            "appended": _encode_items(_validate_items(self.appended)),
        }
        return _canonical_json(payload)

    @classmethod
    def from_bytes(cls, payload: bytes | bytearray | memoryview) -> ContextPackDelta:
        value = _decode_object(payload, fields=cls._FIELDS)
        if value.get("schema") != cls.SCHEMA:
            raise ContextPackError("unsupported delta schema")
        prefix = value.get("prefix_items")
        if type(prefix) is not int or prefix < 0:
            raise ContextPackError("prefix_items must be a non-negative integer")
        return cls(
            base_digest=_validate_digest(value.get("base_digest")),
            target_digest=_validate_digest(value.get("target_digest")),
            prefix_items=prefix,
            appended=_decode_items(value.get("appended")),
        )


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta) -> ContextPack:
    """Apply *delta* to *base*, validating both identities and the rebuilt target."""

    if not isinstance(base, ContextPack) or not isinstance(delta, ContextPackDelta):
        raise ContextPackError("base and delta have incompatible types")
    base.to_bytes()
    # Exercise wire validation for directly constructed delta values as well.
    delta.to_bytes()
    if base.digest != delta.base_digest:
        raise ContextPackError("delta base digest does not match")
    if delta.prefix_items > len(base.items):
        raise ContextPackError("delta prefix exceeds the base pack")
    target = ContextPack.build((*base.items[: delta.prefix_items], *delta.appended))
    if target.digest != delta.target_digest:
        raise ContextPackError("delta target digest does not match")
    return target
