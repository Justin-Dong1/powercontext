#!/usr/bin/env python3
"""Validate the submitted Dify DSL and execute its embedded narrative code."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
DSL_PATH = ROOT / "echo-maze.yml"


def load_dsl() -> dict[str, Any]:
    data = yaml.safe_load(DSL_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def node_map(dsl: dict[str, Any]) -> dict[str, dict[str, Any]]:
    nodes = dsl["workflow"]["graph"]["nodes"]
    return {node["id"]: node for node in nodes}


def run_embedded_story(code: str, recall_body: str, choice: str) -> dict[str, Any]:
    namespace: dict[str, Any] = {}
    exec(compile(code, "echo-maze-dify-code", "exec"), namespace)  # noqa: S102
    return namespace["main"](recall_body, "阿澈", choice)


def main() -> None:
    dsl = load_dsl()
    assert dsl["kind"] == "app"
    assert dsl["version"] == "0.3.0"
    assert dsl["app"]["mode"] == "workflow"

    nodes = node_map(dsl)
    assert set(nodes) == {"start", "recall", "narrate", "remember", "end"}
    assert nodes["recall"]["data"]["url"].endswith("/v1/memory/search")
    assert nodes["remember"]["data"]["url"].endswith("/v1/memory/remember")

    edge_pairs = {(edge["source"], edge["target"]) for edge in dsl["workflow"]["graph"]["edges"]}
    assert edge_pairs == {
        ("start", "recall"),
        ("recall", "narrate"),
        ("narrate", "remember"),
        ("remember", "end"),
    }

    code = nodes["narrate"]["data"]["code"]
    first = run_embedded_story(code, json.dumps({"hits": []}, ensure_ascii=False), "红门")
    assert first["echo_count"] == 0
    assert "首个回声" not in first["story"]
    assert "还没有你的回声" in first["story"]

    recalled = json.dumps(
        {"hits": [{"text": "玩家 阿澈 在回声迷宫选择了红门，进入倒悬钟楼。"}]},
        ensure_ascii=False,
    )
    second = run_embedded_story(code, recalled, "红门")
    assert second["echo_count"] == 1
    assert "上次已经选过这里" in second["story"]
    assert second["story"] != first["story"]

    print("DSL_VALIDATION_PASS")
    print("Nodes: start -> recall -> narrate -> remember -> end")
    print("Cross-run echo branch: PASS")


if __name__ == "__main__":
    main()
