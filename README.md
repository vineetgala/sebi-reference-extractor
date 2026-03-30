# SEBI Reference Extractor

An agent that takes a SEBI circular PDF as input and extracts all references to other documents — other circulars, master circulars, regulations, acts, and notifications — along with their titles and the source page numbers where each reference appears.

Built for the Hyde AI take-home assignment.

---

## What it does

For each input PDF the agent produces a structured JSON file containing:

- **`referenced_documents`** — deduplicated list of every external document found, with title, identifier, date, type, issuing body, and known aliases
- **`reference_mentions`** — every individual mention in the PDF, with source page, evidence text, relation type (e.g. `relies_on`, `amends_or_modifies`), and locator detail (e.g. "Regulation 9(f)")
- **`source_document`** — extracted metadata for the input circular (title, circular number, issue date)
- **Optional AI enrichment** — Gemini pass that adds human-readable `descriptive_title` to identifier-only circular records using only the surrounding evidence text

---

## Setup

**Python 3.10+** required. All PDF dependencies are vendored under `agent-work/vendor/` — no pip install needed for extraction.

For the optional AI enrichment step, set a Gemini API key:
```bash
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

# With Gemini AI enrichment for identifier-only circulars (requires API key)
python3 agent-work/extract_references.py pdfs/ --use-ai

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

## Current eval results (deterministic baseline)

| Fixture | Doc F1 | Page F1 | Title Exact Recall | Type Acc |
|---|---:|---:|---:|---:|
| cra_other_fsr_obligations | 100.0% | 100.0% | 100.0% | 100.0% |
| ease_of_doing_investment_loc | 100.0% | 100.0% | 100.0% | 100.0% |
| guidelines_for_custodians | 100.0% | 100.0% | 66.7% | 100.0% |
| stock_broker_reporting_relaxations | 85.7% | 90.9% | 75.0% | 100.0% |
| valuation_of_gold_and_silver | 100.0% | 100.0% | 100.0% | 100.0% |

**Macro:** Doc F1 97.1% · Page F1 98.2% · Title Exact Recall 88.3% · Doc Precision 100% · Type Accuracy 100%

See [`evals/RESULTS.md`](evals/RESULTS.md) for the full progression table showing how eval-driven fixes improved scores from ~83% Doc F1 to 97%.

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

5. **AI enrichment (optional)** — Gemini is called with evidence snippets for any circular that has only an identifier and date (no explicit title in the text). The prompt instructs the model to extract a phrase only if one appears in the evidence — not to invent an official title. The result is stored as `descriptive_title` separately from the deterministic `title` and `short_title` fields.

---

## Design decisions

- **Precision over recall**: bare date-only notifications and generic phrases like "circulars issued in this regard" are excluded from predictions. Unresolved references are acceptable; false confident matches are not.
- **Alias resolution is registry-based, not LLM-based**: once a full title is seen, its shorthand aliases are registered deterministically and used for all subsequent pages.
- **AI is additive**: it only enriches records that the deterministic layer already found. It never creates new document records or changes pages, types, or identifiers.
- **Page numbers refer to the source PDF**: all `source_page` values are the page in the input circular where the reference appears, not pages in the referenced document.

---

## Known limitations (v1)

- **Cross-paragraph text splits**: when a document title and its year appear in different PDF paragraphs (a line-wrapping artifact), the extractor misses them. Example: `Securities Contracts (Regulation) (Stock Exchanges and Clearing Corporations) Regulations, 2018` in the stock broker circular.
- **Scanned/OCR PDFs not supported**: the pipeline requires native text-layer PDFs. All 5 development fixtures are native-text.
- **No URL resolution**: the agent does not attempt to resolve a SEBI.gov.in URL for referenced documents. The identifier + date is sufficient to locate them manually, but automated resolution requires metadata matching against the SEBI circular index.
- **Single-PDF scope**: the agent processes one PDF at a time. Building a full knowledge graph would require running across all SEBI circulars and cross-linking by shared document references.

---

## v2 ideas (scaling to a knowledge graph)

1. **Batch extraction across all SEBI circulars**: run the agent on the full SEBI circular archive (~thousands of PDFs), writing one JSON per source document.
2. **Cross-document deduplication**: merge documents that appear in multiple source circulars using canonical key matching (identifier, normalized title + year).
3. **URL resolution**: build a metadata index from SEBI's listing pages and match by identifier / date / topic to produce verified `resolved_url` values.
4. **Graph export**: export the merged registry as a knowledge graph (nodes = documents, edges = reference relationships with type, source page, and locator detail).
5. **Query interface**: allow a compliance officer to ask "which circulars reference SEBI (Custodian) Regulations, 1996, Regulation 13?" and get a list of source circulars with page evidence.
