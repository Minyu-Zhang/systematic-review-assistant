"""Test full-text LLM extraction and exploratory cross-document associations.

Run from the project root: python -m src.fulltext_extract --estimate-only
Then set OPENAI_API_KEY and run: python -m src.fulltext_extract
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

from .association import associate, association_markdown
from .layout_pipeline import save_json


# Document metadata and section text already exist in document.json/screening.json.
# These are the research fields that need a full-text reading pass.
FIELD_GROUPS = {
    "bibliographic_metadata": ("title", "authors", "journal", "year", "doi", "keywords"),
    "research_profile": ("research_topic", "study_population", "study_region", "study_period"),
    "conceptual_framework": ("theories", "concepts", "variables"),
    "methodology": ("data_source", "sample_size", "methods", "models"),
    "results": ("findings", "limitations", "research_gap"),
}

INSTRUCTIONS = """Read the entire supplied article text and extract research information.
Return concise values in the requested JSON schema. Each field must have one status:
found, not_reported, or uncertain. Use an empty value and no evidence IDs for
not_reported. Cite exact [page.block.line] IDs from the supplied text for every
found value. Do not infer a missing fact from background literature or references.
If there are multiple samples, methods, or findings, summarize them briefly and
cite the supporting lines. Treat the PDF reading order and headings as fallible.
The result is a draft for human review, not a final eligibility decision."""


class QuotaExhaustedError(RuntimeError):
    """The API cannot process further documents until the account has credits."""


def response_schema():
    field = {"type": "object", "properties": {
        "status": {"type": "string", "enum": ["found", "not_reported", "uncertain"]},
        "value": {"type": "string"},
        "evidence_line_ids": {"type": "array", "items": {"type": "string"}},
    }, "required": ["status", "value", "evidence_line_ids"], "additionalProperties": False}
    groups = {group: {"type": "object", "properties": {name: field for name in names},
                      "required": list(names), "additionalProperties": False}
              for group, names in FIELD_GROUPS.items()}
    return {"type": "object", "properties": groups, "required": list(groups),
            "additionalProperties": False}


def source_input(folder):
    """Add native line IDs to model text without trusting proposed sections."""
    document = json.loads((folder / "document.json").read_text(encoding="utf-8"))
    text = (folder / "model.txt").read_text(encoding="utf-8")
    provenance = json.loads((folder / "model.provenance.json").read_text(encoding="utf-8"))
    if document["document_id"] != provenance["document_id"]:
        raise ValueError("Archive and model text have different document IDs")
    parts, known_ids, previous_page = [], set(), None
    for span in provenance["spans"]:
        line = text[span["start"]:span["end"]]
        if not line.strip():
            continue
        if span["page"] != previous_page:
            parts.append(f"\n=== Physical PDF page {span['page']} ===\n")
            previous_page = span["page"]
        parts.append(f"[{span['line_id']}] {line}\n")
        known_ids.add(span["line_id"])
    article = "".join(parts)
    prompt = f"File: {document['source']['file_name']}\nDocument ID: {document['document_id']}\n{article}"
    return document, prompt, known_ids


def request_body(model, prompt, max_output_tokens):
    return {"model": model, "instructions": INSTRUCTIONS, "input": prompt,
            "text": {"format": {"type": "json_schema", "name": "literature_fulltext",
                                "schema": response_schema(), "strict": True}},
            "max_output_tokens": max_output_tokens, "store": False}


def call_openai(body, api_key, base_url):
    """Use the Responses REST API; no additional runtime package is required."""
    url = base_url.rstrip("/") + "/responses"
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=payload, method="POST", headers={
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read(1000).decode("utf-8", errors="replace")
        if exc.code == 429 and ("credit_balance_exhausted" in detail or
                                "insufficient_quota" in detail):
            raise QuotaExhaustedError(f"Responses API HTTP {exc.code}: {detail}") from exc
        raise RuntimeError(f"Responses API HTTP {exc.code}: {detail}") from exc


def output_text(response):
    if response.get("status") != "completed":
        raise ValueError(f"Model response status: {response.get('status')}")
    contents = [part["text"] for item in response.get("output", [])
                if item.get("type") == "message" for part in item.get("content", [])
                if part.get("type") == "output_text"]
    if not contents:
        raise ValueError("Model response has no output text")
    return "".join(contents)


def usage_record(response, model):
    usage = response.get("usage") or {}
    return {"response_id": response.get("id"), "model": response.get("model", model),
            "status": response.get("status"), "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"), "total_tokens": usage.get("total_tokens"),
            "cached_input_tokens": (usage.get("input_tokens_details") or {}).get("cached_tokens"),
            "reasoning_tokens": (usage.get("output_tokens_details") or {}).get("reasoning_tokens")}


def evidence_issues(extracted, known_ids):
    """Check references mechanically; human review still checks their meaning."""
    issues = []
    for group, names in FIELD_GROUPS.items():
        for name in names:
            item = extracted[group][name]
            field = f"{group}.{name}"
            if item["status"] == "found" and (not item["value"] or not item["evidence_line_ids"]):
                issues.append(f"{field}: found without a value or evidence line")
            if item["status"] == "not_reported" and item["value"]:
                issues.append(f"{field}: not_reported has a value")
            invalid = sorted(set(item["evidence_line_ids"]) - known_ids)
            if invalid:
                issues.append(f"{field}: unknown line IDs {', '.join(invalid)}")
    return issues


def extracted_markdown(result):
    lines = [f"# 全文摘录：{result['source_file']}", "",
             "大模型生成的待核查草稿；行 ID 指向 document.json 中的原生文字。", ""]
    for group, names in FIELD_GROUPS.items():
        lines.extend([f"## {group}", ""])
        for name in names:
            item = result["extracted"][group][name]
            value = item["value"] or f"（{item['status']}）"
            ids = ", ".join(item["evidence_line_ids"]) or "无"
            lines.extend([f"### {name}", "", value, "", f"来源行：{ids}", ""])
    if result["validation_issues"]:
        lines.extend(["## 待核查的问题", ""])
        lines.extend(f"- {issue}" for issue in result["validation_issues"])
    return "\n".join(lines) + "\n"


def token_estimate(body, encoder):
    """Local approximation, separate from billable API usage."""
    return len(encoder.encode(body["instructions"] + "\n" + body["input"], disallowed_special=()))


def total_usage(records):
    return {name: sum(record.get(name) or 0 for record in records)
            for name in ("input_tokens", "output_tokens", "total_tokens", "cached_input_tokens", "reasoning_tokens")}


def record_usage(path, usage):
    """Keep failed attempts too, so a retry does not erase consumed tokens."""
    calls = []
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        calls = previous.get("calls", [previous])
    calls.append(usage)
    save_json(path, {"calls": calls, "totals": total_usage(calls)})


def configured_api_key():
    """Prefer the process environment; accept the project's ignored .env too."""
    if os.environ.get("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"]
    env_file = Path(__file__).resolve().parents[1] / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            name, separator, value = line.partition("=")
            if separator and name.strip() == "OPENAI_API_KEY":
                return value.strip().strip("\"'")
    return None


def run(files, output, model, api_key=None, base_url="https://api.openai.com/v1",
        max_output_tokens=8000, estimate_only=False, force=False, caller=call_openai):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    encoder = None
    if estimate_only:
        import tiktoken
        encoder = tiktoken.get_encoding("cl100k_base")
    estimates, completed, errors, new_usage = [], [], [], []
    for file in files:
        folder = file.parent
        result_folder = output / folder.name
        try:
            document, prompt, known_ids = source_input(folder)
            body = request_body(model, prompt, max_output_tokens)
            if estimate_only:
                estimates.append({"document_id": document["document_id"],
                                  "source_file": document["source"]["file_name"],
                                  "estimated_input_tokens": token_estimate(body, encoder)})
                continue
            result_folder.mkdir(parents=True, exist_ok=True)
            result_path = result_folder / "fulltext.json"
            source_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
            if result_path.exists() and not force:
                existing = json.loads(result_path.read_text(encoding="utf-8"))
                if (existing["document_id"] != document["document_id"] or
                        existing["model"] != model or
                        existing["source_input_sha256"] != source_hash):
                    raise ValueError("Existing fulltext.json uses another source or model; use --force to replace it")
                completed.append(existing)
                continue
            # Save usage before parsing, since a malformed answer still consumed tokens.
            response = caller(body, api_key, base_url)
            usage = usage_record(response, model)
            record_usage(result_folder / "fulltext-usage.json", usage)
            new_usage.append(usage)
            extracted = json.loads(output_text(response))
            issues = evidence_issues(extracted, known_ids)
            result = {"schema_version": "fulltext-0.1", "document_id": document["document_id"],
                      "source_file": document["source"]["file_name"], "model": model,
                      "source_input_sha256": source_hash,
                      "review_status": "pending", "extracted": extracted,
                      "validation_issues": issues, "usage": usage}
            save_json(result_path, result)
            (result_folder / "fulltext.md").write_text(extracted_markdown(result), encoding="utf-8")
            completed.append(result)
            print(f"Extracted {document['source']['file_name']}", flush=True)
        except Exception as exc:
            errors.append({"file": str(file),
                           "error": f"{type(exc).__name__}: {exc}"})
            print(f"FAILED {file.parent.name}: {exc}", flush=True)
            if isinstance(exc, QuotaExhaustedError):
                break
    if estimate_only:
        summary = {"tokenizer": "cl100k_base", "note": "Local text estimate; not API usage",
                   "model": model, "documents": estimates,
                   "estimated_input_tokens": sum(row["estimated_input_tokens"] for row in estimates),
                   "errors": errors}
        save_json(output / "fulltext-estimate.json", summary)
        return summary
    if completed:
        links = associate(completed)
        save_json(output / "fulltext-associations.json", links)
        (output / "fulltext-associations.md").write_text(association_markdown(links), encoding="utf-8")
    recorded = []
    for file in files:
        path = output / file.parent.name / "fulltext-usage.json"
        if path.exists():
            recorded.extend(json.loads(path.read_text(encoding="utf-8"))["calls"])
    summary = {"model": model, "documents_completed": len(completed), "documents_failed": len(errors),
               "documents_pending": len(files) - len(completed) - len(errors),
               "new_api_calls": len(new_usage), "new_api_usage": total_usage(new_usage),
               "recorded_api_usage": total_usage(recorded),
               "completed_document_usage": total_usage([doc["usage"] for doc in completed]),
               "errors": errors}
    save_json(output / "fulltext-run.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/processed"))
    parser.add_argument("--output", type=Path, default=Path("data/processed"))
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    parser.add_argument("--max-output-tokens", type=int, default=8000)
    parser.add_argument("--estimate-only", action="store_true")
    parser.add_argument("--force", action="store_true", help="Replace existing model extracts")
    args = parser.parse_args()
    files = [args.input] if args.input.is_file() else sorted(args.input.glob("*/document.json"))
    if not files:
        parser.error("No document.json archives found")
    key = configured_api_key()
    if not args.estimate_only and not key:
        parser.error("Set OPENAI_API_KEY before sending full text to the model")
    summary = run(files, args.output, args.model, key, args.base_url,
                  args.max_output_tokens, args.estimate_only, args.force)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
