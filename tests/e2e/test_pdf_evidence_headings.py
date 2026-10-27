"""Real scoped Memory regression for statement pages crowded out by commentary."""

from pathlib import Path

import pytest

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    GetMemoryEntryRequest,
    SubmitSourceObservation,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import SourceDefinitionRegistry, manifest_for_definition, project_source_for_transport
from powercontext.sources.pdf_pages import PDF_PAGE_SOURCE_DEFINITION, PDFPageInput, search_pdf_pages
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY


class EvidencePipeline:
    async def extract(self, request, /):
        return tuple(
            MemoryEntryInput(
                kind="source-evidence",
                text=source.projection(TEXT_EVIDENCE_PROJECTION_KEY)["content"],
                sources=(source,),
            )
            for source in request.sources
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("short_headings", [False, True])
async def test_statement_evidence_survives_keyword_heavy_commentary(tmp_path: Path, short_headings: bool):
    config = BuiltinConfig(database=SQLiteConfig(url="sqlite+aiosqlite:///" + (tmp_path / "pdf.db").as_posix()))
    question = "What was the company's EBITDA in 2024 using the income statement and cash flow statement?"
    commentary = (
        "The company discusses EBITDA operating profit depreciation amortization consolidated statement income cash flows net cash in 2024. "
        * 3
    )
    prefix = (
        "Operating Profit Commentary\nDepreciation Amortization Discussion\nConsolidated Statement of Comprehensive Income\n"
        if short_headings
        else "Management discussion and analysis\n"
    )
    texts = [prefix + commentary for _ in range(4)]
    texts += [
        "CONSOLIDATED STATEMENTS OF INCOME\nNet revenue 100\nOperating profit 20\nNet income 15",
        "CONSOLIDATED STATEMENTS OF CASH FLOWS\nDepreciation and amortization 5\nNet cash from operations 30",
    ]
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    observations = []
    for index, text in enumerate(texts, 1):
        page = PDFPageInput(document_id="sample-report", document_sha256="a" * 64, page_number=index, text=text)
        observations.append(project_source_for_transport(registry, await registry.resolve(page)))
    async with open_builtin_runtime(config) as rt:
        scope = await rt.scopes.create(
            ScopeDraft(
                title="Statement evidence",
                summary="Synthetic regression",
                idempotency_key="statement-heading-regression",
            )
        )
        await rt.ingestion.register(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
        for observation in observations:
            await rt.ingestion.submit(SubmitSourceObservation(scope_id=scope.scope_id, observation=observation))
    async with open_builtin_runtime(config, candidate_pipeline=EvidencePipeline()) as rt:
        memory = rt.memory.for_scope(scope.scope_id)
        for _ in range(len(observations) + 1):
            if not (await memory.flush()).processed:
                break
    async with open_builtin_runtime(config) as rt:
        memory = rt.memory.for_scope(scope.scope_id)
        citations = await search_pdf_pages(memory, question, limit=5)
        pages = set()
        for citation in citations:
            entry = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry
            pages.update(
                int(source.source_id.rsplit(":", 1)[-1]) for source in entry.sources if source.source_type == "pdf-page"
            )
        assert {5, 6} <= pages
