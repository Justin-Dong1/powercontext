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

"""Complete PDF page capture and scoped Memory citation search."""

from __future__ import annotations

import hashlib
import io
import re
from itertools import pairwise
from urllib.parse import quote

from pydantic import BaseModel, Field
from pypdf import PdfReader

from powercontext.builtin.artifacts.memory.models import MemoryCitation, MemoryEntryVersion
from powercontext.builtin.runtime import GetMemoryEntryRequest, SearchMemoryRequest
from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.definitions import AdapterSourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

PDF_PAGE_SOURCE_NAME = "pdf-page"


class PDFDocumentInput(BaseModel):
    """One complete original PDF document."""

    document_id: str
    content: bytes


class PDFPageInput(BaseModel):
    """Extracted text for one physical page of one immutable PDF revision."""

    document_id: str
    document_sha256: str
    page_number: int = Field(ge=1)
    text: str


class PDFPageSource(Source):
    """A captured physical PDF page."""

    source_id: str
    document_id: str
    document_sha256: str
    page_number: int = Field(ge=1)
    text: str


def pdf_page_source_id(document_id: str, document_sha256: str, page_number: int) -> str:
    if not document_id.strip():
        raise ValueError("document_id must not be blank")  # noqa: TRY003
    if len(document_sha256) != 64 or any(character not in "0123456789abcdef" for character in document_sha256):
        raise ValueError("document_sha256 must be a lowercase SHA-256 digest")  # noqa: TRY003
    if page_number < 1:
        raise ValueError("page_number must be positive")  # noqa: TRY003
    encoded_document_id = quote(document_id, safe="")
    source_id = f"pdf:{encoded_document_id}:{document_sha256}:{page_number}"
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        # Preserve stable revision/page identity for arbitrarily long public document IDs
        # without truncating two different IDs to the same prefix.
        document_identity = hashlib.sha256(document_id.encode("utf-8")).hexdigest()
        source_id = f"pdf-sha256:{document_identity}:{document_sha256}:{page_number}"
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"source_id must not exceed {MAX_SOURCE_ID_LENGTH} characters")  # noqa: TRY003
    return source_id


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    """Extract every physical page, failing atomically if any page cannot be read."""

    if not value.document_id.strip():
        raise ValueError("document_id must not be blank")  # noqa: TRY003
    document_sha256 = hashlib.sha256(value.content).hexdigest()
    try:
        reader = PdfReader(io.BytesIO(value.content), strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("PDF requires a non-empty password")  # noqa: TRY003, TRY301
        texts = tuple(page.extract_text() or "" for page in reader.pages)
    except ValueError:
        raise
    except Exception as error:
        raise ValueError("content must be a complete readable PDF") from error  # noqa: TRY003
    if not texts:
        raise ValueError("PDF must contain at least one physical page")  # noqa: TRY003
    return tuple(
        PDFPageInput(
            document_id=value.document_id,
            document_sha256=document_sha256,
            page_number=page_number,
            text=text,
        )
        for page_number, text in enumerate(texts, start=1)
    )


class PDFPageSourceAdapter:
    input_class = PDFPageInput
    name = PDF_PAGE_SOURCE_NAME
    source_class = PDFPageSource

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        source_id = pdf_page_source_id(value.document_id, value.document_sha256, value.page_number)
        return PDFPageSource(
            name=source_id,
            source_id=source_id,
            materialization=SourceMaterialization.CAPTURED,
            **value.model_dump(),
        )

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return PDFPageInput(
            document_id=source.document_id,
            document_sha256=source.document_sha256,
            page_number=source.page_number,
            text=source.text,
        )


class PDFPageTextEvidenceProjection:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PDFPageSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PDF_PAGE_SOURCE_NAME,
            source_id=source.source_id,
            content=f"{source.document_id}\n{source.text}",
            metadata={
                "document_id": source.document_id,
                "document_sha256": source.document_sha256,
                "page_number": source.page_number,
            },
        )


PDF_PAGE_SOURCE_ADAPTER = PDFPageSourceAdapter()
PDF_PAGE_SOURCE_DEFINITION = AdapterSourceDefinition(
    PDF_PAGE_SOURCE_ADAPTER,
    projections=(PDFPageTextEvidenceProjection(),),
)


def _pdf_heading_match(text: str, query: str) -> float:
    """Prefer precise, early evidence lines over repeated terms in prose."""

    def terms(value: str) -> frozenset[str]:
        normalized = []
        for word in re.findall(r"[a-z]+", value.casefold()):
            if word in {"of", "the", "and", "to", "for", "at", "in", "from", "our"}:
                continue
            if word.endswith("ies") and len(word) > 4:
                word = word[:-3] + "y"
            elif word.endswith("s") and not word.endswith("ss") and len(word) > 4:
                word = word[:-1]
            normalized.append(word)
        return frozenset(normalized)

    wanted = terms(query)
    if not wanted:
        return 0.0
    # The standard projection starts with the document identifier. Score only
    # the page body; source identity is not evidence for the question.
    body = text.partition("\n")[2]
    leading = [line.strip() for line in body[:1600].splitlines() if line.strip()][:12]
    best = 0.0
    for index, line in enumerate(leading):
        if len(line) <= 160 and len(re.findall(r"[a-z]+", line.casefold())) <= 16:
            found = terms(line)
            if found:
                precision_recall = 2 * len(wanted & found) / (len(wanted) + len(found))
                best = max(best, precision_recall / (1 + index / 12))
    return best


async def _prioritize_pdf_heading_hits(memory, hits, query: str, entries):
    """Load exact candidate evidence once and retain search rank for ties."""
    scored = []
    for original_rank, hit in enumerate(hits):
        identity = (hit.memory_ref.artifact_id, hit.entry_id, hit.entry_version_id)
        if identity not in entries:
            citation = MemoryCitation(
                memory_ref=hit.memory_ref,
                entry_id=hit.entry_id,
                entry_version_id=hit.entry_version_id,
            )
            entries[identity] = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry
        scored.append((-_pdf_heading_match(entries[identity].text, query), original_rank, hit))
    return [item[2] for item in sorted(scored, key=lambda item: (item[0], item[1]))]


async def search_pdf_pages(memory, question: str, limit: int = 10) -> tuple[MemoryCitation, ...]:
    """Search a scoped Memory and return distinct, exact page citations."""

    if limit < 1:
        raise ValueError("limit must be positive")  # noqa: TRY003
    queries = _pdf_search_queries(question)
    ranked: dict[tuple[str, str, str], tuple[float, MemoryCitation]] = {}
    priority: list[tuple[str, str, str]] = []
    entries: dict[tuple[str, str, str], MemoryEntryVersion] = {}
    expansion_queries = frozenset(_finance_expansions(question))
    for query_index, query in enumerate(queries):
        page = await memory.search(SearchMemoryRequest(query=query, mode="fts", limit=max(limit * 3, 40)))
        weight = 1.25 if query_index and query in expansion_queries else 1.0
        hits = list(page.hits)
        if query in expansion_queries:
            hits = await _prioritize_pdf_heading_hits(memory, hits, query, entries)
        for rank, hit in enumerate(hits, start=1):
            citation = MemoryCitation(
                memory_ref=hit.memory_ref,
                entry_id=hit.entry_id,
                entry_version_id=hit.entry_version_id,
            )
            identity = (hit.memory_ref.artifact_id, hit.entry_id, hit.entry_version_id)
            score, _ = ranked.get(identity, (0.0, citation))
            ranked[identity] = (score + weight / (8 + rank), citation)
            # Preserve a small quota from each semantic financial probe before
            # fused lexical results can crowd it out.  Multi-metric questions
            # commonly require different statement pages (for example income
            # and cash-flow statements), so summing every token probe alone is
            # systematically biased toward pages matching many generic words.
            if rank <= 2 and (query_index == 0 or query in expansion_queries) and identity not in priority:
                priority.append(identity)

    citations: list[MemoryCitation] = []
    seen_sources: set[str] = set()
    fused = sorted(
        ranked,
        key=lambda identity: (
            -ranked[identity][0],
            ranked[identity][1].entry_id,
            ranked[identity][1].entry_version_id,
        ),
    )
    ordered = tuple(dict.fromkeys((*priority, *fused)))
    for identity in ordered:
        citation = ranked[identity][1]
        entry = entries.get(identity)
        if entry is None:
            entry = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry
        source_ids = tuple(source.source_id for source in entry.sources if source.source_type == PDF_PAGE_SOURCE_NAME)
        if not source_ids or any(source_id in seen_sources for source_id in source_ids):
            continue
        seen_sources.update(source_ids)
        citations.append(citation)
        if len(citations) == limit:
            break
    return tuple(citations)


_PDF_QUERY_STOPWORDS = frozenset({
    "answer",
    "calculate",
    "company",
    "details",
    "directly",
    "explicitly",
    "fiscal",
    "from",
    "give",
    "important",
    "information",
    "million",
    "millions",
    "only",
    "outlined",
    "perspective",
    "primarily",
    "question",
    "relying",
    "reported",
    "respond",
    "shown",
    "state",
    "statements",
    "using",
    "what",
    "which",
    "with",
    "would",
    "year",
    "years",
    "fy",
})

_FINANCE_QUERY_EXPANSIONS = {
    "geograph": (
        "reportable segments",
        "our operations",
        "geographic areas",
        "countries territories",
        "international markets",
    ),
    "legal": ("legal proceedings", "material litigation"),
    "restructur": ("restructuring charges", "restructuring costs"),
    "ebitda": (
        "operating profit",
        "depreciation amortization",
        "consolidated statement income",
        "consolidated statement cash flows",
    ),
    "capital": (
        "capital expenditures",
        "capital spending",
        "property plant equipment",
        "consolidated balance sheet",
        "consolidated statement cash flows",
        "consolidated statement income",
    ),
    "capex": ("capital expenditures", "capital spending"),
    "margin": ("net revenue", "net sales", "operating income"),
    "revenue": (
        "net revenue",
        "net sales",
        "total revenues",
        "consolidated statements operations",
        "consolidated statement income",
        "summary business segment data",
        "segment revenues",
        "total net sales operating expenses",
    ),
    "sales": ("net sales", "net revenue"),
    "debt": ("long term debt", "borrowings"),
    "cash": ("cash flows", "net cash"),
    "payable": (
        "accounts payable",
        "cost of sales",
        "inventories",
        "consolidated balance sheets",
        "consolidated statements operations",
        "total net sales operating expenses",
    ),
    "quick ratio": (
        "cash equivalents",
        "short term investments",
        "accounts receivable",
        "current liabilities",
        "consolidated balance sheets",
    ),
    "liquidity": (
        "cash equivalents",
        "short term investments",
        "accounts receivable",
        "current liabilities",
        "consolidated balance sheets",
    ),
    "customer": (
        "customer accounted",
        "one customer",
        "customer concentration",
        "commercial airlines",
        "U.S. government",
        "government contracts",
        "significant portion revenues",
        "substantial portion revenue",
    ),
    "tax": ("income taxes", "effective tax"),
    "impair": ("impairment charges", "asset impairment"),
    "acquisition": ("business acquisitions", "purchase consideration"),
    "lease": ("lease liabilities", "operating leases"),
    "segment": ("reportable segments", "segment results"),
}


def _finance_expansions(question: str) -> tuple[str, ...]:
    normalized = question.casefold()
    expansions: list[str] = []
    for marker, values in _FINANCE_QUERY_EXPANSIONS.items():
        if marker in normalized:
            expansions.extend(values)
    years = tuple(dict.fromkeys(re.findall(r"(?:19|20)\d{2}", normalized)))
    if years:
        expansions.extend(f"{phrase} {year}" for phrase in tuple(expansions) for year in years[:2])
    return tuple(dict.fromkeys(expansions))


def _pdf_search_queries(question: str) -> tuple[str, ...]:
    """Create label-free lexical probes suited to page-level financial evidence."""

    tokens = [
        token
        for token in re.findall(r"[a-z]+|(?:19|20)\d{2}", question.casefold())
        if token not in _PDF_QUERY_STOPWORDS and (len(token) > 2 or token.isdigit())
    ]
    salient = tuple(dict.fromkeys(tokens))
    queries: list[str] = [question, *_finance_expansions(question)]
    queries.extend(" ".join(pair) for pair in pairwise(salient))
    queries.extend(token for token in salient if len(token) >= 7 or token.isdigit())
    return tuple(dict.fromkeys(query for query in queries if query.strip()))


__all__ = [
    "PDF_PAGE_SOURCE_ADAPTER",
    "PDF_PAGE_SOURCE_DEFINITION",
    "PDF_PAGE_SOURCE_NAME",
    "PDFDocumentInput",
    "PDFPageInput",
    "PDFPageSource",
    "PDFPageSourceAdapter",
    "PDFPageTextEvidenceProjection",
    "parse_pdf_document",
    "pdf_page_source_id",
    "search_pdf_pages",
]
