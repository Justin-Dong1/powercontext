#!/usr/bin/env python3
"""Initialize and verify the PowerContext state used by the Echo Maze Dify workflow."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request_json(base_url: str, token: str | None, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            body = json.load(response)
            if not isinstance(body, dict):
                raise RuntimeError(f"PowerContext {path} returned a non-object response")
            return body
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"PowerContext {path} failed with HTTP {error.code}: {detail}") from error
    except URLError as error:
        raise RuntimeError(f"PowerContext {path} is unreachable: {error.reason}") from error


def ensure_scope(base_url: str, token: str | None, player: str) -> str:
    result = request_json(
        base_url,
        token,
        "/v1/scopes",
        {
            "title": f"Echo Maze - {player}",
            "summary": "Dify Echo Maze cross-run player choices",
            "idempotency_key": f"echo-maze-{player}",
        },
    )
    scope_id = result.get("scope_id")
    if not isinstance(scope_id, str) or not scope_id:
        raise RuntimeError("PowerContext create scope response did not contain scope_id")
    return scope_id


def remember(base_url: str, token: str | None, scope_id: str, player: str, choice: str) -> dict[str, Any]:
    return request_json(
        base_url,
        token,
        "/v1/memory/remember",
        {
            "scope_id": scope_id,
            "kind": "echo-maze-turn",
            "text": (
                f"玩家 {player} 在回声迷宫选择了{choice}，进入验证房间，"
                "这是可供后续回合召回的已确认游戏状态。"
            ),
            "reason": "Echo Maze reproducible verification",
        },
    )


def search(base_url: str, token: str | None, scope_id: str, player: str) -> dict[str, Any]:
    return request_json(
        base_url,
        token,
        "/v1/memory/search",
        {"scope_id": scope_id, "query": f"玩家 {player} 在回声迷宫的选择"},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("POWERCONTEXT_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--token", default=os.getenv("POWERCONTEXT_TOKEN"))
    parser.add_argument("--scope-id", default=os.getenv("POWERCONTEXT_SCOPE"))
    parser.add_argument("--player", default="阿澈")
    parser.add_argument("--choice", default="红门", choices=("红门", "蓝门", "无门之门"))
    parser.add_argument("--search-only", action="store_true")
    args = parser.parse_args()

    scope_id = args.scope_id or ensure_scope(args.base_url, args.token, args.player)
    mutation: dict[str, Any] | None = None
    if not args.search_only:
        mutation = remember(args.base_url, args.token, scope_id, args.player, args.choice)
    result = search(args.base_url, args.token, scope_id, args.player)
    hits = result.get("hits") or []
    if not isinstance(hits, list):
        raise RuntimeError("PowerContext search response did not contain a hit list")
    matching = [hit for hit in hits if isinstance(hit, dict) and args.choice in str(hit.get("text", ""))]
    if not args.search_only and not matching:
        raise RuntimeError("The remembered choice was not returned by PowerContext search")

    report = {
        "status": "PASS",
        "scope_id": scope_id,
        "remember_revision": (mutation.get("memory") or {}).get("revision") if mutation else None,
        "hit_count": len(hits),
        "matching_choice_count": len(matching),
        "hits": hits,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(1) from error
