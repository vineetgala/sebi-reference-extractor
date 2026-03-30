#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parents[0]
sys.path.insert(0, str(SCRIPT_DIR / "vendor"))

from pdfminer.high_level import extract_pages  # noqa: E402
from pdfminer.layout import LTChar, LTLine, LTRect, LTTextContainer, LTTextLine  # noqa: E402
from pypdf import PdfReader  # noqa: E402


LIST_PREFIX_RE = re.compile(r"^(\(?[0-9]+(?:\.[0-9]+)*[.)]?|[A-Za-z][.)]|[ivxlcdmIVXLCDM]+[.)])\s+")


def rounded_bbox(bbox: tuple[float, float, float, float]) -> list[float]:
    return [round(value, 2) for value in bbox]


def safe_mean(values: list[float], default: float = 0.0) -> float:
    return statistics.mean(values) if values else default


def dominant_left(lines: list[dict]) -> float:
    candidates = []
    for line in lines:
        text = line["text"].strip()
        if not text:
            continue
        if line["alignment"] == "center":
            continue
        if line["block_type_hint"] in {"header", "footer"}:
            continue
        candidates.append(round(line["left"], 1))
    if not candidates:
        return min((line["left"] for line in lines), default=0.0)
    return min(candidates)


def classify_alignment(left: float, right: float, page_width: float) -> str:
    center = (left + right) / 2
    if abs(center - (page_width / 2)) <= 20:
        return "center"
    if right >= page_width - 80 and left > page_width / 2:
        return "right"
    return "left"


def list_prefix(text: str) -> bool:
    return bool(LIST_PREFIX_RE.match(text))


def is_header_or_footer(text: str, top: float, bottom: float, page_height: float) -> str | None:
    compact = " ".join(text.split())
    if not compact:
        return None
    if bottom < 45:
        return "footer"
    if top > page_height - 45:
        return "header"
    if compact.startswith("Page ") and " of " in compact:
        return "header"
    return None


def guess_block_type(line: dict, page_height: float) -> str:
    forced = is_header_or_footer(line["text"], line["top"], line["bottom"], page_height)
    if forced:
        return forced

    text = line["text"].strip()
    if not text:
        return "empty"
    if line["alignment"] == "center" and (line["is_bold"] or text.isupper()):
        return "heading"
    if text.lower().startswith(("sub:", "subject:")):
        return "heading"
    if list_prefix(text):
        return "list_item"
    if line["is_bold"] and len(text) <= 120:
        return "heading"
    return "body"


def underline_match(
    line_bbox: tuple[float, float, float, float],
    decorations: list[dict[str, float]],
) -> bool:
    left, bottom, right, _top = line_bbox
    for deco in decorations:
        if deco["width"] < min(20, (right - left) * 0.4):
            continue
        overlap = min(right, deco["x1"]) - max(left, deco["x0"])
        if overlap <= 0:
            continue
        close_below = -3.0 <= deco["y"] - bottom <= 3.5
        if close_below:
            return True
    return False


def collect_page_items(pdf_path: Path) -> list[dict]:
    pages: list[dict] = []
    for page_number, layout in enumerate(extract_pages(str(pdf_path)), start=1):
        raw_lines: list[dict] = []
        decorations: list[dict[str, float]] = []
        for element in layout:
            if isinstance(element, LTTextContainer):
                for text_line in element:
                    if not isinstance(text_line, LTTextLine):
                        continue
                    text = " ".join(text_line.get_text().split())
                    chars = [char for char in text_line if isinstance(char, LTChar)]
                    if not text or not chars:
                        continue
                    font_names = [char.fontname for char in chars]
                    font_sizes = [round(char.size, 2) for char in chars]
                    unique_fonts = sorted(set(font_names))
                    unique_sizes = sorted(set(font_sizes))
                    bold_chars = sum(1 for name in font_names if "bold" in name.lower())
                    raw_lines.append(
                        {
                            "text": text,
                            "bbox": text_line.bbox,
                            "left": text_line.x0,
                            "right": text_line.x1,
                            "bottom": text_line.y0,
                            "top": text_line.y1,
                            "font_names": unique_fonts,
                            "font_sizes": unique_sizes,
                            "font_size_mean": round(safe_mean(font_sizes), 2),
                            "bold_ratio": round(bold_chars / len(font_names), 3),
                            "char_count": len(chars),
                        }
                    )
            elif isinstance(element, LTLine):
                decorations.append(
                    {
                        "x0": element.x0,
                        "x1": element.x1,
                        "y": safe_mean([element.y0, element.y1]),
                        "width": abs(element.x1 - element.x0),
                    }
                )
            elif isinstance(element, LTRect):
                width = abs(element.x1 - element.x0)
                height = abs(element.y1 - element.y0)
                if height <= 2.5 or width <= 2.5:
                    decorations.append(
                        {
                            "x0": element.x0,
                            "x1": element.x1,
                            "y": safe_mean([element.y0, element.y1]),
                            "width": width,
                        }
                    )

        raw_lines.sort(key=lambda item: (-item["top"], item["left"]))
        for raw in raw_lines:
            raw["alignment"] = classify_alignment(raw["left"], raw["right"], layout.width)
            raw["is_bold"] = raw["bold_ratio"] >= 0.5 or any("bold" in name.lower() for name in raw["font_names"])
            raw["is_underlined_guess"] = underline_match(raw["bbox"], decorations)
            raw["block_type_hint"] = guess_block_type(raw, layout.height)

        margin_left = dominant_left(raw_lines)
        body_lefts = sorted(
            {round(line["left"] - margin_left, 1) for line in raw_lines if line["block_type_hint"] not in {"header", "footer"}}
        )

        pages.append(
            {
                "page_number": page_number,
                "width": round(layout.width, 2),
                "height": round(layout.height, 2),
                "margin_left": round(margin_left, 2),
                "indent_steps": body_lefts[:12],
                "lines": raw_lines,
            }
        )
    return pages


def paragraph_break(prev_line: dict | None, line: dict, page_margin_left: float) -> bool:
    if prev_line is None:
        return True
    if prev_line["block_type_hint"] in {"header", "footer"} or line["block_type_hint"] in {"header", "footer"}:
        return True

    vertical_gap = prev_line["bottom"] - line["top"]
    indent_delta = abs(prev_line["left"] - line["left"])
    prev_text = prev_line["text"].strip()
    curr_text = line["text"].strip()
    tight_gap = max(5.5, prev_line["font_size_mean"] * 0.55)
    loose_gap = max(7.5, prev_line["font_size_mean"] * 0.9)

    if line["block_type_hint"] == "heading":
        continues_heading = (
            prev_line["block_type_hint"] == "heading"
            and indent_delta <= 6
            and vertical_gap <= max(24.0, tight_gap * 4)
            and (
                curr_text[:1].islower()
                or prev_text.lower().startswith(("sub:", "subject:"))
                or prev_line["is_underlined_guess"]
                or line["is_underlined_guess"]
            )
        )
        if continues_heading:
            return False
        return True
    if prev_line["block_type_hint"] == "heading":
        return True

    if line["block_type_hint"] == "list_item":
        return True
    if vertical_gap > loose_gap:
        return True

    if prev_line["block_type_hint"] == "list_item":
        if vertical_gap <= loose_gap and line["left"] >= prev_line["left"] + 10 and not list_prefix(curr_text):
            return False
        if vertical_gap <= loose_gap and indent_delta <= 6 and not list_prefix(curr_text):
            return False
        return True

    if indent_delta >= 18 and line["left"] <= prev_line["left"]:
        return True
    if prev_text.endswith(":") and list_prefix(curr_text):
        return True
    return False


def paragraph_bbox(lines: list[dict]) -> list[float]:
    return rounded_bbox(
        (
            min(line["left"] for line in lines),
            min(line["bottom"] for line in lines),
            max(line["right"] for line in lines),
            max(line["top"] for line in lines),
        )
    )


def paragraph_block_type(lines: list[dict]) -> str:
    types = [line["block_type_hint"] for line in lines]
    if not types:
        return "body"
    first_type = types[0]
    if first_type in {"heading", "list_item", "header", "footer"}:
        return first_type
    counts = Counter(types)
    return counts.most_common(1)[0][0]


def finalize_line_records(page: dict, paragraph_groups: list[list[dict]]) -> tuple[list[dict], list[dict]]:
    line_records: list[dict] = []
    paragraph_records: list[dict] = []
    margin_left = page["margin_left"]

    for paragraph_index, lines in enumerate(paragraph_groups, start=1):
        paragraph_id = f"p{page['page_number']}.{paragraph_index}"
        para_text = " ".join(line["text"].strip() for line in lines if line["text"].strip())
        para_type = paragraph_block_type(lines)
        para_indent = round(min(line["left"] for line in lines) - margin_left, 2)
        indent_level = int(round(max(0.0, para_indent) / 18.0))
        line_ids: list[str] = []
        for line in lines:
            indent_points = round(line["left"] - margin_left, 2)
            line_id = f"p{page['page_number']}l{len(line_records) + 1}"
            line_ids.append(line_id)
            line_records.append(
                {
                    "line_id": line_id,
                    "paragraph_id": paragraph_id,
                    "text": line["text"],
                    "bbox": rounded_bbox(line["bbox"]),
                    "left": round(line["left"], 2),
                    "right": round(line["right"], 2),
                    "top": round(line["top"], 2),
                    "bottom": round(line["bottom"], 2),
                    "font_names": line["font_names"],
                    "font_sizes": line["font_sizes"],
                    "font_size_mean": line["font_size_mean"],
                    "is_bold": line["is_bold"],
                    "bold_ratio": line["bold_ratio"],
                    "is_underlined_guess": line["is_underlined_guess"],
                    "indent_points": indent_points,
                    "indent_level": int(round(max(0.0, indent_points) / 18.0)),
                    "alignment": line["alignment"],
                    "block_type": line["block_type_hint"],
                }
            )
        paragraph_records.append(
            {
                "paragraph_id": paragraph_id,
                "block_type": para_type,
                "text": para_text,
                "bbox": paragraph_bbox(lines),
                "indent_points": para_indent,
                "indent_level": indent_level,
                "is_bold": all(line["is_bold"] for line in lines),
                "is_underlined_guess": any(line["is_underlined_guess"] for line in lines),
                "line_ids": line_ids,
            }
        )
    return line_records, paragraph_records


def build_document(pdf_path: Path) -> dict:
    reader = PdfReader(str(pdf_path))
    metadata = reader.metadata or {}
    root = reader.trailer["/Root"]
    tagged = bool(root.get("/MarkInfo")) or bool(root.get("/StructTreeRoot"))

    raw_pages = collect_page_items(pdf_path)
    pages = []
    for page in raw_pages:
        groups: list[list[dict]] = []
        current: list[dict] = []
        prev_line: dict | None = None
        for line in page["lines"]:
            if line["block_type_hint"] == "empty":
                continue
            if paragraph_break(prev_line, line, page["margin_left"]):
                if current:
                    groups.append(current)
                current = [line]
            else:
                current.append(line)
            prev_line = line
        if current:
            groups.append(current)

        line_records, paragraph_records = finalize_line_records(page, groups)
        pages.append(
            {
                "page_number": page["page_number"],
                "width": page["width"],
                "height": page["height"],
                "margin_left": page["margin_left"],
                "indent_steps": page["indent_steps"],
                "paragraphs": paragraph_records,
                "lines": line_records,
            }
        )

    return {
        "source_pdf": str(pdf_path),
        "file_name": pdf_path.name,
        "metadata": {
            "title": getattr(metadata, "title", None),
            "author": getattr(metadata, "author", None),
            "creator": getattr(metadata, "creator", None),
            "producer": getattr(metadata, "producer", None),
            "tagged_pdf_guess": tagged,
            "page_count": len(reader.pages),
        },
        "pages": pages,
    }


def input_paths(path_arg: str) -> Iterable[Path]:
    path = Path(path_arg)
    if path.is_dir():
        yield from sorted(path.glob("*.pdf"))
    else:
        yield path


def output_path_for(pdf_path: Path, output_dir: Path) -> Path:
    return output_dir / f"{pdf_path.stem}.structured.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract structured layout/style JSON from PDFs.")
    parser.add_argument("input", help="PDF file or directory containing PDFs")
    parser.add_argument(
        "--output-dir",
        default=str(BASE_DIR / "structured-output"),
        help="Directory for JSON output files",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pdf_paths = list(input_paths(args.input))
    if not pdf_paths:
        print("No PDF files found.", file=sys.stderr)
        return 1

    for pdf_path in pdf_paths:
        document = build_document(pdf_path)
        output_path = output_path_for(pdf_path, output_dir)
        output_path.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
        print(output_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
