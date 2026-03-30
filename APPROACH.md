# How the solution works

## Problem

SEBI circulars are published as PDFs. Each circular references other documents — prior circulars, master circulars, regulations, and acts — but these references are embedded in unstructured prose and the PDFs have no hyperlinks or metadata. A compliance team needs to trace these references, but doing it manually across hundreds of circulars doesn't scale.

The goal is to extract every outbound reference from a given circular PDF: what document is being cited, where (source page), and in what context.

---

## Two-layer extraction

The pipeline uses two complementary layers: a deterministic regex layer for the common well-defined patterns, and an AI layer to catch what the regex misses.

```
PDF
 └─ parse pages → paragraphs
      └─ regex extraction  ←── catches ~97% of references
           └─ AI discovery  ←── catches the rest
                └─ registry deduplication
                     └─ structured JSON output
```

### Why regex first

SEBI references follow a small number of very consistent patterns. A master circular always contains the phrase "Master Circular … dated [date]". A formal regulation is always "SEBI ([Name]) Regulations, [year]". An identifier-coded circular is always "SEBI Circular [CIR/XX/YY/ZZZZ]". These patterns are reliable enough that a hand-tuned regex achieves 100% precision with only minor configuration.

Using regex as the primary layer means extraction is fast, free, and fully deterministic — reproducible without an API key and without API calls.

### Why AI as a second layer

The regex processes one paragraph at a time. When a PDF renderer splits a title across two paragraph blocks (e.g. "…Regulations," on one line, "2018." on the next), the regex never sees the complete title and misses the reference entirely. This happened with `Securities Contracts (Regulation) (Stock Exchanges and Clearing Corporations) Regulations, 2018` in one of the development circulars.

More generally, any reference type not in the hardcoded pattern list is silently dropped. Acts, regulations, or circulars written in non-standard ways are invisible to regex.

The AI discovery pass fixes both problems. It receives the full page text (all paragraphs joined into one continuous string per page) and the list of references already found by regex, then returns any additional references it identifies in the text.

---

## Step-by-step

### 1. PDF parsing (`structured_pdf_extract.py`)

Uses `pdfminer-six` for per-line layout extraction and `pypdf` for page count. All dependencies are vendored — no pip install needed.

Output: a structured dict of `{pages: [{page_number, paragraphs: [{paragraph_id, text}]}]}`.

Each paragraph is a semantically coherent block of text as determined by pdfminer's layout analysis.

### 2. Regex extraction (`extract_references.py`)

Four compiled patterns cover the main reference types:

| Pattern | Matches | Example |
|---|---|---|
| `MASTER_CIRCULAR_RE` | Master circulars with a topic body and issue date | `Master Circular for Stock Brokers dated June 17, 2025` |
| `SEBI_CIRCULAR_RE` | Identifier-coded circulars | `SEBI Circular CIR/MIRSD/5/2013 dated August 27, 2013` |
| `FORMAL_INSTRUMENT_RE` | Acts and Regulations with a year | `SEBI (Custodian) Regulations, 1996` |
| `NOTIFICATION_RE` | Gazette notifications with a date | `notification dated January 14, 2026` |

Each match is sent to a `Registry` that deduplicates documents across all pages and assigns a stable `document_id`. When a full title is first seen with a parenthetical alias (e.g. `SEBI (Credit Rating Agencies) Regulations, 1999 (CRA Regulations)`), the alias is registered. Later mentions of just "CRA Regulations" are resolved back to the full record.

For each match the extractor also scans the preceding text for locator pointers — section numbers, regulation clauses, annexure references — and stores them in `target_locators`. This records not just *what* is referenced, but *where inside* the referenced document the circular is pointing.

### 3. AI discovery pass (`--use-ai`)

After regex extraction, if `--use-ai` is set, Gemini 2.5 Flash is called once per document.

The prompt includes:
- Full document text, page by page (paragraphs joined with spaces so cross-line fragments read as continuous text)
- The list of already-found regex records (so Gemini does not re-report them)
- Strict instructions: only return references explicitly in the text, copy titles verbatim, return an empty list if nothing was missed

Gemini returns structured JSON via `responseJsonSchema` constrained output (`temperature: 0.1` for near-deterministic results). Each returned reference includes `document_type`, `title`, `identifier`, `year_or_date`, `source_page`, `evidence_text`, and `exact_quote`.

Post-processing filters:
- Self-references dropped ("this circular", "present circular")
- Identifiers that are section/locator references (e.g. "Regulation 51") are cleared; if no title exists either, the record is dropped entirely
- Acts/regulations whose title doesn't contain the word "Act"/"Regulation" are dropped — guards against truncated PDF text producing unusable records
- AI-discovered notifications with no title are dropped — these are typically gazette notification numbers that appear as supporting metadata for a regulations citation, not standalone documents

Discovered records are tagged `title_source: ai_discovered` and merged into the registry like any other record.

### 4. Output

Each input PDF produces a `<stem>.references.json` containing:

- **`referenced_documents`** — deduplicated list of all referenced documents, each with: `document_id`, `document_type`, `title`, `short_title`, `identifier`, `date`, `year`, `issuing_body`, `aliases`, `title_source`, `resolution_status`, `resolved_url`
- **`reference_mentions`** — one entry per (document, source_page) pair: `source_page`, `evidence_text`, `match_texts`, `relation_type`, `target_locators`, `confidence`
- **`source_document`** — title, circular number, issue date extracted from the first page
- **`ai_discovery`** — whether AI was used and how many new references it found
- **`summary`** — document count, mention count, list of pages with references

---

## Evaluation methodology

The pipeline was developed against 5 hand-labelled ground truth fixtures. Each fixture specifies:

- `scored_references` — the documents the system must find, with canonical titles, official identifiers, and expected source pages
- `abstain_mentions` — specific text the system must *not* emit as a scored document (self-references, generic phrases, bare date-only notifications)

The scorer (`evals/evaluate.py`) matches predictions to gold via a three-step lookup: explicit `canonical_key` → normalised `official_identifier` → normalised `canonical_title`. Both sides are normalised (NFKD unicode, lowercase, non-alphanumeric stripped, "Securities and Exchange Board of India" collapsed to "sebi").

**Primary metrics:**

| Metric | Measures |
|---|---|
| `doc_f1` | Whether each unique referenced document was found |
| `page_f1` | Whether each (document, source_page) pair was found |
| `title_exact_recall` | Whether the predicted title normalises to the gold canonical |
| `type_accuracy` | Whether the document type is correct for matched docs |

### Improvement story

Starting from the initial extractor, running evals against the ground truth revealed four specific bugs. Each fix was driven by a concrete metric drop on a specific fixture, not by guesswork:

| Fix | Metric that revealed it | What changed |
|---|---|---|
| `FORMAL_INSTRUMENT_RE` missed singular "Regulation" | `cra_other_fsr_obligations` Doc F1 66.7% | Pattern changed `Regulations` → `Regulations?` |
| `infer_document_type` missed singular form | Same fixture, type accuracy for CRA doc | Changed to `re.search(r"\bregulations?\b", ...)` |
| Master circular title included trailing acronym | `ease_of_doing_investment_loc` Doc F1 80% | Strip trailing `("RTAs")` from body before building title |
| Bare date-only notifications emitted as predictions | `guidelines_for_custodians` Doc F1 85.7% | Skip `title_source: generic_only` notifications in adapter |
| Circular `short_title` missing date | Title exact recall low | Changed to `"SEBI Circular {id} dated {date}"` |

After these fixes the deterministic baseline reached **Doc F1 97.1%, Page F1 98.2%** (v3).

Adding the AI discovery pass resolved the remaining structural miss (cross-paragraph title split in stock_broker) and brought the final result to **Doc F1 100%, Page F1 100%** (v5).

---

## What the regex can't do (and why that's acceptable)

- **Scanned PDFs**: no text layer, extraction returns nothing. All development fixtures are native-text.
- **Deeply informal references**: "the aforesaid circular" or "our earlier communication" with no identifier. These require co-reference resolution across a much wider context window — out of scope for v1.
- **URL resolution**: SEBI URLs are not derivable from identifiers alone. The `--resolve-urls` flag makes a best-effort attempt using SEBI's listing API, but it's approximate for circulars and unavailable for notifications.

The AI discovery layer handles the first category of gaps (unusual patterns, non-hardcoded instruments) but not the latter two.
