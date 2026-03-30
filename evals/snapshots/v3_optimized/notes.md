# v3 Optimized — after eval-driven fixes

This snapshot captures the extractor **after** four targeted fixes applied in response to eval failures.

## Fixes applied (in order of discovery)

**Fix 1 — Singular/plural Regulations pattern**
`FORMAL_INSTRUMENT_RE` changed from `Regulations` to `Regulations?`. `infer_document_type` changed to use `re.search(r"\bregulations?\b", ...)`.
Effect: CRA fixture went from Doc F1 66.7% to 100%.

**Fix 2 — Master circular title acronym stripping**
`title_from_master_circular` strips trailing parenthetical acronyms (e.g. `("RTAs")`) from the body before building the display title.
Effect: `ease_of_doing_investment_loc` went from Doc F1 80% / Page F1 66.7% to 100% / 100%.

**Fix 3 — Notification precision filter**
`make_predictions.py` skips `document_type: notification` with `title_source: generic_only`. These are bare "Notification dated X" records with no stable identifier.
Effect: `guidelines_for_custodians` went from Doc F1 85.7% (2 FP notifications) to 100%.

**Fix 4 — Date included in circular short_title**
SEBI Circular `short_title` now appends `" dated {date}"` when a date was extracted.
Effect: Title exact recall for `guidelines_for_custodians` improved from 50% to 66.7%.

**Fix 5 — Singular Regulation title normalization**
After matching, `"Regulation,"` followed by a year is normalized to `"Regulations,"` in the title string.
Effect: CRA title exact recall went from 50% to 100%.

## Key metrics

| Metric | Value |
|---|---:|
| Doc Precision | 100.0% |
| Doc Recall | 95.0% |
| **Doc F1** | **97.1%** |
| Page Precision | 100.0% |
| Page Recall | 96.7% |
| **Page F1** | **98.2%** |
| Title Exact Recall | 88.3% |
| Title Presence Recall | 95.0% |
| Type Accuracy on Matched Docs | 100.0% |

## Remaining gaps documented in evals/RESULTS.md

- `stock_broker_reporting_relaxations`: SCCR Regulations, 2018 not found — year appears on a separate PDF paragraph from the title (cross-paragraph text split, architectural limitation)
- `guidelines_for_custodians`: title_exact_recall 66.7% — one circular date format mismatch (15 Dec vs December 15), one Banking Regulation Act singular/plural canonical mismatch
