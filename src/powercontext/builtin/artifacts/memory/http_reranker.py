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

"""Identity-preserving batched HTTP scoring for Memory search candidates."""

from __future__ import annotations

import math

import httpx

from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.artifacts.memory.reranking import MemoryRerankDecision
from powercontext.builtin.inference import InferenceUsage


class HTTPMemoryReranker:
    """Score bounded HTTP batches, then select once across the complete pool."""

    def __init__(
        self,
        endpoint: str,
        *,
        client: httpx.AsyncClient,
        batch_size: int = 32,
        policy_id: str = "http-cross-encoder-v1",
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self.endpoint = endpoint
        self.client = client
        self.batch_size = batch_size
        self.policy_id = policy_id

    async def rerank(
        self,
        query: str,
        candidates: tuple[MemoryHit, ...],
        limit: int,
        /,
    ) -> MemoryRerankDecision:
        if not candidates:
            raise ValueError("rerank requires at least one candidate")
        if limit < 1 or limit > len(candidates):
            raise ValueError("rerank limit must be between one and the candidate count")

        scores: dict[int, float] = {}
        requests = 0
        ranked = tuple(enumerate(candidates, start=1))
        for start in range(0, len(ranked), self.batch_size):
            batch = ranked[start : start + self.batch_size]
            response = await self.client.post(
                self.endpoint,
                json={
                    "query": query,
                    "candidates": [{"rank": rank, "text": candidate.text} for rank, candidate in batch],
                },
            )
            requests += 1
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError as error:
                raise ValueError("rerank response must be valid JSON") from error
            scores.update(self._validate_scores(payload, expected={rank for rank, _candidate in batch}))

        selected = tuple(sorted(scores, key=lambda rank: (-scores[rank], rank))[:limit])
        return MemoryRerankDecision(
            selected_ranks=selected,
            usage=InferenceUsage(requests=requests),
        )

    @staticmethod
    def _validate_scores(payload: object, *, expected: set[int]) -> dict[int, float]:
        if not isinstance(payload, dict) or set(payload) != {"scores"} or not isinstance(payload["scores"], list):
            raise ValueError("rerank response must contain only a scores list")
        scores: dict[int, float] = {}
        for item in payload["scores"]:
            if not isinstance(item, dict) or set(item) != {"rank", "score"}:
                raise ValueError("each rerank score must contain only rank and score")
            rank, score = item["rank"], item["score"]
            if type(rank) is not int or rank not in expected or rank in scores:
                raise ValueError("rerank scores must cover each requested rank exactly once")
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
                raise ValueError("rerank scores must be finite numbers")
            scores[rank] = float(score)
        if set(scores) != expected:
            raise ValueError("rerank scores must cover each requested rank exactly once")
        return scores


__all__ = ["HTTPMemoryReranker"]
