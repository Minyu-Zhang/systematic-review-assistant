"""Evaluate existing outputs without overwriting source PDFs or legacy results.

python -m scripts.evaluate_corpus --tokens
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
from importlib.metadata import distributions
import json
import os
from pathlib import Path
import platform
import re
import csv

from src.layout_pipeline import model_payload, page_lines, project_line, save_json, validate_document
from src.quality import coverage, normalized, text_health


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def annotation_scores(doc, annotations):
    relevant = next((a for a in annotations["documents"] if doc["source"]["file_name"].startswith(a["file_prefix"])), None)
    results = []
    if not relevant:
        return results
    for entry in relevant["pages"]:
        page_no = entry["page"]
        page = doc["pages"][page_no-1]
        active_text = normalized("\n".join(l["text"] for l in page_lines(page) if not l["excluded_reason"]))
        native = normalized(page["raw_text"])
        md = normalized(page["layout"]["markdown"] or "")
        expected = {normalized(t) for t in entry["headings"]}
        actual = {normalized(s["title"]) for s in doc["sections"] if s["title"] and s["heading_line_id"].startswith(f"p{page_no}.")}
        results.append({"document": doc["source"]["file_name"], "page": page_no,
                        "heading_tp": len(actual & expected), "heading_fp": len(actual-expected),
                        "heading_fn": len(expected-actual), "missing_headings": sorted(expected-actual),
                        "extra_headings": sorted(actual-expected),
                        "snippets": [{"text": s, "native": normalized(s) in native,
                                      "model": normalized(s) in active_text,
                                      "markdown": normalized(s) in md} for s in entry["snippets"]]})
    return results


def evaluate(root, output, tokens=False):
    processed = root / "data/processed"
    files = sorted(processed.glob("*/document.json"))
    if not files:
        raise ValueError("Run python -m src.pipeline first")
    errors_path = processed / "run-errors.json"
    if errors_path.exists() and json.loads(errors_path.read_text(encoding="utf-8")):
        raise ValueError("Latest pipeline run has document failures; do not evaluate stale outputs")
    encoder = None
    if tokens:
        import tiktoken
        os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(root / "tmp/tiktoken"))
        encoder = tiktoken.get_encoding("cl100k_base")
    annotations_path = root / "tests/fixtures/annotations.json"
    annotations = json.loads(annotations_path.read_text(encoding="utf-8"))
    rows, pages, checks, input_manifest, token_rows = [], [], [], [], []
    for file in files:
        doc = json.loads(file.read_text(encoding="utf-8"))
        validate_document(doc)
        name = doc["source"]["file_name"]
        stem = Path(name).stem
        pdf = root / "data/pdf" / name
        legacy_json = root / "data/json" / f"{stem}.json"
        legacy_md = root / "data/markdown" / f"{stem}.md"
        if digest(pdf) != doc["document_id"]:
            raise ValueError(f"Source changed since processing: {name}")
        old = json.loads(legacy_json.read_text(encoding="utf-8")) if legacy_json.exists() else {}
        old_md = legacy_md.read_text(encoding="utf-8") if legacy_md.exists() else ""
        native = "\n".join(p["raw_text"] for p in doc["pages"])
        archive = "\n".join(l["text"] for p in doc["pages"] for l in page_lines(p))
        model, provenance = model_payload(doc)
        stored_model = (file.parent / "model.txt").read_text(encoding="utf-8")
        stored_provenance = json.loads((file.parent / "model.provenance.json").read_text(encoding="utf-8"))
        if stored_model != model or stored_provenance != provenance:
            raise ValueError(f"Model export is stale or uses different options: {name}; rerun src.export_model")
        md = "\n".join(p["layout"]["markdown"] or "" for p in doc["pages"])
        all_lines = {l["id"]: l for p in doc["pages"] for l in page_lines(p)}
        for span in provenance["spans"]:
            if model[span["start"]:span["end"]] != project_line(all_lines[span["line_id"]]["text"]):
                raise ValueError(f"Invalid model offset: {name}/{span['line_id']}")
        archive_recall = coverage(native, archive)["character_recall"]
        if archive_recall != 1:
            raise ValueError(f"Native text not fully archived: {name}: {archive_recall}")
        native_health = text_health(native)
        old_health = text_health(old.get("cleaned_text", ""))
        exclusions = Counter(l["excluded_reason"] for l in all_lines.values() if l["excluded_reason"])
        row = {"file": name, "pages": len(doc["pages"]), "native_chars": len(native),
               "legacy_cleaned_chars": len(old.get("cleaned_text", "")), "legacy_markdown_chars": len(old_md),
               "legacy_markdown_character_recall": coverage(native, old_md)["character_recall"],
               "fresh_markdown_character_recall": coverage(native, md)["character_recall"],
               "archive_character_recall": archive_recall,
               "model_chars": len(model), "model_character_recall": coverage(native, model)["character_recall"],
               "native_order_pages": sum(p["reading_order_source"] == "native_stream" for p in doc["pages"]),
               "ocr_review_pages": sum(p["quality"]["needs_ocr_review"] for p in doc["pages"]),
               "layout_error_pages": sum(bool(p["layout"]["error"]) for p in doc["pages"]),
               "proposed_sections": len(doc["sections"]), "source_unicode_issues": native_health["suspicious_unicode_count"],
               "legacy_cleaned_unicode_issues": old_health["suspicious_unicode_count"],
               "native_standalone_numbers": native_health["standalone_numbers"],
               "legacy_cleaned_standalone_numbers": old_health["standalone_numbers"],
               "native_repeated_line_instances": native_health["repeated_line_instances"],
               "repeated_margin_lines": exclusions["repeated_margin_text"],
               "duplicate_position_lines": exclusions["duplicate_at_same_position"],
               "margin_page_number_lines": exclusions["margin_page_number"],
               "rejected_heading_candidates": sum(not c["accepted"] for c in doc["heading_candidates"]),
               "excluded_line_count": sum(bool(l["excluded_reason"]) for l in all_lines.values()),
               "model_table_boxes": sum(b["class"] == "table" for p in doc["pages"] for b in p["layout"]["boxes"]),
               "legacy_markdown_table_rows": sum(line.lstrip().startswith("|") for line in old_md.splitlines())}
        rows.append(row)
        for p in doc["pages"]:
            pages.append({"file": name, "page": p["page_number"], "native_chars": len(p["raw_text"]),
                          "markdown_chars": len(p["layout"]["markdown"] or ""),
                          **p["layout"]["comparison"], "reading_order": p["reading_order_source"],
                          "issues": ";".join(p["layout"]["issues"]),
                          "needs_ocr_review": p["quality"]["needs_ocr_review"],
                          "error": p["layout"]["error"]})
        checks.extend(annotation_scores(doc, annotations))
        for source in (pdf, legacy_json, legacy_md):
            if source.exists():
                input_manifest.append({"path": source.relative_to(root).as_posix(), "sha256": digest(source), "bytes": source.stat().st_size})
        if encoder:
            def count(text):
                return len(encoder.encode(text, disallowed_special=()))
            # Paired comparisons hold text content constant; legacy MD may be lossy.
            wrapper = json.dumps({"text": model}, ensure_ascii=False)
            token_rows.append({"file": name, "legacy_json_tokens": count(legacy_json.read_text(encoding="utf-8")) if legacy_json.exists() else None,
                               "legacy_markdown_tokens": count(old_md), "native_text_tokens": count(native),
                               "model_text_tokens": count(model), "same_text_json_tokens": count(wrapper),
                               "same_text_markdown_fence_tokens": count("```text\n" + model + "```\n"),
                               "archive_json_tokens": count(file.read_text(encoding="utf-8"))})
    expected_sources = {p.name for p in (root / "data/pdf").glob("*.pdf")}
    if Counter(r["file"] for r in rows) != Counter(expected_sources):
        raise ValueError("Processed corpus does not match input PDFs (missing or duplicate/stale outputs)")
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "baseline-manifest.json"
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))["inputs"]
        if previous != input_manifest:
            raise ValueError("Baseline inputs changed; use a separate --output to create a new baseline")
    else:
        save_json(manifest_path, {"created_at": datetime.now(timezone.utc).isoformat(), "inputs": input_manifest})
    for filename, data in [("corpus.csv", rows), ("pages.csv", pages), ("tokens.csv", token_rows)]:
        if data:
            with (output / filename).open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(data[0]))
                writer.writeheader()
                writer.writerows(data)
    tp = sum(c["heading_tp"] for c in checks)
    fp = sum(c["heading_fp"] for c in checks)
    fn = sum(c["heading_fn"] for c in checks)
    snippets = [s for c in checks for s in c["snippets"]]
    summary = {"documents": len(rows), "pages": sum(r["pages"] for r in rows),
               "archive_recall_all_one": all(r["archive_character_recall"] == 1 for r in rows),
               "native_order_pages": sum(r["native_order_pages"] for r in rows),
               "layout_error_pages": sum(r["layout_error_pages"] for r in rows),
               "ocr_review_pages": sum(r["ocr_review_pages"] for r in rows),
               "annotated_pages": len(checks), "heading_tp": tp, "heading_fp": fp, "heading_fn": fn,
               "heading_precision": tp / max(1, tp+fp), "heading_recall": tp / max(1, tp+fn),
               "snippet_total": len(snippets), "snippet_model_retained": sum(s["model"] for s in snippets),
               "snippet_markdown_retained": sum(s["markdown"] for s in snippets),
               "tokenizer": "cl100k_base" if encoder else None,
               "token_totals": {key: sum(r[key] or 0 for r in token_rows) for key in token_rows[0] if key != "file"} if token_rows else {}}
    save_json(output / "summary.json", summary)
    save_json(output / "annotation-results.json", checks)
    save_json(output / "environment.json", {"python": platform.python_version(), "platform": platform.platform(),
              "packages": dict(sorted((d.metadata["Name"], d.version) for d in distributions())),
              "annotations_sha256": digest(annotations_path),
              "code_sha256": {str(p.relative_to(root)): digest(p) for p in list((root/"src").glob("*.py")) + [Path(__file__)]},
              "test_files_sha256": {str(p.relative_to(root)): digest(p) for p in (root/"tests").glob("test_*.py")},
              "requirements_lock_sha256": digest(root/"requirements-lock.txt")})
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path("reports/baseline"))
    parser.add_argument("--tokens", action="store_true", help="Requires tiktoken vocabulary download on first use")
    args = parser.parse_args()
    evaluate(args.root.resolve(), args.output, args.tokens)


if __name__ == "__main__":
    main()
