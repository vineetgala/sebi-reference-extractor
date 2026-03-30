# Fixture Notes

These fixtures come from the PDFs already present in `pdfs/`.

This set is useful as a development set, not as a claim of broad generalization.

## Current fixture set

- `ease_of_doing_investment_loc`
  Strong test for a titled master circular plus multiple governing acts and regulations on a later page.

- `cra_other_fsr_obligations`
  Mostly regulation-heavy with repeated shorthand mentions like `CRA Regulations`.
  Useful for alias normalization and for abstaining on vague phrases such as `circulars issued in this regard`.

- `valuation_of_gold_and_silver`
  Short document with low reference count.
  Good for checking page attribution and avoiding over-extraction.

- `guidelines_for_custodians`
  Best stress fixture in the current set.
  Includes repeated shorthand references, identifier-only circular mentions, a titled master circular, and several abstention cases.

- `stock_broker_reporting_relaxations`
  Repeated master-circular references across pages plus governing acts and regulations in the closing authority paragraph.

## Dataset gaps

- Only 5 source PDFs.
- All 5 are native-text PDFs; no scanned or OCR-heavy documents.
- Heavy skew toward 2026 circulars and toward regulations/master circulars.
- Very limited coverage of confidently resolvable referenced-document URLs.
- Almost no ambiguous same-title or near-title collision cases.
- No holdout split yet.

## Best next additions

If you have time before submission, add 3 more fixtures with these traits:

- An older circular with several prior circular references by identifier only.
- A PDF where link resolution is easy and verifiable, so resolution precision/recall becomes meaningful.
- A more difficult extraction case with poor PDF text quality or unusual layout.

## Scoring conventions

- Source page numbers always refer to the input PDF page where the citation appears.
- Repeated mentions of the same referenced document on the same source page count once for page-level metrics.
- Internal references such as `this circular`, `Annexure-A of this Circular`, or paragraph references inside the current source PDF are not scored as external documents.
