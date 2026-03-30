#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", value)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = text.replace("&", " and ")
    text = text.replace("securities and exchange board of india", "sebi")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_identifier(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", value)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.upper()
    text = re.sub(r"[^A-Z0-9]+", "", text)
    return text


def normalize_url(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().rstrip("/")


def safe_div(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def f1_score(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None:
        return None
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def metric_row(tp: int, pred_total: int, gold_total: int) -> dict[str, Any]:
    precision = safe_div(tp, pred_total)
    recall = safe_div(tp, gold_total)
    return {
      "tp": tp,
      "pred_total": pred_total,
      "gold_total": gold_total,
      "precision": precision,
      "recall": recall,
      "f1": f1_score(precision, recall),
    }


def pick_pred_field(ref: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in ref:
            return ref[name]
    return None


def load_gold(gold_dir: Path) -> dict[str, dict[str, Any]]:
    gold = {}
    for path in sorted(gold_dir.glob("*.json")):
        item = load_json(path)
        gold[item["fixture_id"]] = item
    return gold


def load_predictions(pred_dir: Path | None) -> dict[str, dict[str, Any]]:
    if pred_dir is None or not pred_dir.exists():
        return {}
    predictions = {}
    for path in sorted(pred_dir.glob("*.json")):
        item = load_json(path)
        fixture_id = item.get("fixture_id") or path.stem
        predictions[fixture_id] = item
    return predictions


def build_gold_index(gold_fixture: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, set[str]], dict[str, set[str]]]:
    refs_by_key: dict[str, dict[str, Any]] = {}
    title_index: dict[str, set[str]] = defaultdict(set)
    identifier_index: dict[str, set[str]] = defaultdict(set)

    for ref in gold_fixture["scored_references"]:
        key = ref["canonical_key"]
        refs_by_key[key] = ref
        for alias in [ref.get("canonical_title"), *(ref.get("aliases") or [])]:
            normalized = normalize_text(alias)
            if normalized:
                title_index[normalized].add(key)
        identifier = normalize_identifier(ref.get("official_identifier"))
        if identifier:
            identifier_index[identifier].add(key)

    return refs_by_key, title_index, identifier_index


def match_prediction(
    pred_ref: dict[str, Any],
    refs_by_key: dict[str, dict[str, Any]],
    title_index: dict[str, set[str]],
    identifier_index: dict[str, set[str]],
) -> str | None:
    explicit_key = pick_pred_field(pred_ref, "canonical_key")
    if explicit_key in refs_by_key:
        return explicit_key

    pred_identifier = normalize_identifier(pick_pred_field(pred_ref, "official_identifier", "identifier"))
    if pred_identifier and pred_identifier in identifier_index:
        matches = identifier_index[pred_identifier]
        if len(matches) == 1:
            return next(iter(matches))

    pred_title = normalize_text(pick_pred_field(pred_ref, "canonical_title", "title"))
    if pred_title and pred_title in title_index:
        matches = title_index[pred_title]
        if len(matches) == 1:
            return next(iter(matches))

    return None


def aggregate_predictions(
    pred_fixture: dict[str, Any] | None,
    refs_by_key: dict[str, dict[str, Any]],
    title_index: dict[str, set[str]],
    identifier_index: dict[str, set[str]],
) -> dict[str, dict[str, Any]]:
    aggregated: dict[str, dict[str, Any]] = {}
    references = (pred_fixture or {}).get("references", [])

    for index, pred_ref in enumerate(references):
        matched_key = match_prediction(pred_ref, refs_by_key, title_index, identifier_index)
        pred_title_raw = pick_pred_field(pred_ref, "canonical_title", "title")
        pred_identifier_raw = pick_pred_field(pred_ref, "official_identifier", "identifier")
        pred_type = pick_pred_field(pred_ref, "document_type", "type")
        pred_pages = pick_pred_field(pred_ref, "source_pages") or []
        pred_url = pick_pred_field(pred_ref, "resolved_url", "url")

        if matched_key:
            aggregate_key = f"gold:{matched_key}"
        else:
            signature = (
                normalize_identifier(pred_identifier_raw)
                or normalize_text(pred_title_raw)
                or f"unmatched_{index}"
            )
            aggregate_key = f"pred:{signature}"

        bucket = aggregated.setdefault(
            aggregate_key,
            {
                "matched_key": matched_key,
                "pages": set(),
                "titles": set(),
                "identifiers": set(),
                "types": set(),
                "urls": set(),
                "raw_examples": [],
            },
        )

        bucket["pages"].update(int(page) for page in pred_pages if isinstance(page, int))
        normalized_title = normalize_text(pred_title_raw)
        if normalized_title:
            bucket["titles"].add(normalized_title)
        normalized_identifier = normalize_identifier(pred_identifier_raw)
        if normalized_identifier:
            bucket["identifiers"].add(normalized_identifier)
        if pred_type:
            bucket["types"].add(str(pred_type))
        normalized_url = normalize_url(pred_url)
        if normalized_url:
            bucket["urls"].add(normalized_url)
        bucket["raw_examples"].append(pred_ref)

    return aggregated


def format_metric(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def evaluate_fixture(gold_fixture: dict[str, Any], pred_fixture: dict[str, Any] | None) -> dict[str, Any]:
    refs_by_key, title_index, identifier_index = build_gold_index(gold_fixture)
    aggregated = aggregate_predictions(pred_fixture, refs_by_key, title_index, identifier_index)

    gold_doc_keys = set(refs_by_key.keys())
    pred_doc_keys = set(aggregated.keys())
    matched_doc_keys = {
        bucket["matched_key"]
        for bucket in aggregated.values()
        if bucket["matched_key"] is not None
    }

    doc_metrics = metric_row(
        tp=len(matched_doc_keys),
        pred_total=len(pred_doc_keys),
        gold_total=len(gold_doc_keys),
    )

    gold_page_instances = {
        (ref["canonical_key"], page)
        for ref in gold_fixture["scored_references"]
        for page in ref["source_pages"]
    }
    pred_page_instances = set()
    for aggregate_key, bucket in aggregated.items():
        if bucket["matched_key"] is not None:
            base_key = bucket["matched_key"]
        else:
            base_key = aggregate_key
        for page in bucket["pages"]:
            pred_page_instances.add((base_key, page))

    page_tp = len(gold_page_instances & pred_page_instances)
    page_metrics = metric_row(
        tp=page_tp,
        pred_total=len(pred_page_instances),
        gold_total=len(gold_page_instances),
    )

    gold_title_total = sum(1 for ref in gold_fixture["scored_references"] if ref.get("canonical_title"))
    title_exact = 0
    title_present = 0
    type_correct = 0
    type_total = 0
    resolution_correct = 0
    resolution_pred_total = 0
    resolution_gold_total = 0

    page_mismatches = []

    for ref in gold_fixture["scored_references"]:
        key = ref["canonical_key"]
        bucket = aggregated.get(f"gold:{key}")
        canonical_title_norm = normalize_text(ref.get("canonical_title"))
        gold_pages = sorted(ref.get("source_pages") or [])
        gold_type = ref.get("document_type")
        gold_url = normalize_url(ref.get("resolved_url"))

        if bucket:
            if canonical_title_norm:
                if bucket["titles"]:
                    title_present += 1
                if canonical_title_norm in bucket["titles"]:
                    title_exact += 1

            if gold_type:
                type_total += 1
                if gold_type in bucket["types"]:
                    type_correct += 1

            pred_pages = sorted(bucket["pages"])
            if pred_pages != gold_pages:
                page_mismatches.append(
                    {
                        "canonical_key": key,
                        "gold_pages": gold_pages,
                        "pred_pages": pred_pages,
                    }
                )

            if gold_url:
                resolution_gold_total += 1
                if gold_url in bucket["urls"]:
                    resolution_correct += 1
            if bucket["urls"]:
                resolution_pred_total += 1
        else:
            if gold_type:
                type_total += 0
            if gold_url:
                resolution_gold_total += 1

    for bucket in aggregated.values():
        if bucket["urls"] and bucket["matched_key"] is None:
            resolution_pred_total += 1
        elif bucket["urls"] and bucket["matched_key"] is not None:
            gold_url = normalize_url(refs_by_key[bucket["matched_key"]].get("resolved_url"))
            if not gold_url:
                resolution_pred_total += 1

    title_exact_recall = safe_div(title_exact, gold_title_total)
    title_presence_recall = safe_div(title_present, gold_title_total)
    type_accuracy = safe_div(type_correct, len(matched_doc_keys))
    resolution_precision = safe_div(resolution_correct, resolution_pred_total)
    resolution_recall = safe_div(resolution_correct, resolution_gold_total)

    missing_refs = sorted(gold_doc_keys - matched_doc_keys)
    extra_refs = []
    for aggregate_key, bucket in aggregated.items():
        if bucket["matched_key"] is None:
            sample = bucket["raw_examples"][0]
            extra_refs.append(
                {
                    "aggregate_key": aggregate_key,
                    "title": pick_pred_field(sample, "canonical_title", "title"),
                    "identifier": pick_pred_field(sample, "official_identifier", "identifier"),
                    "pages": sorted(bucket["pages"]),
                }
            )

    return {
        "fixture_id": gold_fixture["fixture_id"],
        "doc_metrics": doc_metrics,
        "page_metrics": page_metrics,
        "title_exact_recall": title_exact_recall,
        "title_presence_recall": title_presence_recall,
        "type_accuracy_on_matched_docs": type_accuracy,
        "resolution_precision": resolution_precision,
        "resolution_recall": resolution_recall,
        "missing_refs": missing_refs,
        "extra_refs": extra_refs,
        "page_mismatches": page_mismatches,
    }


def macro_average(results: list[dict[str, Any]], field_path: tuple[str, ...]) -> float | None:
    values = []
    for result in results:
        current: Any = result
        for key in field_path:
            current = current[key]
        if current is not None:
            values.append(current)
    if not values:
        return None
    return sum(values) / len(values)


def render_markdown(results: list[dict[str, Any]]) -> str:
    lines = []
    lines.append("| Fixture | Doc F1 | Page F1 | Title Exact Recall | Type Acc | Resolution P | Resolution R |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for result in results:
        lines.append(
            "| {fixture} | {doc_f1} | {page_f1} | {title_exact} | {type_acc} | {res_p} | {res_r} |".format(
                fixture=result["fixture_id"],
                doc_f1=format_metric(result["doc_metrics"]["f1"]),
                page_f1=format_metric(result["page_metrics"]["f1"]),
                title_exact=format_metric(result["title_exact_recall"]),
                type_acc=format_metric(result["type_accuracy_on_matched_docs"]),
                res_p=format_metric(result["resolution_precision"]),
                res_r=format_metric(result["resolution_recall"]),
            )
        )

    lines.append("")
    lines.append("## Macro Average")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Doc Precision | {format_metric(macro_average(results, ('doc_metrics', 'precision')))} |")
    lines.append(f"| Doc Recall | {format_metric(macro_average(results, ('doc_metrics', 'recall')))} |")
    lines.append(f"| Doc F1 | {format_metric(macro_average(results, ('doc_metrics', 'f1')))} |")
    lines.append(f"| Page Precision | {format_metric(macro_average(results, ('page_metrics', 'precision')))} |")
    lines.append(f"| Page Recall | {format_metric(macro_average(results, ('page_metrics', 'recall')))} |")
    lines.append(f"| Page F1 | {format_metric(macro_average(results, ('page_metrics', 'f1')))} |")
    lines.append(f"| Title Exact Recall | {format_metric(macro_average(results, ('title_exact_recall',)))} |")
    lines.append(f"| Title Presence Recall | {format_metric(macro_average(results, ('title_presence_recall',)))} |")
    lines.append(f"| Type Accuracy on Matched Docs | {format_metric(macro_average(results, ('type_accuracy_on_matched_docs',)))} |")
    lines.append(f"| Resolution Precision | {format_metric(macro_average(results, ('resolution_precision',)))} |")
    lines.append(f"| Resolution Recall | {format_metric(macro_average(results, ('resolution_recall',)))} |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Score normalized reference extraction predictions against gold labels.")
    parser.add_argument("--gold-dir", default="evals/ground_truth", help="Directory containing ground truth JSON files")
    parser.add_argument("--pred-dir", default=None, help="Directory containing prediction JSON files")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown", help="Output format")
    args = parser.parse_args()

    gold = load_gold(Path(args.gold_dir))
    predictions = load_predictions(Path(args.pred_dir)) if args.pred_dir else {}

    results = []
    for fixture_id in sorted(gold):
        result = evaluate_fixture(gold[fixture_id], predictions.get(fixture_id))
        results.append(result)

    if args.format == "json":
        print(json.dumps(results, indent=2))
    else:
        print(render_markdown(results))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
