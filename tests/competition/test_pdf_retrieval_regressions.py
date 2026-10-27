"""PDF retrieval must disambiguate reports and preserve financial concepts."""

from types import SimpleNamespace

import pytest

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.sources.pdf_pages import search_pdf_pages


class PageMemory:
    def __init__(self, pages):
        self.hits = tuple(
            MemoryHit(
                memory_ref=ArtifactRef(family="memory", artifact_id="reports", revision=1),
                entry_id=str(index),
                entry_version_id=f"v{index}",
                text=text,
                score=1,
                matched_by=("fts",),
            )
            for index, text in enumerate(pages)
        )

    async def search(self, request):
        # Mimic an OR index whose generic lexical scores favor the wrong report.
        terms = set(request.query.lower().split())
        hits = tuple(hit for hit in self.hits if any(term in hit.text.lower() for term in terms))
        return SimpleNamespace(hits=hits[: request.limit])

    async def get(self, request):
        hit = next(hit for hit in self.hits if hit.entry_id == request.citation.entry_id)
        assert request.citation.entry_version_id == hit.entry_version_id
        return SimpleNamespace(
            entry=SimpleNamespace(
                text=hit.text,
                sources=(SimpleNamespace(source_type="pdf-page", source_id=hit.entry_id),),
            )
        )


@pytest.mark.asyncio
async def test_financial_probes_do_not_return_another_company():
    memory = PageMemory([
        "OTHER_2024_10K\nOperating profit. Depreciation amortization. Capital expenditures. Cash flows.",
        "ACME_2024_10K\nConsolidated statement income\nOperating income 80. Net revenue 900.",
        "ACME_2024_10K\nConsolidated statement cash flows\nDepreciation amortization 20. Capital expenditures 10.",
    ])
    citations = await search_pdf_pages(memory, "What is Acme's 2024 EBITDA less capex?", limit=2)
    assert {citation.entry_id for citation in citations} == {"1", "2"}


@pytest.mark.asyncio
async def test_or_probe_false_positives_do_not_displace_statement_pages():
    memory = PageMemory([
        *(f"ACME_2024_10K\nCash awards and compensation for executive {index}." for index in range(25)),
        "ACME_2024_10K\nConsolidated statement cash flows\nDepreciation and amortization 20. Capital expenditures 10.",
        "ACME_2024_10K\nConsolidated statement income\nOperating income 80. Net revenue 900.",
    ])
    citations = await search_pdf_pages(memory, "What is Acme's EBITDA less capex?", limit=2)
    assert {citation.entry_id for citation in citations} == {"25", "26"}


@pytest.mark.asyncio
async def test_anonymous_document_id_does_not_filter_all_results():
    memory = PageMemory(["opaque-identifier\nLegal proceedings. No material litigation."])
    citations = await search_pdf_pages(memory, "Are there material legal proceedings?", limit=1)
    assert len(citations) == 1
