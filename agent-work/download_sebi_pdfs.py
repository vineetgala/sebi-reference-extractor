#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote
from urllib.request import Request, urlopen


PAGE_URLS = [
    "https://www.sebi.gov.in/legal/circulars/jan-2026/ease-of-doing-investment-and-ease-of-doing-business-doing-away-with-requirement-of-issuance-of-letter-of-confirmation-loc-and-to-effect-direct-credit-of-securities-in-dematerialisation-account-o-_99421.html",
    "https://www.sebi.gov.in/legal/circulars/feb-2026/obligations-on-cras-while-undertaking-rating-of-financial-instruments-falling-under-the-purview-of-any-other-financial-sector-regulator_99670.html",
    "https://www.sebi.gov.in/legal/circulars/feb-2026/valuation-of-physical-gold-and-silver-held-by-mutual-fund-schemes_100001.html",
    "https://www.sebi.gov.in/legal/circulars/mar-2026/guidelines-for-custodians_100118.html",
    "https://www.sebi.gov.in/legal/circulars/mar-2026/ease-of-doing-business-measures-relaxations-in-certain-reporting-requirements-for-certain-stock-brokers-and-doing-away-with-the-requirement-of-reporting-of-demat-account_100511.html",
]


PDF_RE = re.compile(r"file=(https://www\.sebi\.gov\.in/[^'\"<>]+\.pdf)", re.IGNORECASE)


def fetch_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=60) as response:
        return response.read().decode("utf-8", "ignore")


def fetch_bytes(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=120) as response:
        return response.read()


def safe_name(pdf_url: str) -> str:
    name = Path(unquote(pdf_url)).name
    return name if name.lower().endswith(".pdf") else f"{name}.pdf"


def main() -> int:
    base_dir = Path(__file__).resolve().parents[1]
    pdf_dir = base_dir / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = base_dir / "manifest.json"

    manifest = []
    for page_url in PAGE_URLS:
        html = fetch_text(page_url)
        match = PDF_RE.search(html)
        if not match:
            print(f"Could not resolve PDF for: {page_url}", file=sys.stderr)
            return 1

        pdf_url = match.group(1)
        pdf_name = safe_name(pdf_url)
        pdf_path = pdf_dir / pdf_name
        pdf_path.write_bytes(fetch_bytes(pdf_url))

        manifest.append(
            {
                "page_url": page_url,
                "pdf_url": pdf_url,
                "pdf_path": str(pdf_path),
                "bytes": pdf_path.stat().st_size,
            }
        )
        print(f"Downloaded {pdf_name}")

    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
