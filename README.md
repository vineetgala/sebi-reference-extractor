# SEBI Reference Extractor

An agent that takes a SEBI circular PDF as input and extracts all references to other documents — other circulars, master circulars, regulations, acts, and notifications — along with their titles and the source page numbers where each reference appears.

Built for the Hyde AI take-home assignment.

---

## What it does

For each input PDF the agent produces a structured JSON file containing:

- **`referenced_documents`** — deduplicated list of every external document found, with title, identifier, date, type, issuing body, and known aliases
- **`reference_mentions`** — every individual mention in the PDF, with source page, evidence text, relation type (e.g. `relies_on`, `amends_or_modifies`), and locator detail (e.g. "Regulation 9(f)")
- **`source_document`** — extracted metadata for the input circular (title, circular number, issue date)
- **Optional AI discovery** — Gemini pass that finds references the regex extractor missed (cross-paragraph title splits, acts not in the hardcoded pattern list, non-standard phrasing); tagged `title_source: ai_discovered` in the output

---

## Setup

**Python 3.10+** required. All PDF dependencies are vendored under `agent-work/vendor/` — no pip install needed for deterministic extraction.

For the optional AI discovery step, install the official Gemini SDK and set a Gemini API key:
```bash
pip install google-genai
export GEMINI_API_KEY=<your-key>
# or
export GOOGLE_API_KEY=<your-key>
```

---

## Run the extractor

```bash
# Single PDF
python3 agent-work/extract_references.py path/to/circular.pdf

# Directory of PDFs
python3 agent-work/extract_references.py pdfs/

# With Gemini AI discovery — finds references regex missed (requires API key)
python3 agent-work/extract_references.py pdfs/ --use-ai

# With URL resolution — attempts to find sebi.gov.in listing URLs for each referenced document
python3 agent-work/extract_references.py pdfs/ --resolve-urls

# AI discovery + URL resolution
python3 agent-work/extract_references.py pdfs/ --use-ai --resolve-urls

# Custom output directory
python3 agent-work/extract_references.py pdfs/ --output-dir my-output/
```

Output files are written as `<stem>.references.json` in `reference-output/` (or the directory you specify).

---

## Run the evals

The eval pipeline has three steps: extract → adapt → score.

```bash
# Step 1: extract references from the 5 development PDFs
python3 agent-work/extract_references.py pdfs/

# Step 2: convert extractor output to eval prediction format
python3 evals/make_predictions.py

# Step 3: score predictions against ground truth
python3 evals/evaluate.py --gold-dir evals/ground_truth --pred-dir evals/predictions

# JSON output instead of markdown table
python3 evals/evaluate.py --gold-dir evals/ground_truth --pred-dir evals/predictions --format json
```

For the AI-enriched comparison:
```bash
python3 agent-work/extract_references.py pdfs/ --use-ai
python3 evals/make_predictions.py
python3 evals/evaluate.py --gold-dir evals/ground_truth --pred-dir evals/predictions
```

---

## API Server

A FastAPI server that exposes the extraction pipeline as a REST endpoint with auto-generated Swagger docs.

```bash
pip install -r api/requirements.txt
uvicorn api.server:app --reload --port 8000
```

| URL | Description |
|---|---|
| `POST /extract` | Submit a URL (SEBI webpage or direct PDF), get the full reference JSON back |
| `GET /docs` | Swagger UI — interactive API explorer |
| `GET /redoc` | ReDoc documentation |
| `GET /health` | Health check |

**Query parameters on `POST /extract`:**
- `use_ai` (bool, default `false`) — enable Gemini discovery pass to find references regex missed
- `gemini_model` (string, default `gemini-2.5-flash`) — model to use when `use_ai=true`
- `resolve_urls` (bool, default `false`) — attempt to find sebi.gov.in listing URLs for each referenced document

Requires a `GEMINI_API_KEY` in `.env` only when `use_ai=true`. The deterministic extractor has no external dependencies beyond the vendored PDF libraries; the optional AI pass uses the official `google-genai` SDK.

---

## Reference Viewer

An interactive browser-based viewer with two modes:

**Extract New tab (default)** — paste any SEBI circular webpage URL or direct PDF URL, give it an optional name, and click Extract. The viewer calls the local FastAPI server, runs the extraction pipeline, and renders results immediately. Previously extracted documents in the session are kept as clickable chips so you can switch between them without re-extracting.

**Golden Dataset tab** — browse the 5 pre-analysed circulars from this project, loaded from the pre-computed `reference-output/` JSON files. Full document text is available in this mode.

Both modes render identically: paragraphs with references are shown with inline highlights colour-coded by document type. Hovering a highlight shows a tooltip with title, issuer, date, identifier, relation type, locators (section/para/annexure pointers), and a confidence bar. Clicking a document in the sidebar scrolls to its first mention.

```bash
# Both servers must be running for "Extract New" to work:
python3 viewer/serve.py                           # viewer on port 7890
uvicorn api.server:app --reload --port 8000       # API on port 8000

# Then open:
# http://localhost:7890/viewer/
```

No build step. No frontend dependencies. The viewer server requires only the Python standard library.

---

## Current eval results (deterministic + URL resolution)

| Fixture | Doc F1 | Page F1 | Title Exact Recall | Type Acc | URL Resolution Rate |
|---|---:|---:|---:|---:|---:|
| cra_other_fsr_obligations | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| ease_of_doing_investment_loc | 100.0% | 100.0% | 100.0% | 100.0% | 60.0% |
| guidelines_for_custodians | 100.0% | 100.0% | 66.7% | 100.0% | 66.7% |
| stock_broker_reporting_relaxations | 85.7% | 90.9% | 75.0% | 100.0% | 66.7% |
| valuation_of_gold_and_silver | 100.0% | 100.0% | 100.0% | 100.0% | 50.0% |

**Macro (with `--use-ai`):** Doc F1 100% · Page F1 100% · Title Exact Recall 93.3% · Doc Precision 100% · Type Accuracy 100%

**Deterministic baseline (no AI):** Doc F1 97.1% · Page F1 98.2% · URL Resolution Rate 68.7%

URL Resolution Rate = documents the system resolved a sebi.gov.in URL for / total documents predicted. Acts and Regulations resolve reliably; circulars depend on date uniqueness; notifications are not resolvable.

See [`evals/RESULTS.md`](evals/RESULTS.md) for the full progression table showing how eval-driven fixes improved scores from 83% → 97% (regex) → 100% (regex + AI discovery).

---

## Repo layout

```
agent-work/
  extract_references.py      # main extraction agent
  structured_pdf_extract.py  # PDF layout parser (pdfminer + pypdf)
  vendor/                    # vendored pdfminer-six, pypdf, cryptography

pdfs/                        # 5 SEBI circular PDFs used for development

reference-output/            # extraction outputs (one JSON per PDF)

evals/
  evaluate.py                # scorer: doc F1, page F1, title recall, type accuracy
  make_predictions.py        # adapts extractor output → scorer input format
  ground_truth/              # 5 hand-labelled ground truth fixtures
  fixtures/README.md         # fixture notes and dataset gaps
  predictions/               # generated prediction files (gitignored)
  RESULTS.md                 # full eval progression and known gaps

manifest.json                # source PDF metadata (URLs, paths, sizes)

viewer/
  index.html               # general-purpose reference viewer — "Extract New" tab calls
                           # the API on port 8000; "Golden Dataset" tab loads pre-computed JSONs
  serve.py                 # minimal stdlib HTTP server; serves project root so paths resolve

api/
  server.py                # FastAPI server — POST /extract, Swagger at /docs
  requirements.txt         # fastapi, uvicorn, python-multipart
```

---

## Architecture

The extraction pipeline is **deterministic-first with optional AI review**.

1. **PDF parsing** (`structured_pdf_extract.py`) — pdfminer extracts per-page, per-line layout; pypdf provides page count and metadata. Output is a structured dict of pages → paragraphs.

2. **Regex extraction** — four compiled patterns cover the main reference types found in SEBI circulars:
   - `MASTER_CIRCULAR_RE` — master circulars with topic and date
   - `SEBI_CIRCULAR_RE` — identifier-coded circulars (`CIR/XXX/YYY/ZZZZ`)
   - `FORMAL_INSTRUMENT_RE` — Acts and Regulations with year
   - `NOTIFICATION_RE` — gazette notifications with date

3. **Registry + alias tracking** — a `Registry` deduplicates documents across pages and tracks short-form aliases (e.g. "CRA Regulations" → SEBI (Credit Rating Agencies) Regulations, 1999). After an explicit full-form mention is registered, subsequent shorthand mentions on later pages are resolved automatically.

4. **Locator extraction** — preceding text is scanned for section, paragraph, regulation, and annexure references so the output records *where* inside a referenced document the circular is pointing (e.g. "para 5", "Regulation 13", "Chapter III").

5. **AI discovery (optional)** — Gemini is called with the full document text (paragraphs joined per page so cross-paragraph title fragments are continuous) and the list of already-found regex records. Gemini returns any additional references it finds that regex missed — acts not in the hardcoded list, regulations with split titles, non-standard phrasing. Results are tagged `title_source: ai_discovered` and merged into the registry alongside regex findings.

---

## Design decisions

- **Precision over recall**: bare date-only notifications and generic phrases like "circulars issued in this regard" are excluded from predictions. Unresolved references are acceptable; false confident matches are not.
- **Alias resolution is registry-based, not LLM-based**: once a full title is seen, its shorthand aliases are registered deterministically and used for all subsequent pages.
- **AI is a second layer, not a replacement**: regex handles the well-defined common cases (identifiers, known instrument names, master circulars). AI discovery catches the long tail — references that don't fit a clean pattern. AI never modifies regex-found records.
- **Page numbers refer to the source PDF**: all `source_page` values are the page in the input circular where the reference appears, not pages in the referenced document.

---

## Known limitations (v1)

- **Cross-paragraph text splits**: the regex extractor processes each paragraph individually, so references whose title and year land in separate paragraph blocks are missed by regex alone. The `--use-ai` discovery pass handles these by reading the full joined page text.
- **Scanned/OCR PDFs not supported**: the pipeline requires native text-layer PDFs. All 5 development fixtures are native-text.
- **URL resolution is best-effort**: `--resolve-urls` uses SEBI's AJAX listing API with title/date matching. Acts and regulations resolve reliably; circulars depend on having a descriptive title or a unique date. Notifications are not resolvable (date-only, no identifier).
- **Single-PDF scope**: the agent processes one PDF at a time. Building a full knowledge graph would require running across all SEBI circulars and cross-linking by shared document references.

---

## v2 ideas (scaling to a knowledge graph)

1. **Batch extraction across all SEBI circulars**: run the agent on the full SEBI circular archive (~thousands of PDFs), writing one JSON per source document.
2. **Cross-document deduplication**: merge documents that appear in multiple source circulars using canonical key matching (identifier, normalized title + year).
3. **URL resolution (partial)**: `--resolve-urls` already resolves acts, regulations, master circulars, and date-matchable circulars. A full solution would build a local metadata index of all SEBI listing pages for offline, zero-latency matching.
4. **Graph export**: export the merged registry as a knowledge graph (nodes = documents, edges = reference relationships with type, source page, and locator detail).
5. **Query interface**: allow a compliance officer to ask "which circulars reference SEBI (Custodian) Regulations, 1996, Regulation 13?" and get a list of source circulars with page evidence.
