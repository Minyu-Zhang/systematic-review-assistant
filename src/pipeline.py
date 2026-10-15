"""Run with: python -m src.pipeline --input data/pdf --output data/processed."""

import argparse
from pathlib import Path

from .export_model import export_document
from .layout_pipeline import parse_pdf, save_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/pdf"))
    parser.add_argument("--output", type=Path, default=Path("data/processed"))
    parser.add_argument("--no-layout", action="store_true", help="Native evidence only; no layout model")
    parser.add_argument("--markdown", action="store_true", help="Also export untrusted layout Markdown for comparison")
    parser.add_argument("--exclude-references", action="store_true", help="Exclude proposed references from model text only")
    args = parser.parse_args()
    files = [args.input] if args.input.is_file() else sorted(args.input.glob("*.pdf"))
    if not files:
        parser.error(f"No PDFs found at {args.input}")
    failures = []
    for path in files:
        try:
            doc = parse_pdf(path, use_layout=not args.no_layout)
            out = args.output / doc["document_id"][:16]
            out.mkdir(parents=True, exist_ok=True)
            save_json(out / "document.json", doc)
            export_document(doc, out, args.exclude_references)
            if args.markdown:
                md = "\n\n".join(f"<!-- physical page {p['page_number']} -->\n{p['layout']['markdown'] or ''}" for p in doc["pages"])
                (out / "candidate.md").write_text(md, encoding="utf-8")
            fallback = sum(p["reading_order_source"] == "native_stream" for p in doc["pages"])
            print(f"{path.name}: {doc['page_count']} pages, {fallback} native-order pages -> {out}", flush=True)
        except Exception as exc:
            failures.append({"file": path.name, "error": f"{type(exc).__name__}: {exc}"})
            print(f"FAILED {path.name}: {exc}", flush=True)
    save_json(args.output / "run-errors.json", failures)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
