#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from structured_pdf_extract import BASE_DIR, build_document


def _load_dotenv() -> None:
    """Load KEY=value pairs from .env at repo root into os.environ (no-op if absent)."""
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key and value and value != "your_key_here" and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


DATE_PATTERN = (
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},\s+\d{4}"
    r"|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+\d{4}"
)

CIRCULAR_NUMBER_RE = re.compile(r"\bCIRCULAR\s+([A-Z0-9/().-]+)\b")
ISSUE_DATE_RE = re.compile(DATE_PATTERN, re.IGNORECASE)
SUBJECT_RE = re.compile(r"\b(?:Sub|Subject)\s*:\s*(.+?)(?=\s+\d+\.\s|$)", re.IGNORECASE | re.DOTALL)
LEADING_ALIAS_RE = re.compile(r"^\s*\(([^)]+)\)")

MASTER_CIRCULAR_RE = re.compile(
    rf"(?P<full>(?P<prefix>(?:SEBI['’]s\s+)?)Master\s+Circular(?P<body>[^.;:\n]*?)\s+dated\s+(?P<date>{DATE_PATTERN})(?P<suffix>[^.;:\n]*))",
    re.IGNORECASE,
)
SEBI_CIRCULAR_RE = re.compile(
    rf"(?P<full>SEBI\s+Circular(?:\s+no\.)?\s+(?P<identifier>[A-Z]+(?:/[A-Z0-9().-]+)+)(?:\s+dated\s+(?P<date>{DATE_PATTERN}))?)",
    re.IGNORECASE,
)
FORMAL_INSTRUMENT_RE = re.compile(
    r"(?P<name>"
    r"(?:SEBI\s*\([^)]+\)\s*Regulations?"
    r"|Securities\s+and\s+Exchange\s+Board\s+of\s+India\s*\([^)]+\)\s*Regulations?"
    r"|Securities\s+and\s+Exchange\s+Board\s+of\s+India\s+Act"
    r"|Depositories\s+Act"
    r"|Banking\s+Regulations?\s+Act"
    r"|Securities\s+Contracts\s*\(Regulation\)\s*\(Stock\s+Exchanges\s+and\s+Clearing\s+Corporations\)\s*Regulations"
    r")\s*,?\s*(?P<year>(?:19|20)\d{2}))",
    re.IGNORECASE,
)
NOTIFICATION_RE = re.compile(
    rf"(?P<full>(?P<kind>Gazette\s+notification|notification)\s+dated\s+(?P<date>{DATE_PATTERN}))",
    re.IGNORECASE,
)

LOCATOR_PREFIX_RE = re.compile(
    r"(?P<locator>"
    r"(?:para(?:s)?|regulation(?:s)?|section(?:s)?|chapter|clause(?:s)?|annexure)"
    r"[^.;:\n]{0,140}"
    r")\s+of(?:\s+the)?\s*$",
    re.IGNORECASE,
)
PARAGRAPH_ITEM_RE = re.compile(r"\bpara(?:s)?\s+([0-9A-Za-z().,\- ]+(?:and\s+[0-9A-Za-z().,\- ]+)?)", re.IGNORECASE)
REGULATION_ITEM_RE = re.compile(
    r"\bregulation(?:s)?\s+([0-9A-Za-z().,\- ]+(?:and\s+[0-9A-Za-z().,\- ]+)?)",
    re.IGNORECASE,
)
SECTION_ITEM_RE = re.compile(
    r"\bsection(?:s)?\s+([0-9A-Za-z().,\- ]+(?:and\s+[0-9A-Za-z().,\- ]+)?)",
    re.IGNORECASE,
)
CHAPTER_ITEM_RE = re.compile(r"\bchapter\s+([IVXLC0-9A-Za-z().-]+)", re.IGNORECASE)
ANNEXURE_ITEM_RE = re.compile(r"\bannexure[-\s]*([A-Z0-9]+)\b", re.IGNORECASE)
CLAUSE_ITEM_RE = re.compile(r"\bclause(?:s)?\s+([0-9A-Za-z().,\- ]+(?:and\s+[0-9A-Za-z().,\- ]+)?)", re.IGNORECASE)

TOKEN_ITEM_RE = re.compile(
    r"\b[0-9]+(?:\([^)]+\))?(?:\.[0-9A-Za-z]+(?:\([^)]+\))?)*\b|\([ivxlcdm]+\)|\([a-z]+\)|\b[IVXLC]+\b",
    re.IGNORECASE,
)
SMART_QUOTES = str.maketrans({"“": '"', "”": '"', "’": "'", "‘": "'"})


@dataclass
class DocumentRecord:
    document_id: str
    document_type: str
    title: str | None
    short_title: str | None
    identifier: str | None
    date: str | None
    year: int | None
    issuing_body: str | None
    aliases: list[str]
    title_source: str
    resolution_status: str
    resolved_url: str | None


def compact(text: str) -> str:
    return " ".join(text.translate(SMART_QUOTES).split())


def clean_alias(text: str | None) -> str | None:
    if not text:
        return None
    alias = compact(text).strip("()[]{}\"' ")
    if not alias:
        return None
    if len(alias) > 80:
        return None
    return alias


def normalize_title_case_whitespace(text: str | None) -> str | None:
    if not text:
        return None
    return compact(text).strip(" .,:;")


def infer_document_type(name: str) -> str:
    lowered = name.lower()
    if "act" in lowered:
        return "act"
    if "master circular" in lowered:
        return "master_circular"
    if "circular" in lowered:
        return "circular"
    if re.search(r"\bregulations?\b", lowered):
        return "regulations"
    if "notification" in lowered:
        return "notification"
    return "other"


def relation_type_for(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ["stand amended", "stand replaced", "stand substituted", "stand deleted"]):
        return "amends_or_modifies"
    if any(token in lowered for token in ["issued in exercise", "read with"]):
        return "legal_basis"
    if any(token in lowered for token in ["specified as under", "provides", "specifies as under"]):
        return "quotes_or_cites"
    if any(token in lowered for token in ["in terms of", "vide "]):
        return "relies_on"
    return "references"


def confidence_for(is_alias_only: bool, record: DocumentRecord) -> tuple[float, str, str]:
    if is_alias_only:
        return 0.74, "medium", "Alias-only mention resolved from an earlier full-form citation in the same PDF."
    if record.document_type in {"act", "regulations"}:
        return 0.93, "high", "Full formal title and year are present in the source paragraph."
    if record.document_type == "master_circular" and record.title and record.date:
        return 0.92, "high", "Full master circular title and issue date are present in the source paragraph."
    if record.document_type == "circular" and record.identifier:
        return 0.91, "high", "SEBI circular identifier is present in the source paragraph."
    if record.document_type == "notification" and record.date:
        return 0.68, "medium", "Notification date is present, but title and identifier are absent."
    return 0.61, "medium", "Document reference is partially specified."


def parse_year(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"(19|20)\d{2}", value)
    return int(match.group(0)) if match else None


def build_doc_key(document_type: str, title: str | None, identifier: str | None, date: str | None, year: int | None) -> str:
    key_title = normalize_title_case_whitespace(title) or ""
    key_identifier = (identifier or "").upper()
    key_date = (date or "").upper()
    key_year = str(year or "")
    return "|".join([document_type, key_title.upper(), key_identifier, key_date, key_year])


class Registry:
    def __init__(self) -> None:
        self._doc_counter = 0
        self._by_key: dict[str, DocumentRecord] = {}
        self._aliases: dict[str, str] = {}

    def upsert(
        self,
        *,
        document_type: str,
        title: str | None,
        short_title: str | None,
        identifier: str | None,
        date: str | None,
        year: int | None,
        issuing_body: str | None,
        aliases: Iterable[str],
        title_source: str,
    ) -> DocumentRecord:
        key = build_doc_key(document_type, title, identifier, date, year)
        existing = self._by_key.get(key)
        if existing:
            alias_set = set(existing.aliases)
            alias_set.update(clean_alias(alias) for alias in aliases)
            existing.aliases = sorted(alias for alias in alias_set if alias)
            if short_title and not existing.short_title:
                existing.short_title = short_title
            for alias in existing.aliases:
                self._aliases[alias.casefold()] = existing.document_id
            return existing

        self._doc_counter += 1
        record = DocumentRecord(
            document_id=f"doc_{self._doc_counter:03d}",
            document_type=document_type,
            title=normalize_title_case_whitespace(title),
            short_title=normalize_title_case_whitespace(short_title),
            identifier=normalize_title_case_whitespace(identifier),
            date=normalize_title_case_whitespace(date),
            year=year,
            issuing_body=issuing_body,
            aliases=sorted({alias for alias in (clean_alias(alias) for alias in aliases) if alias}),
            title_source=title_source,
            resolution_status="unresolved",
            resolved_url=None,
        )
        self._by_key[key] = record
        for alias in record.aliases:
            self._aliases[alias.casefold()] = record.document_id
        return record

    def add_alias(self, alias: str, document_id: str) -> None:
        cleaned = clean_alias(alias)
        if cleaned:
            self._aliases[cleaned.casefold()] = document_id
            for record in self._by_key.values():
                if record.document_id == document_id and cleaned not in record.aliases:
                    record.aliases.append(cleaned)
                    record.aliases.sort()
                    break

    def record_for_alias(self, alias: str) -> DocumentRecord | None:
        document_id = self._aliases.get(alias.casefold())
        if not document_id:
            return None
        for record in self._by_key.values():
            if record.document_id == document_id:
                return record
        return None

    def records(self) -> list[DocumentRecord]:
        return sorted(self._by_key.values(), key=lambda record: record.document_id)

    def aliases(self) -> list[str]:
        return sorted(self._aliases.keys(), key=len, reverse=True)


def extract_source_metadata(document: dict) -> dict:
    first_page = document["pages"][0]
    page_text = compact(" ".join(line["text"] for line in first_page["lines"]))
    subject_match = SUBJECT_RE.search(page_text)
    circular_match = CIRCULAR_NUMBER_RE.search(page_text)
    issue_date_match = ISSUE_DATE_RE.search(page_text)
    return {
        "source_pdf": document["source_pdf"],
        "file_name": document["file_name"],
        "page_count": document["metadata"]["page_count"],
        "circular_number": circular_match.group(1) if circular_match else None,
        "issue_date": issue_date_match.group(0) if issue_date_match else None,
        "title": subject_match.group(1).strip(" .") if subject_match else None,
    }


def title_from_master_circular(match: re.Match[str]) -> tuple[str | None, str | None, list[str]]:
    prefix = compact(match.group("prefix") or "")
    body = compact(match.group("body") or "")
    date = compact(match.group("date"))
    suffix = compact(match.group("suffix") or "")

    title = "Master Circular"
    if body:
        # Strip a trailing parenthetical acronym from the body (e.g. ("RTAs")) so it
        # doesn't end up in the title.  The acronym is short enough to ignore as alias.
        body = re.sub(r'\s*\("?[A-Za-z]{2,10}"?\)\s*$', "", body).strip()
        title = f"{title} {body}".strip() if body else title
    elif prefix:
        trailer_match = re.match(
            r"for\s+(.+?)(?=\s+\(|\s+(?:has|have|provides|provide|stand|stands|were|was|is|are)\b|$)",
            suffix,
            re.IGNORECASE,
        )
        if trailer_match:
            title = f"{title} for {compact(trailer_match.group(1))}"

    alias_match = re.search(r"\(([^)]*Master Circular[^)]*)\)", suffix, re.IGNORECASE)
    aliases = [clean_alias(alias_match.group(1))] if alias_match else []
    return normalize_title_case_whitespace(title), date, [alias for alias in aliases if alias]


def concise_master_circular_match_text(match: re.Match[str]) -> str:
    text = compact(match.group("full"))
    trimmed = re.split(r"\s+(?=has\b|have\b|provides\b|provide\b|stand\b|stands\b|were\b|was\b|is\b|are\b)", text, maxsplit=1, flags=re.IGNORECASE)[0]
    return trimmed


def parse_locator_tokens(raw: str) -> list[str]:
    values = []
    normalized = re.sub(r"(\d+)\s+\(([A-Za-z0-9]+)\)", r"\1(\2)", raw)
    for token in TOKEN_ITEM_RE.findall(normalized.replace(" to ", " ")):
        cleaned = token.strip(" ,.;:()")
        if cleaned and cleaned not in values:
            values.append(cleaned)
    return values


def extract_locators(prefix_text: str) -> dict:
    locator_match = LOCATOR_PREFIX_RE.search(prefix_text)
    if not locator_match:
        return {"raw": None, "paragraphs": [], "regulations": [], "sections": [], "chapters": [], "annexures": [], "clauses": []}

    raw = compact(locator_match.group("locator"))
    return {
        "raw": raw,
        "paragraphs": collect_locator_values(PARAGRAPH_ITEM_RE, raw),
        "regulations": collect_locator_values(REGULATION_ITEM_RE, raw),
        "sections": collect_locator_values(SECTION_ITEM_RE, raw),
        "chapters": collect_locator_values(CHAPTER_ITEM_RE, raw),
        "annexures": [value.upper() for value in ANNEXURE_ITEM_RE.findall(raw)],
        "clauses": collect_clause_values(raw),
    }


def collect_locator_values(pattern: re.Pattern[str], raw: str) -> list[str]:
    values: list[str] = []
    for match in pattern.finditer(raw):
        for token in parse_locator_tokens(match.group(1)):
            if token not in values:
                values.append(token)
    return values


def collect_clause_values(raw: str) -> list[str]:
    clause_match = CLAUSE_ITEM_RE.search(raw)
    if not clause_match:
        return []
    values: list[str] = []
    for token in re.findall(r"\(([^)]+)\)", clause_match.group(1)):
        cleaned = token.strip().lower()
        if cleaned and cleaned not in values:
            values.append(cleaned)
    return values


def merge_locator_maps(items: Iterable[dict]) -> dict:
    merged = {"raw": [], "paragraphs": [], "regulations": [], "sections": [], "chapters": [], "annexures": [], "clauses": []}
    for item in items:
        if item.get("raw") and item["raw"] not in merged["raw"]:
            merged["raw"].append(item["raw"])
        for key in ["paragraphs", "regulations", "sections", "chapters", "annexures", "clauses"]:
            for value in item.get(key, []):
                if value not in merged[key]:
                    merged[key].append(value)
    merged["raw"] = merged["raw"] or None
    return merged


def explicit_references_for_paragraph(text: str, registry: Registry) -> list[dict]:
    findings: list[dict] = []

    for match in MASTER_CIRCULAR_RE.finditer(text):
        title, date, aliases = title_from_master_circular(match)
        short_title = aliases[0] if aliases else "Master Circular"
        record = registry.upsert(
            document_type="master_circular",
            title=title,
            short_title=short_title,
            identifier=None,
            date=date,
            year=parse_year(date),
            issuing_body="SEBI",
            aliases=aliases + ["Master Circular"],
            title_source="explicit_in_text",
        )
        findings.append(
            {
                "match_span": match.span(),
                "match_text": concise_master_circular_match_text(match),
                "document": record,
                "is_alias_only": False,
                "locators": extract_locators(text[: match.start()]),
            }
        )

    for match in SEBI_CIRCULAR_RE.finditer(text):
        identifier = match.group("identifier")
        date = normalize_title_case_whitespace(match.group("date"))
        record = registry.upsert(
            document_type="circular",
            title=None,
            short_title=f"SEBI Circular {identifier}" + (f" dated {date}" if date else ""),
            identifier=identifier,
            date=date,
            year=parse_year(date or identifier),
            issuing_body="SEBI",
            aliases=[],
            title_source="not_present_in_text",
        )
        findings.append(
            {
                "match_span": match.span(),
                "match_text": compact(match.group("full")),
                "document": record,
                "is_alias_only": False,
                "locators": extract_locators(text[: match.start()]),
            }
        )

    for match in FORMAL_INSTRUMENT_RE.finditer(text):
        full = compact(match.group("name"))
        # Normalize singular "Regulation" to plural when the matched text uses it
        # (e.g. "SEBI (Credit Rating Agencies) Regulation, 1999" → "Regulations").
        full = re.sub(r"\bRegulation\b(?=\s*,\s*(?:19|20)\d{2})", "Regulations", full)
        year = parse_year(match.group("year"))
        record = registry.upsert(
            document_type=infer_document_type(full),
            title=full,
            short_title=None,
            identifier=None,
            date=None,
            year=year,
            issuing_body="SEBI" if full.upper().startswith("SEBI") else None,
            aliases=collect_following_aliases(text, match.end()),
            title_source="explicit_in_text",
        )
        findings.append(
            {
                "match_span": match.span(),
                "match_text": compact(match.group("name")),
                "document": record,
                "is_alias_only": False,
                "locators": extract_locators(text[: match.start()]),
            }
        )

    for match in NOTIFICATION_RE.finditer(text):
        kind = compact(match.group("kind"))
        date = compact(match.group("date"))
        record = registry.upsert(
            document_type="notification",
            title=kind.title(),
            short_title=kind.title(),
            identifier=None,
            date=date,
            year=parse_year(date),
            issuing_body="SEBI",
            aliases=[],
            title_source="generic_only",
        )
        findings.append(
            {
                "match_span": match.span(),
                "match_text": compact(match.group("full")),
                "document": record,
                "is_alias_only": False,
                "locators": extract_locators(text[: match.start()]),
            }
        )

    return dedupe_overlaps(findings)


def collect_following_aliases(text: str, start_index: int) -> list[str]:
    trailer = text[start_index : start_index + 40]
    match = LEADING_ALIAS_RE.match(trailer)
    alias = clean_alias(match.group(1)) if match else None
    return [alias] if alias else []


def dedupe_overlaps(findings: list[dict]) -> list[dict]:
    ordered = sorted(findings, key=lambda item: (item["match_span"][0], -(item["match_span"][1] - item["match_span"][0])))
    kept: list[dict] = []
    for item in ordered:
        span_start, span_end = item["match_span"]
        overlaps = False
        for existing in kept:
            existing_start, existing_end = existing["match_span"]
            if span_start >= existing_start and span_end <= existing_end:
                overlaps = True
                break
        if not overlaps:
            kept.append(item)
    return kept


def alias_references_for_paragraph(text: str, registry: Registry, explicit_spans: list[tuple[int, int]]) -> list[dict]:
    findings: list[dict] = []
    for alias in registry.aliases():
        if not alias:
            continue
        alias_text = alias
        pattern = re.compile(rf"\b{re.escape(alias_text)}\b", re.IGNORECASE)
        for match in pattern.finditer(text):
            if any(overlap(match.span(), span) for span in explicit_spans):
                continue
            record = registry.record_for_alias(alias_text)
            if not record:
                continue
            findings.append(
                {
                    "match_span": match.span(),
                    "match_text": compact(match.group(0)),
                    "document": record,
                    "is_alias_only": True,
                    "locators": extract_locators(text[: match.start()]),
                }
            )
    return dedupe_overlaps(findings)


def overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def should_skip_reference(match_text: str, paragraph_text: str, source_title: str | None) -> bool:
    lowered_match = match_text.lower()
    lowered_para = paragraph_text.lower()
    if "this circular" in lowered_match:
        return True
    if lowered_match.startswith("annexure-a") and "this circular" in lowered_para:
        return True
    if source_title and compact(source_title).lower() in lowered_match:
        return True
    return False


def consolidate_mentions(paragraph: dict, text: str, findings: list[dict], source_title: str | None) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for finding in findings:
        if should_skip_reference(finding["match_text"], text, source_title):
            continue
        grouped[finding["document"].document_id].append(finding)

    mentions: list[dict] = []
    for document_id, items in grouped.items():
        record = items[0]["document"]
        merged_locators = merge_locator_maps(item["locators"] for item in items)
        is_alias_only = all(item["is_alias_only"] for item in items)
        confidence, confidence_label, confidence_reason = confidence_for(is_alias_only, record)
        mentions.append(
            {
                "document_id": document_id,
                "source_page": paragraph["page_number"],
                "source_paragraph_id": paragraph["paragraph_id"],
                "match_texts": sorted({item["match_text"] for item in items}),
                "evidence_text": text,
                "relation_type": relation_type_for(text),
                "target_locators": merged_locators,
                "confidence": confidence,
                "confidence_label": confidence_label,
                "confidence_reason": confidence_reason,
            }
        )
    return sorted(mentions, key=lambda item: item["document_id"])


def ai_discovery_schema() -> dict:
    return {
        "type": "OBJECT",
        "properties": {
            "discovered_references": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "document_type": {
                            "type": "STRING",
                            "enum": ["circular", "master_circular", "regulations", "act", "notification"],
                        },
                        "title": {"type": ["STRING", "null"]},
                        "identifier": {"type": ["STRING", "null"]},
                        "year_or_date": {"type": ["STRING", "null"]},
                        "source_page": {"type": "INTEGER"},
                        "evidence_text": {"type": "STRING"},
                        "exact_quote": {"type": "STRING"},
                    },
                    "required": [
                        "document_type", "title", "identifier", "year_or_date",
                        "source_page", "evidence_text", "exact_quote",
                    ],
                },
            }
        },
        "required": ["discovered_references"],
    }


def build_ai_discovery_prompt(source: dict, structured: dict, already_found: list[DocumentRecord]) -> str:
    already_found_list = [
        {
            "document_type": r.document_type,
            "title": r.title or r.short_title,
            "identifier": r.identifier,
            "date": r.date,
        }
        for r in already_found
    ]

    pages_text_parts = []
    for page in structured["pages"]:
        para_texts = [compact(p["text"]) for p in page["paragraphs"] if compact(p["text"])]
        if para_texts:
            # Join paragraphs with a space so cross-paragraph title fragments
            # (e.g. "Regulations," on one line, "2018." on the next) read as
            # continuous text and are easier for the model to recognise.
            pages_text_parts.append(f"=== PAGE {page['page_number']} ===\n" + " ".join(para_texts))

    return "\n".join([
        "You are reviewing a SEBI circular PDF to find references to external documents.",
        "A regex extractor already found the references listed below.",
        "Your task: identify any ADDITIONAL references it missed.",
        "",
        "Already found by regex (do NOT return these again):",
        json.dumps(already_found_list, ensure_ascii=False, indent=2),
        "",
        "Rules:",
        "1. Only return references EXPLICITLY present in the document text below.",
        "2. Do NOT re-report any reference already in the 'already found' list.",
        "3. Do NOT return self-references ('this circular', 'present circular', 'the circular').",
        "4. Do NOT invent titles or identifiers — copy exactly from the text.",
        "5. source_page must be the page number from the === PAGE N === header where the text appears.",
        "6. If nothing was missed, return an empty discovered_references list.",
        "",
        "FULL DOCUMENT TEXT:",
        "\n\n".join(pages_text_parts),
    ])


def call_gemini_json(prompt: str, model: str, api_key: str, schema: dict) -> dict:
    request_body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseJsonSchema": schema,
            "temperature": 0.1,
        },
    }
    request = urllib.request.Request(
        url=f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps(request_body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))

    parts = payload.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    text = "".join(part.get("text", "") for part in parts).strip()
    if not text:
        raise ValueError("Gemini returned no structured JSON text.")
    return json.loads(text)


def apply_ai_discoveries(
    registry: Registry,
    discoveries: list[dict],
    mention_counter: int,
    source_title: str | None,
) -> tuple[list[dict], int]:
    new_mentions: list[dict] = []
    for disc in discoveries:
        exact_quote = disc.get("exact_quote") or ""
        evidence_text = disc.get("evidence_text") or ""

        skip_phrases = ("this circular", "present circular", "the circular")
        if any(phrase in exact_quote.lower() for phrase in skip_phrases):
            continue
        if source_title and compact(source_title).lower() in exact_quote.lower():
            continue

        doc_type = disc.get("document_type") or "other"
        title = normalize_title_case_whitespace(disc.get("title"))
        identifier = normalize_title_case_whitespace(disc.get("identifier"))

        # If AI put a section/locator reference in the identifier field (e.g. "Regulation 51"
        # or "Section 11 (1) of the Securities and Exchange"), it is not a real document
        # identifier.  If a title is also present, just clear the identifier and keep the
        # record (the title is the canonical key).  If there is no title either, the record
        # is useless — skip it entirely.
        if identifier and re.search(r"^(?:section|regulation|article|clause|para)\b", identifier.lower()):
            if not title:
                continue
            identifier = None
        raw_date = (disc.get("year_or_date") or "").strip()
        year = parse_year(raw_date)
        date = normalize_title_case_whitespace(raw_date) if raw_date and not re.fullmatch(r"(19|20)\d{2}", raw_date) else None

        # For regulations/acts, append year to title if not already present so the canonical
        # title matches the "Name, YEAR" format that regex extraction and eval gold use.
        if title and year and doc_type in {"regulations", "act"} and str(year) not in title:
            title = f"{title}, {year}"

        # Drop clearly truncated or incomplete formal-instrument titles:
        # a valid act title must contain the word "Act"; a valid regulations title must contain
        # "Regulation". If absent, the PDF text was cut off and the record is unusable.
        if doc_type == "act" and title and not re.search(r"\bact\b", title.lower()):
            continue
        if doc_type == "regulations" and title and not re.search(r"\bregulations?\b", title.lower()):
            continue

        record = registry.upsert(
            document_type=doc_type,
            title=title,
            short_title=None,
            identifier=identifier,
            date=date,
            year=year,
            issuing_body="SEBI" if (
                doc_type in {"circular", "master_circular"}
                or (title or "").upper().startswith("SEBI")
            ) else None,
            aliases=[],
            title_source="ai_discovered",
        )

        mention_counter += 1
        loc_prefix = evidence_text[: evidence_text.find(exact_quote)] if exact_quote in evidence_text else ""
        new_mentions.append({
            "mention_id": f"ref_{mention_counter:03d}",
            "document_id": record.document_id,
            "source_page": disc.get("source_page", 1),
            "source_paragraph_id": None,
            "match_texts": [exact_quote] if exact_quote else [],
            "evidence_text": evidence_text,
            "relation_type": relation_type_for(evidence_text),
            "target_locators": extract_locators(loc_prefix),
            "confidence": 0.77,
            "confidence_label": "medium",
            "confidence_reason": "Reference identified by AI; not matched by deterministic regex.",
        })

    return new_mentions, mention_counter


def analyze_document(pdf_path: Path, *, use_ai: bool = False, resolve_urls: bool = False, gemini_model: str = "gemini-2.5-flash") -> dict:
    structured = build_document(pdf_path)
    source = extract_source_metadata(structured)
    registry = Registry()
    mention_counter = 0
    mentions: list[dict] = []

    for page in structured["pages"]:
        for paragraph in page["paragraphs"]:
            text = compact(paragraph["text"])
            if not text:
                continue
            explicit = explicit_references_for_paragraph(text, registry)
            alias_only = alias_references_for_paragraph(text, registry, [item["match_span"] for item in explicit])
            paragraph_mentions = consolidate_mentions(paragraph | {"page_number": page["page_number"]}, text, explicit + alias_only, source["title"])
            for mention in paragraph_mentions:
                mention_counter += 1
                mention["mention_id"] = f"ref_{mention_counter:03d}"
                mentions.append(mention)

    records = registry.records()
    ai_section: dict = {"enabled": False, "provider": None, "model": None, "discovered_count": 0}
    if use_ai:
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("AI review requested, but GEMINI_API_KEY / GOOGLE_API_KEY is missing.")
        discovery_prompt = build_ai_discovery_prompt(source, structured, records)
        discovery_payload = call_gemini_json(discovery_prompt, gemini_model, api_key, ai_discovery_schema())
        new_mentions, mention_counter = apply_ai_discoveries(
            registry, discovery_payload.get("discovered_references", []), mention_counter, source["title"]
        )
        mentions.extend(new_mentions)
        records = registry.records()
        ai_section = {
            "enabled": True,
            "provider": "gemini",
            "model": gemini_model,
            "discovered_count": len(new_mentions),
        }

    url_resolution: dict = {"enabled": False, "resolved": 0, "resolved_approx": 0, "unresolved": 0}
    if resolve_urls:
        sys.path.insert(0, str(Path(__file__).parent))
        from resolve_urls import resolve_document_urls  # noqa: PLC0415
        counts = resolve_document_urls(records)
        url_resolution = {"enabled": True, **counts}

    return structured, {
        "schema_version": "1.0.0",
        "extraction_method": {
            "mode": "deterministic_with_ai_discovery" if use_ai else "deterministic",
            "layout_parser": "pdfminer + pypdf via structured_pdf_extract.py",
            "llm_used": use_ai,
        },
        "source_document": source,
        "ai_discovery": ai_section,
        "url_resolution": url_resolution,
        "referenced_documents": [record.__dict__ for record in records],
        "reference_mentions": mentions,
        "summary": {
            "referenced_document_count": len(records),
            "reference_mention_count": len(mentions),
            "pages_with_references": sorted({mention["source_page"] for mention in mentions}),
        },
    }


def input_paths(path_arg: str) -> Iterable[Path]:
    path = Path(path_arg)
    if path.is_dir():
        yield from sorted(path.glob("*.pdf"))
    else:
        yield path


def output_path_for(pdf_path: Path, output_dir: Path) -> Path:
    return output_dir / f"{pdf_path.stem}.references.json"


def pages_path_for(pdf_path: Path, output_dir: Path) -> Path:
    return output_dir / f"{pdf_path.stem}.pages.json"


def build_pages_output(structured: dict) -> dict:
    """Slim structured text for the viewer — all pages, all paragraphs."""
    return {
        "pages": [
            {
                "page_number": page["page_number"],
                "paragraphs": [
                    {"paragraph_id": p["paragraph_id"], "text": compact(p["text"])}
                    for p in page["paragraphs"]
                    if compact(p["text"])
                ],
            }
            for page in structured["pages"]
        ]
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract structured references from SEBI circular PDFs.")
    parser.add_argument("input", help="PDF file or directory containing PDFs")
    parser.add_argument(
        "--output-dir",
        default=str(BASE_DIR / "reference-output"),
        help="Directory for reference JSON output files",
    )
    parser.add_argument("--use-ai", action="store_true", help="Enable Gemini discovery pass to find references the regex extractor missed")
    parser.add_argument("--resolve-urls", action="store_true", help="Attempt to resolve sebi.gov.in URLs for referenced documents via the SEBI listing API")
    parser.add_argument("--gemini-model", default="gemini-2.5-flash", help="Gemini model name for optional AI review")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pdf_paths = list(input_paths(args.input))
    if not pdf_paths:
        raise SystemExit("No PDF files found.")

    for pdf_path in pdf_paths:
        try:
            structured, result = analyze_document(pdf_path, use_ai=args.use_ai, resolve_urls=args.resolve_urls, gemini_model=args.gemini_model)
        except (RuntimeError, urllib.error.URLError, ValueError) as exc:
            print(f"{pdf_path}: {exc}", file=sys.stderr)
            return 1
        output_path = output_path_for(pdf_path, output_dir)
        output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        pages_path = pages_path_for(pdf_path, output_dir)
        pages_path.write_text(json.dumps(build_pages_output(structured), indent=2, ensure_ascii=False), encoding="utf-8")
        print(output_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
