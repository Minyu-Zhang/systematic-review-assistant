"""Export concise model text from an existing archive without reparsing PDFs."""

import argparse
import json
from pathlib import Path

from .layout_pipeline import model_payload, save_json, validate_document


def export_document(document, output, exclude_references=False):
    validate_document(document)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    text, provenance = model_payload(document, exclude_references)
    (output / "model.txt").write_text(text, encoding="utf-8")
    save_json(output / "model.provenance.json", provenance)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/processed"))
    parser.add_argument("--output", type=Path, help="Optional separate output root")
    parser.add_argument("--exclude-references", action="store_true")
    args = parser.parse_args()
    files = [args.input] if args.input.is_file() else sorted(args.input.glob("*/document.json"))
    if not files:
        parser.error("No document.json archives found")
    for file in files:
        doc = json.loads(file.read_text(encoding="utf-8"))
        output = args.output / doc["document_id"][:16] if args.output else file.parent
        export_document(doc, output, args.exclude_references)
    print(f"Exported {len(files)} document(s)")


if __name__ == "__main__":
    main()
