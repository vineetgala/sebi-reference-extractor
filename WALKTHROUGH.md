# SEBI Reference Extractor — Walkthrough

---

## 1. Models, Tools & APIs

| Layer | What | Why |
|---|---|---|
| **PDF parsing** | pdfminer-six + pypdf (vendored, no pip) | Per-line layout extraction with font/position metadata |
| **Deterministic extraction** | 4 compiled regex patterns + Registry | Fast, free, 100% precision, fully reproducible |
| **AI discovery** | Gemini 2.5 Flash (`temperature: 0.1`, structured JSON output) | Catches cross-paragraph splits, non-standard phrasing, acts not in regex patterns |
| **API server** | FastAPI (POST /extract) | Accepts any SEBI URL, returns structured JSON |
| **Viewer** | Pure HTML/CSS/JS (no build step) | Interactive browser UI with inline highlights, tooltips, sidebar |
| **Evaluation** | Custom scorer (Python) — doc F1, page F1, title recall, type accuracy | 5 hand-labelled ground truth fixtures |
| **Agent tooling** | Claude Code (Opus / Sonnet) | Built the full pipeline, evals, viewer, and API |

---

## 2. Architecture

```
                         INPUT
                           |
                     PDF file or URL
                           |
                    ┌──────▼──────┐
                    │  PDF Parser  │   pdfminer + pypdf
                    │  page-aware  │   → pages → paragraphs → text
                    └──────┬──────┘
                           |
               ┌───────────▼───────────┐
               │   Regex Extraction    │   4 patterns, per-paragraph
               │                       │
               │  Master Circulars     │   "Master Circular for X dated Y"
               │  SEBI Circulars       │   "SEBI Circular CIR/XX/YY/ZZ"
               │  Acts & Regulations   │   "SEBI (Name) Regulations, Year"
               │  Notifications        │   "notification dated Month DD, YYYY"
               │                       │
               │  + alias tracking     │   "(CRA Regulations)" → full title
               │  + locator parsing    │   "Regulation 9(f)", "Annexure-7"
               └───────────┬───────────┘
                           |
                    ┌──────▼──────┐
                    │  Registry   │   deduplicates across all pages
                    └──────┬──────┘
                           |
              ┌────────────▼────────────┐
              │  AI Discovery (optional) │   Gemini 2.5 Flash
              │                          │
              │  full page text joined   │   sees cross-paragraph titles
              │  already-found refs      │   only returns NEW discoveries
              │  structured JSON output  │   title, type, page, evidence
              │  post-processing filters │   drop self-refs, locators, truncated
              └────────────┬────────────┘
                           |
                    ┌──────▼──────┐
                    │   OUTPUT    │   structured JSON
                    └─────────────┘

              referenced_documents (deduplicated)
              reference_mentions   (per-page, with context)
              source_document      (circular metadata)
              ai_discovery         (what AI found)
```

---

## 3. Evaluation-Driven Development

### Ground truth

5 hand-labelled SEBI circulars. Each fixture specifies:
- **scored_references** — what the system must find (canonical title, identifier, expected pages)
- **abstain_mentions** — what the system must NOT emit (self-references, generic phrases)

### Metrics

| Metric | Measures |
|---|---|
| **Doc F1** | Did we find each unique referenced document? |
| **Page F1** | Did we find each (document, page) pair? |
| **Title Exact Recall** | Does the predicted title match the canonical? |
| **Type Accuracy** | Is the document type correct for matched docs? |

### Improvement story

Every fix was driven by a specific metric drop on a specific fixture:

```
v0 baseline         ███████████████████████░░░░░░   Doc F1  83.6%
                     ██████████████████████░░░░░░░   Page F1 76.4%

    Fix 1: "Regulation" → "Regulations?"       (cra fixture Doc F1 was 66.7%)
    Fix 2: type inference for singular form     (cra type accuracy)
    Fix 3: strip trailing acronym from MC title (ease_of_doing Doc F1 was 80%)
    Fix 4: filter bare date-only notifications  (custodians Doc F1 was 85.7%)
    Fix 5: add date to circular short_title     (title recall was low)

v3 optimized         █████████████████████████████░  Doc F1  97.1%
                     ██████████████████████████████  Page F1 98.2%

    Fix 6: AI discovery pass (Gemini 2.5 Flash)

v5 final             ██████████████████████████████  Doc F1  100%
                     ██████████████████████████████  Page F1 100%
```

| Snapshot | Doc F1 | Page F1 | Title Exact | Precision |
|---|---:|---:|---:|---:|
| **v0** baseline | 83.6% | 76.4% | 71.0% | 91.0% |
| **v3** eval-driven fixes | 97.1% | 98.2% | 88.3% | 100.0% |
| **v5** + AI discovery | **100.0%** | **100.0%** | 93.3% | 100.0% |

---

## 4. Limitations (v2 priorities)

| Limitation | Impact | v2 Fix |
|---|---|---|
| **Cross-paragraph title splits** | Regex misses titles wrapped across line breaks (e.g. "Regulations,\n2018") | Paragraph merge pass before regex — partially implemented for date splits |
| **Scanned/OCR PDFs** | No text layer = no extraction | Add OCR preprocessing (Tesseract or cloud OCR) |
| **Informal co-references** | "the aforesaid circular", "our earlier communication" — no identifier | Co-reference resolution with LLM context window |
| **URL resolution is approximate** | SEBI URLs not derivable from identifiers alone | Build a local metadata index of all SEBI listing pages |
| **Title normalization gaps** | Date format mismatches ("15 Dec" vs "December 15"), singular/plural ("Regulation" vs "Regulations") | Fuzzy title matching in scorer |

---

## 5. Scaling to a Knowledge Graph

```
                    ┌─────────────────────────┐
                    │   SEBI Circular Archive  │
                    │   ~5,000+ PDFs           │
                    └────────────┬────────────┘
                                 |
                          batch extraction
                          (parallelize across PDFs)
                                 |
                    ┌────────────▼────────────┐
                    │  Per-PDF Reference JSON  │
                    │  one file per circular    │
                    └────────────┬────────────┘
                                 |
                       cross-document dedup
                       (canonical key matching)
                                 |
                    ┌────────────▼────────────┐
                    │    Unified Registry      │
                    │                          │
                    │  Nodes = documents       │
                    │    (circulars, acts,      │
                    │     regulations, MCs)     │
                    │                          │
                    │  Edges = references       │
                    │    (type, page, locator,  │
                    │     evidence text)        │
                    └────────────┬────────────┘
                                 |
                         ┌───────┴───────┐
                         |               |
                    ┌────▼────┐    ┌─────▼─────┐
                    │  Graph  │    │  Query     │
                    │  Export │    │  Interface │
                    │ Neo4j / │    │            │
                    │ Neptune │    │ "Which circulars
                    │         │    │  reference Reg 13
                    └─────────┘    │  of Custodian
                                   │  Regulations?"
                                   └───────────┘
```

### What it enables

| Capability | Value for compliance |
|---|---|
| **Dependency tracing** | "Circular X relies on Regulation Y, Section 13" — full chain |
| **Impact analysis** | When a regulation is amended, find every circular that references it |
| **Temporal view** | See how references to a specific act evolve across years of circulars |
| **Gap detection** | Find circulars that reference documents with no inbound references (orphans) |
| **Compliance mapping** | Map each business activity to the full tree of applicable regulations and circulars |

### Technical scaling notes

- Current extraction: ~3 seconds per PDF (deterministic), ~8 seconds with AI
- 5,000 PDFs at 8s each = ~11 hours sequential, ~1 hour with 10x parallelism
- Gemini free tier (500 req/day) sufficient for ~60 PDFs/day; paid tier removes limits
- Cross-document dedup uses the same canonical key matching as the eval scorer
- Graph storage: each node ≈ 200 bytes metadata, each edge ≈ 500 bytes with locators
- 5,000 circulars × ~8 references each = ~40,000 edges — fits comfortably in any graph DB
