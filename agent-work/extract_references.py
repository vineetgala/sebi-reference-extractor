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
    descriptive_title: str | None
    descriptive_title_source: str | None
    identifier: str | None
    date: str | None
    year: int | None
    issuing_body: str | None
    aliases: list[str]
    title_source: str
    ai_review_notes: str | None
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
            descriptive_title=None,
            descriptive_title_source=None,
            identifier=normalize_title_case_whitespace(identifier),
            date=normalize_title_case_whitespace(date),
            year=year,
            issuing_body=issuing_body,
            aliases=sorted({alias for alias in (clean_alias(alias) for alias in aliases) if alias}),
            title_source=title_source,
            ai_review_notes=None,
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


def ai_review_candidates(records: list[DocumentRecord], mentions: list[dict]) -> list[dict]:
    mention_index: dict[str, list[dict]] = defaultdict(list)
    for mention in mentions:
        mention_index[mention["document_id"]].append(mention)

    candidates: list[dict] = []
    for record in records:
        if record.document_type not in {"circular", "notification"}:
            continue
        if record.title:
            continue
        evidence_texts = []
        for mention in mention_index.get(record.document_id, [])[:3]:
            if mention["evidence_text"] not in evidence_texts:
                evidence_texts.append(mention["evidence_text"])
        if not evidence_texts:
            continue
        candidates.append(
            {
                "document_id": record.document_id,
                "document_type": record.document_type,
                "identifier": record.identifier,
                "date": record.date,
                "current_short_title": record.short_title,
                "evidence_texts": evidence_texts,
            }
        )
    return candidates


def gemini_review_schema() -> dict:
    return {
        "type": "OBJECT",
        "properties": {
            "reviews": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "document_id": {"type": "STRING"},
                        "keep_document": {"type": "BOOLEAN"},
                        "descriptive_title": {"type": "STRING", "nullable": True},
                        "descriptive_title_source": {
                            "type": "STRING",
                            "enum": ["none", "explicit_phrase_in_evidence", "purpose_clause_in_evidence"],
                        },
                        "notes": {"type": "STRING"},
                    },
                    "required": ["document_id", "keep_document", "descriptive_title", "descriptive_title_source", "notes"],
                },
            }
        },
        "required": ["reviews"],
    }


def build_ai_prompt(source: dict, candidates: list[dict]) -> str:
    instructions = [
        "You are reviewing deterministic reference extraction from a SEBI circular PDF.",
        "Use only the evidence snippets provided below. Do not use outside knowledge.",
        "For each candidate document:",
        "1. keep_document should usually be true unless the candidate is clearly not another document.",
        "2. descriptive_title should be null unless the evidence contains an identifying phrase beyond a bare identifier/date.",
        "3. If you provide descriptive_title, copy or lightly normalize the phrase from evidence. Do not invent an official title.",
        "4. If the evidence only gives an identifier and date, return descriptive_title as null and descriptive_title_source as none.",
    ]
    payload = {
        "source_document": {
            "title": source.get("title"),
            "circular_number": source.get("circular_number"),
            "issue_date": source.get("issue_date"),
        },
        "candidates": candidates,
    }
    return "\n".join(instructions) + "\n\nINPUT JSON:\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def call_gemini_json(prompt: str, model: str, api_key: str) -> dict:
    request_body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseJsonSchema": gemini_review_schema(),
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


def apply_ai_reviews(records: list[DocumentRecord], reviews: list[dict]) -> dict:
    review_index = {item["document_id"]: item for item in reviews}
    changes_applied = 0
    for record in records:
        review = review_index.get(record.document_id)
        if not review:
            continue
        record.ai_review_notes = review.get("notes")
        descriptive_title = normalize_title_case_whitespace(review.get("descriptive_title"))
        source = review.get("descriptive_title_source")
        if descriptive_title and descriptive_title != record.descriptive_title:
            record.descriptive_title = descriptive_title
            record.descriptive_title_source = source
            changes_applied += 1
    return {
        "reviewed_document_ids": sorted(review_index.keys()),
        "changes_applied": changes_applied,
    }


def analyze_document(pdf_path: Path, *, use_ai: bool = False, gemini_model: str = "gemini-2.5-flash") -> dict:
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
    ai_section = {
        "enabled": False,
        "provider": None,
        "model": None,
        "reviewed_document_ids": [],
        "changes_applied": 0,
    }
    if use_ai:
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("AI review requested, but GEMINI_API_KEY / GOOGLE_API_KEY is missing.")
        candidates = ai_review_candidates(records, mentions)
        ai_section = {
            "enabled": True,
            "provider": "gemini",
            "model": gemini_model,
            "reviewed_document_ids": [],
            "changes_applied": 0,
        }
        if candidates:
            prompt = build_ai_prompt(source, candidates)
            review_payload = call_gemini_json(prompt, gemini_model, api_key)
            ai_section.update(apply_ai_reviews(records, review_payload.get("reviews", [])))

    return {
        "schema_version": "1.0.0",
        "extraction_method": {
            "mode": "deterministic_with_optional_ai_review" if use_ai else "deterministic",
            "layout_parser": "pdfminer + pypdf via structured_pdf_extract.py",
            "llm_used": use_ai,
        },
        "source_document": source,
        "ai_enrichment": ai_section,
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract structured references from SEBI circular PDFs.")
    parser.add_argument("input", help="PDF file or directory containing PDFs")
    parser.add_argument(
        "--output-dir",
        default=str(BASE_DIR / "reference-output"),
        help="Directory for reference JSON output files",
    )
    parser.add_argument("--use-ai", action="store_true", help="Enable Gemini review for ambiguous identifier-only references")
    parser.add_argument("--gemini-model", default="gemini-2.5-flash", help="Gemini model name for optional AI review")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pdf_paths = list(input_paths(args.input))
    if not pdf_paths:
        raise SystemExit("No PDF files found.")

    for pdf_path in pdf_paths:
        try:
            result = analyze_document(pdf_path, use_ai=args.use_ai, gemini_model=args.gemini_model)
        except (RuntimeError, urllib.error.URLError, ValueError) as exc:
            print(f"{pdf_path}: {exc}", file=sys.stderr)
            return 1
        output_path = output_path_for(pdf_path, output_dir)
        output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(output_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
