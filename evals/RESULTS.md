# Eval Results

## Current Assessment

This workspace did not contain a committed reference-extraction eval harness or scored prediction outputs.

What now exists:

- Hand-checked gold labels for the 5 PDFs currently in the workspace
- Explicit abstention cases so precision-first behavior is visible
- A scorer that separates document finding from source-page accuracy

## What to report in the submission

Use a table like this for each iteration:

| System | Doc P | Doc R | Doc F1 | Page P | Page R | Page F1 | Title Exact Recall | Title Presence Recall | Type Acc on Matched | Resolution P | Resolution R |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Baseline |  |  |  |  |  |  |  |  |  |  |  |
| Improved |  |  |  |  |  |  |  |  |  |  |  |

## Cleanest Before vs After Story

The most credible story for this assignment is:

1. Baseline
   Extract raw reference-like text, but allow duplicate mentions, miss shorthand aliases, and over-predict vague references.

2. Improvement
   Add page-aware deduplication, alias normalization, title cleanup, and abstention rules for vague or self-referential mentions.

3. Optional second improvement
   Add URL resolution only when identifier, title, and date agree strongly enough to preserve near-perfect resolution precision.

## What should move after the improvement

- `doc_precision` should rise because vague mentions and internal references stop being emitted as external documents.
- `page_f1` should rise because repeated mentions are normalized and attached to the right source pages.
- `title_exact_recall` should rise because shorthand mentions are normalized to stable titles.
- `resolution_precision` should stay very high, even if `resolution_recall` stays modest.

## Notes for the final write-up

- Treat this 5-document set as a development set, not a claim of full SEBI coverage.
- Show at least one per-fixture example where the baseline over-extracted or mis-normalized a reference and the improved system fixed it.
- If you add a blind holdout set later, keep this table format and report the same metrics there too.
