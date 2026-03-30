#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent / "vendor"))

from pypdf import PdfReader  # noqa: E402


def summarize_pdf(pdf_path: Path) -> dict[str, object]:
    reader = PdfReader(str(pdf_path))
    page_stats = []
    extracted_samples = []

    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        compact = " ".join(text.split())
        page_stats.append(
            {
                "page": index,
                "chars": len(text),
                "has_text": bool(compact),
            }
        )
        if compact and len(extracted_samples) < 2:
            extracted_samples.append(
                {
                    "page": index,
                    "sample": compact[:400],
                }
            )

    total_chars = sum(item["chars"] for item in page_stats)
    text_pages = sum(1 for item in page_stats if item["has_text"])
    return {
        "file": pdf_path.name,
        "pages": len(reader.pages),
        "text_pages": text_pages,
        "total_chars": total_chars,
        "extractable_with_pypdf": text_pages > 0 and total_chars > 200,
        "page_stats": page_stats,
        "samples": extracted_samples,
    }


def main() -> int:
    pdf_dir = BASE_DIR / "pdfs"
    results = [summarize_pdf(path) for path in sorted(pdf_dir.glob("*.pdf"))]
    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
