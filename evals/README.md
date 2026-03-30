# SEBI Reference Extraction Evals

This folder contains a small, precision-first evaluation package for the Hyde take-home.

The current workspace did not include an existing eval harness, so this package is built around the five PDFs already present under `pdfs/`.

## What is scored

Primary scoring uses external-document references that are specific enough to normalize into a stable document object.

Each scored reference has:

- `canonical_key`: stable gold identifier used by the scorer
- `document_type`: `circular`, `master_circular`, `regulations`, `act`, or similar
- `canonical_title`: gold normalized title
- `official_identifier`: optional circular or notification identifier
- `source_pages`: input-PDF pages where the reference appears

Ground-truth files also include `abstain_mentions` for self-references, internal cross-references, and vague mentions that should not be aggressively resolved in a precision-first system.

## Recommended metrics

Use these as the headline metrics in the submission:

1. `doc_precision`, `doc_recall`, `doc_f1`
   Counts unique referenced documents per source PDF, ignoring page attribution.

2. `page_precision`, `page_recall`, `page_f1`
   Counts unique `(referenced_document, source_page)` instances.
   This is the cleanest measure of whether the system found the right document on the right page.

3. `title_exact_recall`
   `gold documents with exact canonical title extracted / gold documents`

4. `title_presence_recall`
   `gold documents with any non-empty predicted title / gold documents`

5. `type_accuracy_on_matched_docs`
   `matched documents with correct document_type / matched documents`

6. `resolution_precision` and `resolution_recall`
   Only for references where you choose to predict a resolved SEBI URL.
   Precision matters more than recall for this assignment.

## Prediction format

The scorer expects one JSON file per fixture in a prediction directory:

```json
{
  "fixture_id": "guidelines_for_custodians",
  "references": [
    {
      "canonical_title": "SEBI (Custodian) Regulations, 1996",
      "official_identifier": null,
      "document_type": "regulations",
      "source_pages": [1, 2, 4, 10],
      "resolved_url": null
    }
  ]
}
```

The scorer is flexible on field names and will also accept `title` instead of `canonical_title`, and `identifier` instead of `official_identifier`.

## How to run

```bash
python3 evals/evaluate.py --gold-dir evals/ground_truth --pred-dir path/to/predictions
```

If a fixture has no prediction file, it is scored as zero predictions for that fixture.

## Why this eval shape fits the assignment

- It stays focused on the single-PDF deliverable instead of a full knowledge-graph product.
- It measures page attribution directly, which the prompt explicitly asks for.
- It rewards abstention on vague references instead of unsafe guessing.
- It cleanly separates extraction quality from optional link resolution.
