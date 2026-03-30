# Eval Results

## Progression

Each row below is a real measured eval run.  Changes between runs are called out explicitly so the eval-driven improvement story is reproducible.

### v0 — deterministic extractor, initial state

**Snapshot:** `evals/snapshots/v0_baseline/`

Before any fixes, the extractor had four bugs the evals revealed:

1. `FORMAL_INSTRUMENT_RE` required plural `Regulations` — missed "SEBI (Credit Rating Agencies) **Regulation**, 1999" (singular in the PDF).
2. Master circular title captured trailing parenthetical acronym — "Master Circular for Registrars to an Issue and Share Transfer Agents (**"RTAs"**)" didn't match the gold canonical.
3. Bare date-only notification records (no stable title/identifier) emitted as scored predictions — lowered precision for `guidelines_for_custodians`.
4. SEBI Circular `short_title` did not include date — "SEBI Circular CIR/MIRSD/5/2013" didn't match gold canonical "SEBI Circular CIR/MIRSD/5/2013 dated August 27, 2013".

**Real measured metrics (reproduced from `evals/snapshots/v0_baseline/eval_results.md`):**

| Metric | Value |
|---|---:|
| Doc Precision | 91.0% |
| Doc Recall | 81.0% |
| Doc F1 | 83.6% |
| Page Precision | 90.0% |
| Page Recall | 74.0% |
| Page F1 | 76.4% |
| Title Exact Recall | 71.0% |
| Title Presence Recall | 81.0% |
| Type Accuracy on Matched Docs | 100.0% |

---

### v1 — after fix 1: FORMAL_INSTRUMENT_RE singular/plural + type inference

**What changed:** Added `s?` to the two SEBI Regulations patterns in `FORMAL_INSTRUMENT_RE` so singular "Regulation" is matched. Added `re.search(r"\bregulations?\b", ...)` to `infer_document_type` so singular-form titles get `document_type: regulations` instead of `other`.

**What the evals revealed:** `cra_other_fsr_obligations` had Doc F1 of 66.7% — SEBI (Credit Rating Agencies) Regulation, 1999 was missing entirely, along with all its alias back-matches (CRA Regulations) on pages 2, 3, 4.

| Fixture | Doc F1 | Page F1 | Title Exact Recall | Type Acc |
|---|---:|---:|---:|---:|
| cra_other_fsr_obligations | 100.0% | 100.0% | 50.0% | 100.0% |
| ease_of_doing_investment_loc | 80.0% | 66.7% | 80.0% | 100.0% |
| guidelines_for_custodians | 85.7% | 90.9% | 50.0% | 100.0% |
| stock_broker_reporting_relaxations | 85.7% | 80.0% | 75.0% | 100.0% |
| valuation_of_gold_and_silver | 100.0% | 100.0% | 100.0% | 100.0% |

| Metric | Value |
|---|---:|
| Doc Precision | 91.0% |
| Doc Recall | 91.0% |
| Doc F1 | 90.3% |
| Page Precision | 90.0% |
| Page Recall | 86.7% |
| Page F1 | 87.5% |
| Title Exact Recall | 71.0% |
| Title Presence Recall | 91.0% |
| Type Accuracy on Matched Docs | 100.0% |

---

### v2 — after fix 2: Master Circular generic alias + RTA title stripping

**What changed:** Re-added `"Master Circular"` as a registered alias (it had been removed in a prior branch, breaking page-2 alias matches). Stripped trailing parenthetical acronyms (e.g. `("RTAs")`) from master circular body text before building the display title.

**What the evals revealed:** `ease_of_doing_investment_loc` had Doc F1 80% and Page F1 66.7% — the RTA Master Circular was predicted with an extra `("RTAs")` suffix that prevented matching, and the page 2 alias mention for `stock_broker_reporting_relaxations` was being missed.

| Fixture | Doc F1 | Page F1 | Title Exact Recall | Type Acc |
|---|---:|---:|---:|---:|
| cra_other_fsr_obligations | 100.0% | 100.0% | 50.0% | 100.0% |
| ease_of_doing_investment_loc | 100.0% | 100.0% | 100.0% | 100.0% |
| guidelines_for_custodians | 85.7% | 90.9% | 50.0% | 100.0% |
| stock_broker_reporting_relaxations | 85.7% | 90.9% | 75.0% | 100.0% |
| valuation_of_gold_and_silver | 100.0% | 100.0% | 100.0% | 100.0% |

| Metric | Value |
|---|---:|
| Doc Precision | 95.0% |
| Doc Recall | 95.0% |
| Doc F1 | 94.3% |
| Page Precision | 96.7% |
| Page Recall | 96.7% |
| Page F1 | 96.4% |
| Title Exact Recall | 75.0% |
| Title Presence Recall | 95.0% |
| Type Accuracy on Matched Docs | 100.0% |

---

### v3 — after fix 3: notification filter + Regulation title normalization + date in circular short_title

**What changed:**
- Prediction adapter (`make_predictions.py`) skips `document_type: notification` records with `title_source: generic_only` — these are bare "Notification dated X" objects with no stable identifier, appropriate to abstain on.
- `FORMAL_INSTRUMENT_RE` usage site normalizes `"Regulation,"` → `"Regulations,"` in title when followed by a year, so extracted titles match the canonical form.
- SEBI Circular `short_title` now includes the date when present (e.g. `"SEBI Circular CIR/MIRSD/5/2013 dated August 27, 2013"`), matching the gold canonical format.

**What the evals revealed:** `guidelines_for_custodians` had Doc F1 85.7% due to 2 FP notification records in predictions. CRA title exact recall was 50% because "Regulation" (singular) didn't normalize to the canonical plural form.

| Fixture | Doc F1 | Page F1 | Title Exact Recall | Type Acc |
|---|---:|---:|---:|---:|
| cra_other_fsr_obligations | 100.0% | 100.0% | 100.0% | 100.0% |
| ease_of_doing_investment_loc | 100.0% | 100.0% | 100.0% | 100.0% |
| guidelines_for_custodians | 100.0% | 100.0% | 66.7% | 100.0% |
| stock_broker_reporting_relaxations | 85.7% | 90.9% | 75.0% | 100.0% |
| valuation_of_gold_and_silver | 100.0% | 100.0% | 100.0% | 100.0% |

| Metric | Value |
|---|---:|
| Doc Precision | 100.0% |
| Doc Recall | 95.0% |
| Doc F1 | 97.1% |
| Page Precision | 100.0% |
| Page Recall | 96.7% |
| Page F1 | 98.2% |
| Title Exact Recall | 88.3% |
| Title Presence Recall | 95.0% |
| Type Accuracy on Matched Docs | 100.0% |

This is the **current production baseline**.

**Snapshot:** `evals/snapshots/v3_optimized/`

---

### v4 — AI enrichment pass (gemini-2.5-flash)

**Snapshot:** `evals/snapshots/v4_ai_enriched/`

**What changed:** Ran the extractor with `--use-ai`. Gemini 2.5 Flash reviewed all identifier-only circular records (those where `title` is null) using up to 3 evidence snippets from the PDF. The prompt is strictly grounded: only extract a phrase that appears in the evidence, never invent.

**Candidates found:**

| Source PDF | Candidates | Changes |
|---|---:|---:|
| Guidelines for Custodians | 2 | 2 |
| All other PDFs | 0 | 0 |

Zero candidates in the other 4 PDFs — all their referenced documents already had explicit titles. The two enriched entries in `guidelines_for_custodians`:

| Identifier | descriptive_title added by AI |
|---|---|
| CIR/MIRSD/5/2013 dated Aug 27, 2013 | "general guidelines ... for dealing with conflict of interest" |
| CIR/MIRSD/24/2011 dated 15 Dec 2011 | "registered intermediaries including Custodians are allowed to outsource non-core activities" |

**Eval metrics: identical to v3.** The AI enrichment is purely additive — `descriptive_title` is a separate field; the eval adapter prefers `short_title` (identifier + date) for canonical matching. The improvement is in human-readable output quality, not structural correctness metrics.

**Qualitative improvement:** Without AI, `"SEBI Circular CIR/MIRSD/5/2013 dated August 27, 2013"` is opaque. With AI, a compliance officer sees the subject of that circular directly in the output — based solely on context in the current PDF, no hallucination.

---

## Remaining known gaps

| Gap | Affected fixture | Root cause | Fix path |
|---|---|---|---|
| SCCR Regulations, 2018 not found | stock_broker_reporting_relaxations | "Regulations, 2018" split across PDF paragraphs — title and year in separate paragraph blocks | Require cross-paragraph text joining in PDF parser (v2 work) |
| `CIR/MIRSD/24/2011` title exact miss | guidelines_for_custodians | Date in PDF is "15 Dec 2011"; gold canonical uses "December 15, 2011" | Month name normalization or gold alias update |
| Banking Regulation Act singular/plural | guidelines_for_custodians | PDF uses "Regulations Act" (plural), gold canonical is "Regulation Act" (singular, legally correct) | Title normalization lookup table (v2 work) |

---

## AI enrichment (optional pass, not yet run)

Run with:
```bash
export GEMINI_API_KEY=<your-key>
python3 agent-work/extract_references.py pdfs --use-ai
python3 evals/make_predictions.py
python3 evals/evaluate.py --gold-dir evals/ground_truth --pred-dir evals/predictions
```

The AI pass sends identifier-only circular records (those where `title` is null and only a bare `identifier + date` is known) to Gemini with surrounding evidence text.  Gemini is instructed to extract a `descriptive_title` only if a meaningful subject phrase appears in the evidence — it must not hallucinate an official title.

Expected impact:
- `title_presence_recall` may improve slightly if any circulars currently have no title at all (currently all have short_title populated, so impact here is minimal)
- Human-readable output quality improves significantly: `"SEBI Circular CIR/MIRSD/5/2013 dated August 27, 2013"` becomes something like `"SEBI Circular CIR/MIRSD/5/2013 — Risk Management Framework for Custodians"`
- `title_exact_recall` is unlikely to improve because the gold canonical format is `"identifier dated date"` while AI adds a subject phrase beyond that

The AI pass is additive: it never removes a document or changes its type or pages.  Its `descriptive_title` is stored separately from `title` and `short_title`, so the baseline extraction is always preserved.

---

## Dataset notes

This 5-document eval set is a **development set**, not a generalization claim.  All 5 PDFs are:
- Native-text (not scanned/OCR)
- Recent 2026 circulars
- Heavy on Regulations and Master Circular references
- No ambiguous same-title collision cases
- No covered resolved URLs (resolution metrics are n/a throughout)

For v2, prioritise adding: an older circular with many identifier-only references, a PDF where at least one URL can be verified, and a document with degraded PDF text to test OCR robustness.
