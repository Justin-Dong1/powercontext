"""Regression coverage for the competition's public protocol boundaries."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory import EmbeddingProfile
from powercontext.builtin.artifacts.memory.http_reranker import HTTPMemoryReranker
from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.inference import EmbeddingResult
from powercontext.builtin.inference.coalescing import CoalescingEmbeddingModel
from powercontext.builtin.runtime import PrepareContextRequest
from powercontext.builtin.runtime.prepared_context import PreparedContextBuilder, PreparedMemoryCandidates
from powercontext.sources.pi_session import PiSessionInput, parse_pi_session


def test_pi_archive_requires_explicit_parent_even_for_root():
    content = "\n".join(json.dumps(record) for record in (
        {"type": "session", "version": 3, "id": "session"},
        {"type": "message", "id": "event", "message": {"role": "user", "content": "Hello"}},
    )).encode()
    with pytest.raises(ValueError):
        parse_pi_session(PiSessionInput(content=content))


@pytest.mark.parametrize("batch_size", [True, 1.5, "2"])
def test_http_batch_size_rejects_non_integer_values(batch_size):
    async def scenario():
        async with httpx.AsyncClient() as client:
            with pytest.raises(ValueError):
                HTTPMemoryReranker("https://score.invalid", client=client, batch_size=batch_size)
    asyncio.run(scenario())


@pytest.mark.parametrize("window", [float("nan"), float("inf")])
def test_embedding_window_must_be_finite(window):
    class Model:
        profile = EmbeddingProfile(profile_id="finite-window", model="offline", dimension=1)

    with pytest.raises(ValueError):
        CoalescingEmbeddingModel(Model(), coalesce_ms=window)


def test_embedding_batches_can_complete_while_another_batch_is_blocked():
    class Model:
        profile = EmbeddingProfile(profile_id="independent-batches", model="offline", dimension=1)

        def __init__(self):
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def embed(self, texts):
            if texts == ("slow",):
                self.started.set()
                await self.release.wait()
            return EmbeddingResult(vectors=tuple((float(len(text)),) for text in texts))

    async def scenario():
        base = Model()
        model = CoalescingEmbeddingModel(base, max_batch_size=1, coalesce_ms=0)
        slow = asyncio.create_task(model.embed(("slow",)))
        await base.started.wait()
        try:
            fast = await asyncio.wait_for(model.embed(("fast",)), timeout=0.25)
            assert fast.vectors == ((4.0,),)
        finally:
            base.release.set()
            await slow

    asyncio.run(scenario())


def test_evidence_falls_back_to_relevant_sentence_when_neighbors_exceed_budget():
    evidence = "The cobalt sensor calibration is 37 degrees."
    text = "Administrative background " + "neutral " * 45 + ". " + evidence + " Other records " + "routine " * 45 + "."
    memory_ref = ArtifactRef(family="memory", artifact_id="m", revision=1)
    hit = MemoryHit(memory_ref=memory_ref, entry_id="e", entry_version_id="v", text=text, score=1, matched_by=("fts",))
    result = PreparedContextBuilder().build_scopes_result(
        request=PrepareContextRequest(query="cobalt sensor calibration", max_bytes=600, evidence_selection=True),
        current_scope_id="s",
        memory_candidates=(PreparedMemoryCandidates(scope_id="s", memory_ref=memory_ref, hits=(hit,)),),
    )
    assert result.context.content_bytes <= 600
    assert any(evidence in fragment.text for fragment in result.fragments)
    for fragment in result.fragments:
        assert fragment.text == text[fragment.start:fragment.end]
