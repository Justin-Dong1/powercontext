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

"""Concurrent request coalescing and bounded caching for embeddings."""

from __future__ import annotations

import asyncio
import math
from collections import OrderedDict, deque
from dataclasses import dataclass

from powercontext.builtin.inference.models import EmbeddingResult, EmbeddingVector, InferenceUsage
from powercontext.builtin.inference.protocols import EmbeddingModel


@dataclass(frozen=True, slots=True)
class _ResolvedEmbedding:
    vector: EmbeddingVector
    batch_id: int
    usage: InferenceUsage


def _sum_optional(values: list[int | None]) -> int | None:
    present = [value for value in values if value is not None]
    return sum(present) if present else None


class CoalescingEmbeddingModel:
    """Share in-flight embedding work and cache successful vectors by text."""

    def __init__(
        self,
        model: EmbeddingModel,
        *,
        max_batch_size: int = 64,
        coalesce_ms: float = 5.0,
        cache_size: int = 1024,
    ) -> None:
        if isinstance(max_batch_size, bool) or not isinstance(max_batch_size, int) or max_batch_size < 1:
            raise ValueError("max_batch_size must be a positive integer")  # noqa: TRY003
        if isinstance(cache_size, bool) or not isinstance(cache_size, int) or cache_size < 0:
            raise ValueError("cache_size must be a non-negative integer")  # noqa: TRY003
        if (
            isinstance(coalesce_ms, bool)
            or not isinstance(coalesce_ms, (int, float))
            or not math.isfinite(coalesce_ms)
            or coalesce_ms < 0
        ):
            raise ValueError("coalesce_ms must be a finite non-negative number")  # noqa: TRY003
        self._model = model
        self.profile = model.profile
        self._max_batch_size = max_batch_size
        self._coalesce_seconds = float(coalesce_ms) / 1000.0
        self._cache_size = cache_size
        self._cache: OrderedDict[str, EmbeddingVector] = OrderedDict()
        self._inflight: dict[str, asyncio.Future[_ResolvedEmbedding]] = {}
        self._queue: deque[str] = deque()
        self._dispatcher: asyncio.Task[None] | None = None
        self._next_batch_id = 0
        self._workers: set[asyncio.Task[None]] = set()

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult(vectors=(), usage=InferenceUsage(requests=0))

        pending: dict[str, asyncio.Future[_ResolvedEmbedding]] = {}
        cached: dict[str, EmbeddingVector] = {}
        loop = asyncio.get_running_loop()
        for text in dict.fromkeys(texts):
            vector = self._cache.get(text)
            if vector is not None:
                self._cache.move_to_end(text)
                cached[text] = vector
                continue
            future = self._inflight.get(text)
            if future is None:
                future = loop.create_future()
                future.add_done_callback(_observe_failure)
                self._inflight[text] = future
                self._queue.append(text)
            pending[text] = future

        if self._queue and (self._dispatcher is None or self._dispatcher.done()):
            self._dispatcher = asyncio.create_task(self._dispatch())

        resolved: dict[str, _ResolvedEmbedding] = {}
        for text, future in pending.items():
            resolved[text] = await asyncio.shield(future)

        batches: dict[int, InferenceUsage] = {}
        vectors: list[EmbeddingVector] = []
        for text in texts:
            if text in cached:
                vectors.append(cached[text])
                continue
            item = resolved[text]
            vectors.append(item.vector)
            batches[item.batch_id] = item.usage
        usages = list(batches.values())
        return EmbeddingResult(
            vectors=tuple(vectors),
            usage=InferenceUsage(
                requests=sum(usage.requests for usage in usages),
                input_tokens=_sum_optional([usage.input_tokens for usage in usages]),
                output_tokens=_sum_optional([usage.output_tokens for usage in usages]),
            ),
        )

    async def _dispatch(self) -> None:
        await asyncio.sleep(self._coalesce_seconds)
        while self._queue:
            texts = tuple(self._queue.popleft() for _ in range(min(self._max_batch_size, len(self._queue))))
            self._next_batch_id += 1
            worker = asyncio.create_task(self._run_batch(texts, self._next_batch_id))
            self._workers.add(worker)
            worker.add_done_callback(self._workers.discard)

    async def _run_batch(self, texts: tuple[str, ...], batch_id: int) -> None:
        futures = {text: self._inflight[text] for text in texts}
        try:
            result = await self._model.embed(texts)
            if len(result.vectors) != len(texts):
                raise ValueError("embedding model returned an unexpected number of vectors")  # noqa: TRY003, TRY301
            for text, vector in zip(texts, result.vectors, strict=True):
                if self._cache_size:
                    self._cache[text] = vector
                    self._cache.move_to_end(text)
                    while len(self._cache) > self._cache_size:
                        self._cache.popitem(last=False)
                if not futures[text].done():
                    futures[text].set_result(_ResolvedEmbedding(vector=vector, batch_id=batch_id, usage=result.usage))
        except asyncio.CancelledError:
            for future in futures.values():
                if not future.done():
                    future.cancel()
            raise
        except Exception as error:
            for future in futures.values():
                if not future.done():
                    future.set_exception(error)
        finally:
            for text, future in futures.items():
                if self._inflight.get(text) is future:
                    del self._inflight[text]


def _observe_failure(future: asyncio.Future[_ResolvedEmbedding]) -> None:
    # A cancelled or failed caller may no longer await every shared text.
    if not future.cancelled():
        future.exception()


__all__ = ["CoalescingEmbeddingModel"]
