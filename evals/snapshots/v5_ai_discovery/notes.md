# v5 — AI discovery pass (gemini-2.5-flash, temperature 0.1)

## What changed

Replaced the previous enrichment-only AI pass (which only added `descriptive_title` to
already-found identifier-only circulars) with a **discovery pass** that scans the full
document text for references the regex extractor missed.

Key implementation decisions:
- Full document text is sent to Gemini page-by-page (paragraphs within a page joined with
  a space, not newline, so cross-paragraph title fragments are read as continuous text)
- Already-found regex records are listed in the prompt so Gemini does not re-report them
- `temperature: 0.1` for near-deterministic output
- Three post-processing filters in `apply_ai_discoveries`:
  1. Skip self-references ("this circular", "present circular")
  2. If identifier looks like a section/locator reference (starts with "Section",
     "Regulation", "Para", etc.): clear the identifier if a title exists; skip entirely
     if no title either
  3. Skip acts/regulations whose title doesn't contain the word "Act"/"Regulation" —
     guards against truncated PDF text creating unusable records
- In `make_predictions.py`: skip AI-discovered notifications with no title (these are
  gazette notification numbers that serve as supporting metadata for a regulations
  mention, not standalone scoreable documents)

## The known miss this fixes

`Securities Contracts (Regulation) (Stock Exchanges and Clearing Corporations)
Regulations, 2018` in `stock_broker_reporting_relaxations`: the PDF splits the title
across two paragraph blocks ("Regulations," ends one paragraph, "2018." starts the next).
The regex processes each paragraph individually and never sees the complete title+year.
Gemini receives the full joined page text and correctly identifies the complete reference.

## Eval results

| Fixture | Doc F1 | Page F1 | Title Exact Recall | Type Acc |
|---|---:|---:|---:|---:|
| cra_other_fsr_obligations | 100.0% | 100.0% | 100.0% | 100.0% |
| ease_of_doing_investment_loc | 100.0% | 100.0% | 100.0% | 100.0% |
| guidelines_for_custodians | 100.0% | 100.0% | 66.7% | 100.0% |
| stock_broker_reporting_relaxations | 100.0% | 100.0% | 100.0% | 100.0% |
| valuation_of_gold_and_silver | 100.0% | 100.0% | 100.0% | 100.0% |

**Macro:** Doc F1 100.0% · Page F1 100.0% · Title Exact 93.3% · Doc Precision 100% · Type Accuracy 100%

## Comparison to previous best (v3)

| Metric | v3 | v5 | Δ |
|---|---:|---:|---:|
| Doc F1 | 97.1% | 100.0% | +2.9pp |
| Page F1 | 98.2% | 100.0% | +1.8pp |
| Title Exact Recall | 88.3% | 93.3% | +5.0pp |
| Doc Precision | 100.0% | 100.0% | — |
| Doc Recall | 95.0% | 100.0% | +5.0pp |
