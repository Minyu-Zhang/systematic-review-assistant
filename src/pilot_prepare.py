"""Prepare the user-selected six-paper pilot offline; never sends API requests."""

import argparse
import hashlib
import itertools
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_KINDS = {"cover", "references"}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_evidence(folder, selection):
    paths = [folder / name for name in ("document.json", "model.txt", "model.provenance.json")]
    document = json.loads(paths[0].read_text(encoding="utf-8"))
    text = paths[1].read_text(encoding="utf-8")
    provenance = json.loads(paths[2].read_text(encoding="utf-8"))
    doc_id = document["document_id"]
    if doc_id != provenance["document_id"] or not doc_id.startswith(selection["archive"]):
        raise ValueError(f"Archive identity mismatch: {folder}")
    kinds = {item["id"]: item["kind"] for item in document.get("sections", [])}
    records, excluded, seen = [], [], set()
    for span in provenance["spans"]:
        line_id = span["line_id"]
        if line_id in seen:
            raise ValueError(f"Duplicate source line: {line_id}")
        seen.add(line_id)
        start, end = span["start"], span["end"]
        if not 0 <= start <= end <= len(text):
            raise ValueError(f"Invalid source offset: {line_id}")
        value = text[start:end]
        kind = kinds.get(span.get("section_id"), "unknown")
        record = {"evidence_id": f'{selection["alias"]}:{line_id}',
                  "document_id": doc_id, "page": span["page"], "line_id": line_id,
                  "start": start, "end": end, "text": value, "section_kind": kind}
        if kind in EXCLUDED_KINDS or not value.strip():
            excluded.append({"evidence_id": record["evidence_id"], "page": span["page"],
                             "reason": kind if value.strip() else "blank"})
        else:
            records.append(record)
    metadata = dict(selection, document_id=doc_id, source_file=document["source"]["file_name"],
                    pages=len(document.get("pages", [])), raw_characters=len(text),
                    retained_characters=sum(len(row["text"]) for row in records),
                    retained_lines=len(records), excluded_lines=len(excluded),
                    archive_hashes={path.name: sha256(path.read_bytes()) for path in paths})
    return metadata, records, excluded


def render_lines(records):
    return "\n".join(f'[{r["evidence_id"]}] {r["text"]}' for r in records)


def chunk_lines(records, max_chars=12000):
    """Keep source lines intact. No overlap; adjacent chunks can be retrieved by ID."""
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    chunks, current, size = [], [], 0
    for record in records:
        length = len(render_lines([record])) + 1
        if current and size + length > max_chars:
            chunks.append(current)
            current, size = [], 0
        current.append(record)
        size += length
    if current:
        chunks.append(current)
    return chunks


def prepare(input_root, output_root, selection_path, max_chars=12000):
    selection = json.loads(Path(selection_path).read_text(encoding="utf-8"))
    aliases = [d["alias"] for d in selection["documents"]]
    if len(set(aliases)) != len(aliases):
        raise ValueError("Duplicate document aliases")
    initial = selection["initial_api_comparison"]
    if not set(initial) <= set(aliases):
        raise ValueError("Unknown initial comparison document")
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    output = Path(output_root)
    # Load all archives before writing anything; outputs are a separate local run.
    loaded = [load_evidence(Path(input_root) / row["archive"], row)
              for row in selection["documents"]]
    input_path = Path(input_root).resolve()
    output_path = output.resolve()
    if output_path == input_path or input_path in output_path.parents or output_path in input_path.parents:
        raise ValueError("Pilot output must be separate from source archives")
    if (output / "manifest.json").exists():
        raise FileExistsError("Pilot preparation already exists; choose a new run directory")
    prompts = {name: (ROOT / "prompts" / f"pilot-{name}.txt").read_text(encoding="utf-8")
               for name in ("claims", "comparison", "direct")}
    output.mkdir(parents=True, exist_ok=True)
    documents, chunks, all_records, omissions, extraction_requests = [], [], [], [], []
    for metadata, records, excluded in loaded:
        alias = metadata["alias"]
        documents.append(metadata)
        all_records.extend(records)
        omissions.extend(excluded)
        document_chunks = chunk_lines(records, max_chars)
        for index, rows in enumerate(document_chunks, 1):
            chunk_id = f"{alias}-{index:03d}"
            source_text = render_lines(rows)
            target = output / "chunks" / f"{chunk_id}.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source_text + "\n", encoding="utf-8")
            chunks.append({"chunk_id": chunk_id, "document_alias": alias,
                           "evidence_ids": [r["evidence_id"] for r in rows],
                           "characters_with_ids": len(source_text),
                           "over_budget_single_line": len(source_text) > max_chars,
                           "previous": f"{alias}-{index-1:03d}" if index > 1 else None,
                           "next": f"{alias}-{index+1:03d}" if index < len(document_chunks) else None})
            extraction_requests.append({"task_id": chunk_id, "stage": "claims",
                                        "document_aliases": [alias],
                                        "messages": [{"role": "system", "content": prompts["claims"]},
                                                     {"role": "user", "content": source_text}]})
    pairs = [{"pair_id": f"P{index:02d}", "left": left, "right": right,
              "api_status": "not_run"}
             for index, (left, right) in enumerate(itertools.combinations(aliases, 2), 1)]
    with (output / "evidence.jsonl").open("w", encoding="utf-8") as file:
        for row in all_records:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_json(output / "chunks.json", chunks)
    write_json(output / "exclusions.json", omissions)
    write_json(output / "pairs.json", pairs)
    write_json(output / "requests" / "claims.json", extraction_requests)
    direct_records = [row for row in all_records if row["evidence_id"].split(":")[0] in initial]
    direct_text = render_lines(direct_records)
    direct = {"task_id": "initial-direct", "stage": "direct-baseline",
              "document_aliases": initial,
              "messages": [{"role": "system", "content": prompts["direct"]},
                           {"role": "user", "content": direct_text}]}
    write_json(output / "requests" / "direct.json", direct)
    write_json(output / "requests" / "comparison-template.json", {
        "status": "awaiting_claims_and_evidence", "system_prompt": prompts["comparison"],
        "pairs": pairs})
    manifest = {"schema_version": "pilot-preparation-1", "status": "prepared_offline",
                "api_calls": 0, "budget_cny": selection.get("budget_cny"),
                "paid_run_approved": False,
                "input_root": str(input_path), "selection_sha256": sha256(Path(selection_path).read_bytes()),
                "prompt_hashes": {key: sha256(value.encode("utf-8")) for key, value in prompts.items()},
                "documents": documents, "document_count": len(documents),
                "physical_pages": sum(d["pages"] for d in documents),
                "raw_characters": sum(d["raw_characters"] for d in documents),
                "retained_characters": sum(d["retained_characters"] for d in documents),
                "chunks": len(chunks), "paper_pairs": len(pairs), "max_chunk_chars": max_chars,
                "initial_direct_characters_with_prompt": sum(len(m["content"]) for m in direct["messages"]),
                "all_extraction_characters_with_prompts": sum(len(m["content"]) for r in extraction_requests for m in r["messages"]),
                "token_estimate": None,
                "notes": ["Character counts are not model tokens or a price quotation.",
                          "Only pre-existing cover/reference section labels and blank spans are excluded; errors may remain.",
                          "Excluded IDs are recorded; references remain in the original archives.",
                          "Known problem pages are flagged, not silently repaired.",
                          "Requests are provider-neutral task inputs, not executable API payloads; no model or credentials are embedded.",
                          "No budget or paid-call authorization is inferred from a provider preference."]}
    write_json(output / "manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/processed"))
    parser.add_argument("--output", type=Path, default=Path("outputs/pilot-2026-10-21"))
    parser.add_argument("--selection", type=Path, default=ROOT / "configs/pilot-six-papers.json")
    parser.add_argument("--max-chars", type=int, default=12000)
    args = parser.parse_args()
    manifest = prepare(args.input, args.output, args.selection, args.max_chars)
    print(json.dumps({key: manifest[key] for key in
                      ("status", "api_calls", "document_count", "physical_pages", "chunks", "paper_pairs",
                       "raw_characters", "retained_characters", "initial_direct_characters_with_prompt")}, indent=2))


if __name__ == "__main__":
    main()
