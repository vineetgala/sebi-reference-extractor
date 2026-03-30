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

| Fixture | Doc F1 | Page F1 | Title Exact Recall | Type Acc | URL Resolution Rate |
|---|---:|---:|---:|---:|---:|
| cra_other_fsr_obligations | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| ease_of_doing_investment_loc | 100.0% | 100.0% | 100.0% | 100.0% | 60.0% |
| guidelines_for_custodians | 100.0% | 100.0% | 66.7% | 100.0% | 66.7% |
| stock_broker_reporting_relaxations | 85.7% | 90.9% | 75.0% | 100.0% | 66.7% |
| valuation_of_gold_and_silver | 100.0% | 100.0% | 100.0% | 100.0% | 50.0% |

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
| URL Resolution Rate | 68.7% |

This is the **current production baseline**.

**Snapshot:** `evals/snapshots/v3_optimized/`

---

### v5 — AI discovery pass (gemini-2.5-flash, temperature 0.1)

**Snapshot:** `evals/snapshots/v5_ai_discovery/`

**What changed:** Replaced the previous enrichment-only AI pass with an **AI discovery pass** that reads the full document text and finds references the regex extractor missed.

The approach:
- All paragraph text is joined per page (with spaces, not newlines, so cross-paragraph title fragments appear continuous)
- Already-found regex records are provided to Gemini to avoid re-reporting
- Gemini returns structured JSON: `document_type`, `title`, `identifier`, `year_or_date`, `source_page`, `evidence_text`, `exact_quote`
- `temperature: 0.1` for near-deterministic output
- Post-processing filters: self-references dropped; locator references in the identifier field cleared; truncated act titles (no "Act" keyword) dropped; AI-discovered notifications with no title dropped (gazette IDs that are metadata for a regulations mention, not standalone documents)

**What AI found (per PDF):**

| Source PDF | Discovered |
|---|---:|
| stock_broker_reporting_relaxations | 1 — SCCR Regulations, 2018 |
| All other PDFs | 0 |

**Why SCCR was previously missed:** The PDF splits "Regulations," and "2018." across two paragraph blocks. The regex processes each paragraph individually and never sees the full title+year. Gemini receives the joined page text and correctly identifies the complete reference.

URL Resolution Rate was not measured for this snapshot (run predates `--resolve-urls`). See v3 for current resolution numbers.

| Fixture | Doc F1 | Page F1 | Title Exact Recall | Type Acc |
|---|---:|---:|---:|---:|
| cra_other_fsr_obligations | 100.0% | 100.0% | 100.0% | 100.0% |
| ease_of_doing_investment_loc | 100.0% | 100.0% | 100.0% | 100.0% |
| guidelines_for_custodians | 100.0% | 100.0% | 66.7% | 100.0% |
| stock_broker_reporting_relaxations | 100.0% | 100.0% | 100.0% | 100.0% |
| valuation_of_gold_and_silver | 100.0% | 100.0% | 100.0% | 100.0% |

| Metric | Value |
|---|---:|
| Doc Precision | 100.0% |
| Doc Recall | 100.0% |
| Doc F1 | 100.0% |
| Page Precision | 100.0% |
| Page Recall | 100.0% |
| Page F1 | 100.0% |
| Title Exact Recall | 93.3% |
| Title Presence Recall | 100.0% |
| Type Accuracy on Matched Docs | 100.0% |

This is the **current production baseline**.

---

## Remaining known gaps

| Gap | Affected fixture | Root cause | Fix path |
|---|---|---|---|
| `CIR/MIRSD/24/2011` title exact miss | guidelines_for_custodians | Date in PDF is "15 Dec 2011"; gold canonical uses "December 15, 2011" | Month name normalization or gold alias update |
| Banking Regulation Act singular/plural | guidelines_for_custodians | PDF uses "Regulations Act" (plural), gold canonical is "Regulation Act" (singular, legally correct) | Title normalization lookup table (v2 work) |

---

## Dataset notes

This 5-document eval set is a **development set**, not a generalization claim.  All 5 PDFs are:
- Native-text (not scanned/OCR)
- Recent 2026 circulars
- Heavy on Regulations and Master Circular references
- No ambiguous same-title collision cases
- URL Resolution Rate measured on deterministic baseline (v3): 68.7% macro average. Acts and Regulations resolve reliably; circulars depend on date uniqueness; notifications are not resolvable.

For v2, prioritise adding: an older circular with many identifier-only references, a PDF where at least one URL can be verified, and a document with degraded PDF text to test OCR robustness.
