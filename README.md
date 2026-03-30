# SEBI Ref Extractor

This repo root now contains the working copy of the Hyde take-home materials that were previously scattered across `tmp/`.

## Layout

- `agent-work/`: extraction scripts and vendored dependencies
- `pdfs/`: the 5 SEBI source PDFs currently used for development
- `reference-output/`: current reference extraction outputs
- `manifest.json`: source PDF metadata
- `evals/`: ground truth, scorer, fixture notes, and results scaffold

## Notes

- `tmp/` still contains older scratch and regenerable intermediate files.
- The important reusable project assets now live at repo root.

## Quick Commands

```bash
python3 evals/evaluate.py --gold-dir evals/ground_truth
python3 agent-work/extract_references.py pdfs
```
