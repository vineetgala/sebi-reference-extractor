#!/usr/bin/env python3
"""Convert reference-output/*.references.json to eval prediction format.

Usage:
    python3 evals/make_predictions.py
    python3 evals/make_predictions.py --ref-dir reference-output --out-dir evals/predictions
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def build_fixture_id_map(gold_dir: Path) -> dict[str, str]:
    """Map PDF stem → fixture_id from ground truth source_pdf fields."""
    mapping = {}
    for path in sorted(gold_dir.glob("*.json")):
        gold = json.loads(path.read_text(encoding="utf-8"))
        pdf_stem = Path(gold["source_pdf"]).stem
        mapping[pdf_stem] = gold["fixture_id"]
    return mapping


def pick_title(doc: dict) -> str | None:
    # title       = full explicit name (Acts, Regulations, Master Circulars)
    # short_title = identifier + date for SEBI Circulars — matches gold canonical format
    return doc.get("title") or doc.get("short_title")


def convert_to_prediction(references_json: dict) -> list[dict]:
    pages_by_doc: dict[str, set[int]] = defaultdict(set)
    for mention in references_json.get("reference_mentions", []):
        doc_id = mention["document_id"]
        page = mention.get("source_page")
        if page is not None:
            pages_by_doc[doc_id].add(int(page))

    references = []
    for doc in references_json.get("referenced_documents", []):
        doc_id = doc["document_id"]
        # Skip bare date-only notifications (title_source generic_only, no stable identifier).
        # These are real PDF references but lack enough identity for precision scoring.
        if doc.get("document_type") == "notification" and doc.get("title_source") == "generic_only":
            continue
        # Skip AI-discovered notifications with no title — these are typically supporting-metadata
        # identifiers (e.g. gazette notification numbers that contextualise a regulations mention)
        # rather than standalone scoreable documents.
        if doc.get("document_type") == "notification" and doc.get("title_source") == "ai_discovered" and not doc.get("title"):
            continue
        references.append(
            {
                "canonical_title": pick_title(doc),
                "official_identifier": doc.get("identifier"),
                "document_type": doc.get("document_type"),
                "source_pages": sorted(pages_by_doc.get(doc_id, set())),
                "resolved_url": doc.get("resolved_url"),
            }
        )
    return references


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert extractor output to eval prediction format.")
    parser.add_argument("--ref-dir", default=str(REPO_ROOT / "reference-output"), help="Directory with *.references.json files")
    parser.add_argument("--gold-dir", default=str(REPO_ROOT / "evals" / "ground_truth"), help="Ground truth directory (for fixture_id lookup)")
    parser.add_argument("--out-dir", default=str(REPO_ROOT / "evals" / "predictions"), help="Output directory for prediction files")
    args = parser.parse_args()

    ref_dir = Path(args.ref_dir)
    gold_dir = Path(args.gold_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    fixture_id_map = build_fixture_id_map(gold_dir)

    for path in sorted(ref_dir.glob("*.references.json")):
        pdf_stem = path.stem.replace(".references", "")
        fixture_id = fixture_id_map.get(pdf_stem)
        if not fixture_id:
            print(f"  skip  {path.name}  (no matching fixture)")
            continue

        data = json.loads(path.read_text(encoding="utf-8"))
        references = convert_to_prediction(data)

        out = {"fixture_id": fixture_id, "references": references}
        out_path = out_dir / f"{fixture_id}.json"
        out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  wrote {out_path.name}  ({len(references)} refs)")


if __name__ == "__main__":
    main()
