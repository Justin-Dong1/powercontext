"""Count-trigger regressions beyond the published minimum examples."""

from __future__ import annotations

import asyncio
import importlib

from powercontext.builtin.runtime import open_builtin_runtime

checks = importlib.import_module("challenges.processing-01-count-trigger.acceptance.checks")


def test_memory_rechecks_a_burst_after_each_bounded_window(tmp_path, monkeypatch):
    async def scenario():
        with checks.provider(monkeypatch) as server:
            settings = checks.config(
                tmp_path / "burst.db",
                server,
                memory_source_count_threshold=3,
                source_window_limit=1,
            )
            async with open_builtin_runtime(settings) as runtime:
                scope_id = await checks.scope(runtime, "burst")
                receipts = await checks.capture(runtime, scope_id, checks.messages()[:6])
                expected = checks.receipt_refs(receipts[:4])
                await checks.wait_refs(runtime, scope_id, "memory", expected)
                await checks.stay_refs(runtime, scope_id, "memory", expected)

    asyncio.run(scenario())
