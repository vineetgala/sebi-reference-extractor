# v4 AI Enriched — gemini-2.5-flash descriptive title pass

This snapshot adds an optional Gemini AI review pass on top of the v3 deterministic baseline.

## What the AI pass does

After deterministic extraction, any circular or notification record that has only an identifier + date (no explicit title in the text) is sent to Gemini with up to 3 evidence snippets from the PDF.

The prompt instructs the model to:
- Extract a `descriptive_title` only if an identifying phrase appears in the evidence
- Never invent an official title
- Return `descriptive_title: null` if the evidence only has an identifier and date

Results from this run:

| Source PDF | Candidates sent | Changes applied |
|---|---|---|
| Guidelines for Custodians | 2 | 2 |
| All others | 0 | 0 |

The two enriched circulars in `guidelines_for_custodians`:

| Identifier | descriptive_title added |
|---|---|
| CIR/MIRSD/5/2013 dated Aug 27, 2013 | "general guidelines ... for dealing with conflict of interest" |
| CIR/MIRSD/24/2011 dated 15 Dec 2011 | "registered intermediaries including Custodians are allowed to outsource non-core activities" |

Zero candidates in the other 4 PDFs — all their referenced documents already had explicit titles (Acts, Regulations, Master Circulars with named topics and dates).

## Eval metrics — same as v3

Structural eval metrics (Doc F1, Page F1, title exact recall) are identical to v3.  The AI enrichment is purely additive: `descriptive_title` is stored as a separate field from `title` and `short_title`.  The eval adapter uses `short_title` (identifier + date) as the canonical title for matching, so AI enrichment does not affect the eval scores.

| Metric | v3 | v4 (AI) | Δ |
|---|---:|---:|---:|
| Doc F1 | 97.1% | 97.1% | 0 |
| Page F1 | 98.2% | 98.2% | 0 |
| Title Exact Recall | 88.3% | 88.3% | 0 |

## Where AI adds value

The improvement is in **human-readable output quality**, not structural metrics:

- Without AI: `"SEBI Circular CIR/MIRSD/5/2013 dated August 27, 2013"` — correct but opaque
- With AI: same identifier + date, plus `descriptive_title: "general guidelines for dealing with conflict of interest"` — a compliance officer can understand the subject without opening the original circular

This is the primary v1 use case: when a circular says "per SEBI Circular CIR/MIRSD/5/2013 dated August 27, 2013", the AI enrichment tells you *what that circular was about*, based only on context available in the current PDF.

## Model used

`gemini-2.5-flash` via `generativelanguage.googleapis.com/v1beta`
