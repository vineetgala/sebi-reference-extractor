#!/usr/bin/env python3
"""FastAPI server for the SEBI Reference Extractor.

Usage:
    uvicorn api.server:app --reload --port 8000

Swagger UI:   http://localhost:8000/docs
ReDoc:        http://localhost:8000/redoc

Inputs accepted by POST /extract
  • url — SEBI circular webpage URL  OR  direct PDF URL
    Both URL types are auto-detected; no flag needed.
"""

from __future__ import annotations

import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

# ── Add agent-work/ to sys.path so extract_references can be imported ──────
_AGENT_WORK = Path(__file__).resolve().parent.parent / "agent-work"
if str(_AGENT_WORK) not in sys.path:
    sys.path.insert(0, str(_AGENT_WORK))

from extract_references import analyze_document  # noqa: E402

# ═══════════════════════════════════════════════════════════════════════════
#  URL RESOLUTION HELPERS
# ═══════════════════════════════════════════════════════════════════════════

_TIMEOUT = 30  # seconds
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; SEBI-Reference-Extractor/1.0; "
        "+https://github.com/sebi-reference-extractor)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
}


def _http_get(url: str, *, binary: bool = True) -> bytes | str:
    """GET a URL with a browser-like User-Agent.  Returns bytes or str."""
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        raw = resp.read()
    return raw if binary else raw.decode("utf-8", errors="replace")


def _pdf_filename_from_url(url: str) -> str:
    """Extract a clean filename from a PDF URL."""
    path = urllib.parse.urlparse(url).path
    name = path.rstrip("/").split("/")[-1]
    return name if name.lower().endswith(".pdf") else (name + ".pdf")


def _resolve_pdf_from_url(url: str) -> tuple[bytes, str, str]:
    """Download a PDF from a URL, handling two input types transparently.

    Accepts:
    • Direct PDF URL — any URL whose path ends in ``.pdf``
    • SEBI circular webpage — HTML page with an embedded PDF attachment link
      (e.g. ``https://www.sebi.gov.in/legal/circulars/...html``)

    Returns:
        (pdf_bytes, pdf_filename, pdf_url)

    Raises:
        ValueError — if a PDF cannot be located or downloaded.
    """
    url = url.strip()

    # ── Fast path: URL already points directly at a PDF ────────────────────
    if urllib.parse.urlparse(url).path.lower().endswith(".pdf"):
        try:
            data = _http_get(url, binary=True)
        except (urllib.error.URLError, OSError) as exc:
            raise ValueError(f"Could not download PDF from {url!r}: {exc}") from exc
        return data, _pdf_filename_from_url(url), url

    # ── Slow path: HTML page — scrape for a PDF attachment link ────────────
    try:
        html = _http_get(url, binary=False)
    except (urllib.error.URLError, OSError) as exc:
        raise ValueError(f"Could not fetch page {url!r}: {exc}") from exc

    # SEBI pages embed the PDF in an iframe viewer:
    #   <iframe src='...?file=https://www.sebi.gov.in/sebi_data/attachdocs/…pdf'>
    # Try that pattern first, then fall back to plain href attributes.
    candidates: list[str] = []

    # 1. ?file= parameter in iframe / any tag (SEBI's viewer pattern)
    candidates += re.findall(r'[?&]file=([^"\'&>\s]+?\.pdf)', html, re.IGNORECASE)

    # 2. href / src attributes ending in .pdf
    candidates += re.findall(r'(?:href|src)=["\']([^"\']*?\.pdf)["\']', html, re.IGNORECASE)

    if not candidates:
        raise ValueError(
            f"No PDF attachment found on page {url!r}. "
            "Ensure the URL points to a SEBI circular page that has a PDF attachment."
        )

    # Prefer attachdocs links; otherwise take the first candidate
    preferred = [c for c in candidates if "attachdocs" in c.lower()]
    chosen_href = preferred[0] if preferred else candidates[0]

    # Resolve relative → absolute
    pdf_url = urllib.parse.urljoin(url, chosen_href)

    try:
        data = _http_get(pdf_url, binary=True)
    except (urllib.error.URLError, OSError) as exc:
        raise ValueError(
            f"Found PDF link {pdf_url!r} on the page but could not download it: {exc}"
        ) from exc

    return data, _pdf_filename_from_url(pdf_url), pdf_url


# ═══════════════════════════════════════════════════════════════════════════
#  RESPONSE MODELS
# ═══════════════════════════════════════════════════════════════════════════

class ExtractionMethod(BaseModel):
    mode: str = Field(
        description="Either 'deterministic' or 'deterministic_with_ai_discovery'.",
        examples=["deterministic_with_ai_discovery"],
    )
    layout_parser: str = Field(
        description="PDF parsing stack used.",
        examples=["pdfminer + pypdf via structured_pdf_extract.py"],
    )
    llm_used: bool = Field(description="Whether an LLM was invoked during extraction.")


class SourceDocument(BaseModel):
    source_pdf: str = Field(
        description="The direct PDF URL that was downloaded and processed.",
        examples=["1769773760624.pdf"],
    )
    file_name: str = Field(description="Basename of the PDF.")
    source_url: Optional[str] = Field(
        default=None,
        description="The URL originally submitted (present only when input was a URL). "
                    "May be a SEBI webpage URL or a direct PDF URL.",
        examples=["https://www.sebi.gov.in/legal/circulars/jan-2026/ease-of-doing-investment_99421.html"],
    )
    page_count: int = Field(description="Total number of pages in the PDF.")
    circular_number: Optional[str] = Field(
        default=None,
        description="SEBI circular number extracted from the first page.",
        examples=["HO/38/13/(3)2026-MIRSD-POD/I/3763/2026"],
    )
    issue_date: Optional[str] = Field(
        default=None,
        description="Issue date of the circular as it appears in the PDF.",
        examples=["January 30, 2026"],
    )
    title: Optional[str] = Field(
        default=None,
        description="Subject line of the circular extracted from the first page.",
    )


class AiDiscovery(BaseModel):
    enabled: bool = Field(description="Whether the AI discovery pass was requested and ran.")
    provider: Optional[str] = Field(default=None, examples=["gemini"])
    model: Optional[str] = Field(default=None, examples=["gemini-2.5-flash"])
    discovered_count: int = Field(
        description="Number of new document references found by the AI discovery pass that regex missed."
    )


class ReferencedDocument(BaseModel):
    document_id: str = Field(examples=["doc_001"])
    document_type: str = Field(
        description="One of: act, regulations, master_circular, circular, notification, other.",
        examples=["regulations"],
    )
    title: Optional[str] = Field(
        default=None,
        description="Full formal title as it appears in the PDF text.",
        examples=["SEBI (Custodian) Regulations, 1996"],
    )
    short_title: Optional[str] = Field(
        default=None,
        description="Short-form title (alias or identifier+date for circulars).",
        examples=["SEBI Circular CIR/MIRSD/5/2013 dated August 27, 2013"],
    )
    identifier: Optional[str] = Field(
        default=None,
        description="SEBI circular identifier code, if present.",
        examples=["CIR/MIRSD/5/2013"],
    )
    date: Optional[str] = Field(default=None, examples=["August 27, 2013"])
    year: Optional[int] = Field(default=None, examples=[2013])
    issuing_body: Optional[str] = Field(default=None, examples=["SEBI"])
    aliases: list[str] = Field(
        description="Short-form aliases registered for this document.",
        examples=[["Custodian Regulations"]],
    )
    title_source: str = Field(
        description="'explicit_in_text', 'not_present_in_text', 'generic_only', or 'ai_discovered'.",
        examples=["explicit_in_text"],
    )
    resolution_status: str = Field(examples=["unresolved"])
    resolved_url: Optional[str] = Field(default=None)


class TargetLocators(BaseModel):
    raw: Optional[list[str]] = Field(
        default=None,
        description="Raw locator phrase(s) from the preceding text.",
        examples=[["para 13, 20, 22, 23 and Annexure-7, Annexure-15 and Annexure-20"]],
    )
    paragraphs: list[str] = Field(default=[], examples=[["13", "20", "22", "23"]])
    regulations: list[str] = Field(default=[], examples=[["101"]])
    sections: list[str] = Field(default=[], examples=[["11", "IV"]])
    chapters: list[str] = Field(default=[], examples=[["IV"]])
    annexures: list[str] = Field(default=[], examples=[["7", "15", "20"]])
    clauses: list[str] = Field(default=[], examples=[["a", "b"]])


class ReferenceMention(BaseModel):
    mention_id: str = Field(examples=["ref_001"])
    document_id: str = Field(
        description="Links to a document_id in referenced_documents.",
        examples=["doc_001"],
    )
    source_page: int = Field(
        description="Page in the *input PDF* where this reference appears (1-indexed).",
        examples=[1],
    )
    source_paragraph_id: str = Field(examples=["p1.9"])
    match_texts: list[str] = Field(
        description="Exact text fragment(s) that triggered this reference detection.",
        examples=[["Master Circular for Registrars to an Issue and Share Transfer Agents"]],
    )
    evidence_text: str = Field(
        description="Full paragraph text containing the reference."
    )
    relation_type: str = Field(
        description="'relies_on', 'legal_basis', 'references', 'amends_or_modifies', or 'quotes_or_cites'.",
        examples=["relies_on"],
    )
    target_locators: TargetLocators
    confidence: float = Field(ge=0.0, le=1.0, examples=[0.92])
    confidence_label: str = Field(examples=["high"])
    confidence_reason: str


class UrlResolution(BaseModel):
    enabled: bool = Field(description="Whether URL resolution was requested.")
    resolved: int = Field(default=0, description="High-confidence matches (score ≥ 0.60).")
    resolved_approx: int = Field(default=0, description="Low-confidence or single-date matches.")
    unresolved: int = Field(default=0, description="No match found or type not resolvable (e.g. notifications).")


class ExtractionSummary(BaseModel):
    referenced_document_count: int
    reference_mention_count: int
    pages_with_references: list[int] = Field(examples=[[1, 2]])


class ExtractionResult(BaseModel):
    schema_version: str = Field(examples=["1.0.0"])
    extraction_method: ExtractionMethod
    source_document: SourceDocument
    ai_discovery: AiDiscovery
    url_resolution: UrlResolution
    referenced_documents: list[ReferencedDocument]
    reference_mentions: list[ReferenceMention]
    summary: ExtractionSummary


# ═══════════════════════════════════════════════════════════════════════════
#  APP
# ═══════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="SEBI Reference Extractor",
    description=(
        "Extract all outbound document references from a SEBI circular — other circulars, "
        "master circulars, regulations, acts, and notifications — with source page, surrounding "
        "context, locator detail, and an optional Gemini-powered discovery pass.\n\n"
        "## Inputs\n\n"
        "`POST /extract` requires a `url` parameter:\n\n"
        "| Field | Type | Description |\n"
        "|---|---|---|\n"
        "| `url` | string | SEBI circular **webpage** URL *or* direct **PDF** URL — "
        "both are auto-detected, no flag needed |\n\n"
        "Examples of accepted URLs:\n"
        "```\n"
        "https://www.sebi.gov.in/legal/circulars/jan-2026/ease-of-doing-..._99421.html\n"
        "https://www.sebi.gov.in/sebi_data/attachdocs/jan-2026/1769773760624.pdf\n"
        "```\n\n"
        "## AI discovery\n\n"
        "Set `use_ai=true` and provide `GEMINI_API_KEY` in `.env` to run a Gemini pass that "
        "finds references the regex extractor missed — cross-paragraph title splits, acts not "
        "in the hardcoded pattern list, non-standard phrasing. Discovered records are tagged "
        "`title_source: ai_discovered` and merged with the regex findings.\n\n"
        "## URL resolution\n\n"
        "Set `resolve_urls=true` to have the server attempt to find a live sebi.gov.in URL "
        "for each referenced document via SEBI's listing API. "
        "Results are stored in `resolved_url` and `resolution_status` on each document entry. "
        "Status values: `resolved` (high confidence), `resolved_approx` (low confidence or "
        "single date match), `unresolved` (no match or non-resolvable type such as notifications)."
    ),
    version="1.0.0",
    contact={"name": "Hyde Assignment"},
    license_info={"name": "MIT"},
)


# ─── Routes ────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


@app.get("/health", summary="Health check", tags=["Utility"])
def health():
    """Returns `{"status": "ok"}` when the server is running."""
    return {"status": "ok"}


@app.post(
    "/extract",
    response_model=ExtractionResult,
    summary="Extract document references from a SEBI circular",
    tags=["Extraction"],
    responses={
        200: {"description": "Extraction succeeded."},
        400: {"description": "Bad input — no PDF found on page, missing AI key."},
        422: {"description": "Validation error — missing required fields."},
        500: {"description": "Unexpected extraction failure."},
    },
)
def extract_references(
    url: str = Form(
        description=(
            "URL of a SEBI circular. Accepted formats:\n\n"
            "- **Webpage URL** — the HTML page on sebi.gov.in "
            "(e.g. `https://www.sebi.gov.in/legal/circulars/jan-2026/..._99421.html`). "
            "The server fetches the page, finds the PDF attachment link, and downloads it.\n\n"
            "- **Direct PDF URL** — a URL whose path ends in `.pdf` "
            "(e.g. `https://www.sebi.gov.in/sebi_data/attachdocs/jan-2026/1769773760624.pdf`). "
            "Downloaded directly."
        ),
    ),
    use_ai: bool = Query(
        default=False,
        description=(
            "Enable Gemini discovery pass to find references the regex extractor missed. "
            "Requires `GEMINI_API_KEY` in `.env`."
        ),
    ),
    gemini_model: str = Query(
        default="gemini-2.5-flash",
        description="Gemini model to use when `use_ai=true`.",
    ),
    resolve_urls: bool = Query(
        default=False,
        description=(
            "Attempt to find sebi.gov.in listing URLs for each referenced document. "
            "Uses SEBI's internal AJAX API — makes one or more HTTP calls per document. "
            "Adds `resolved_url` and `resolution_status` to each entry in `referenced_documents`."
        ),
    ),
):
    """
    Extract all outbound document references from a SEBI circular.

    Provide the circular via `url` — a SEBI circular webpage URL or a direct PDF URL (auto-detected).

    The response contains:
    - **`referenced_documents`** — deduplicated list of every external document found.
    - **`reference_mentions`** — every individual mention with source page, context, and locators.
    - **`source_document`** — metadata extracted from the circular itself.
    - **`summary`** — counts and pages-with-references list.
    """
    # ── Acquire PDF bytes + metadata ───────────────────────────────────────
    submitted_url = url.strip()
    try:
        pdf_bytes, display_name, pdf_url = _resolve_pdf_from_url(submitted_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    source_ref = pdf_url

    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Received an empty PDF.")

    # ── Write to temp file and run extraction ──────────────────────────────
    tmp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(pdf_bytes)

        try:
            _structured, result = analyze_document(tmp_path, use_ai=use_ai, resolve_urls=resolve_urls, gemini_model=gemini_model)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except (ValueError, urllib.error.URLError) as exc:
            raise HTTPException(status_code=400, detail=f"Extraction error: {exc}")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Unexpected extraction error: {exc}")

        # ── Patch source_document with the actual input identifiers ────────
        result["source_document"]["source_pdf"] = source_ref
        result["source_document"]["file_name"]  = display_name
        result["source_document"]["source_url"] = submitted_url

        return result

    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink()
