# v0 Baseline — before eval-driven fixes

This snapshot captures the extractor **before** any fixes were applied based on eval feedback.

## State of the extractor at this snapshot

Four bugs were present:

1. `FORMAL_INSTRUMENT_RE` patterns required plural `Regulations` — the singular form `"SEBI (Credit Rating Agencies) Regulation, 1999"` (as it literally appears in one PDF) was not matched.
2. `infer_document_type` checked for `"regulations" in lowered` (string substring) — a matched singular-form title was typed as `"other"` instead of `"regulations"`.
3. `title_from_master_circular` preserved trailing parenthetical acronyms in the display title — producing `"Master Circular for Registrars to an Issue and Share Transfer Agents ("RTAs")"` instead of the clean canonical form.
4. SEBI Circular `short_title` did not include the date — producing `"SEBI Circular CIR/MIRSD/5/2013"` instead of `"SEBI Circular CIR/MIRSD/5/2013 dated August 27, 2013"`.

Additionally, bare date-only notification records (no stable identifier) were emitted as scored predictions, reducing precision.

## Key metrics

| Metric | Value |
|---|---:|
| Doc Precision | 91.0% |
| Doc Recall | 81.0% |
| **Doc F1** | **83.6%** |
| Page Precision | 90.0% |
| Page Recall | 74.0% |
| **Page F1** | **76.4%** |
| Title Exact Recall | 71.0% |
| Title Presence Recall | 81.0% |
| Type Accuracy on Matched Docs | 100.0% |

## Worst fixture

`cra_other_fsr_obligations`: Doc F1 **66.7%**, Page F1 **33.3%**

The entire SEBI (Credit Rating Agencies) Regulations, 1999 document was missing — not just on its introduction page but across all four pages where it appears via its "CRA Regulations" alias. The alias back-matches only work after the initial full-form registration, which never happened because the singular title form was not matched.
