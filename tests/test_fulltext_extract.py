import json

from src.association import associate
import src.fulltext_extract as fulltext_extract
from src.fulltext_extract import FIELD_GROUPS, QuotaExhaustedError, evidence_issues, run, source_input


def make_archive(root, doc_id, text):
    folder = root / doc_id
    folder.mkdir(parents=True)
    (folder / "document.json").write_text(json.dumps({
        "document_id": doc_id, "source": {"file_name": f"{doc_id}.pdf"},
    }), encoding="utf-8")
    (folder / "model.txt").write_text(text, encoding="utf-8")
    (folder / "model.provenance.json").write_text(json.dumps({
        "document_id": doc_id, "spans": [{"start": 0, "end": len(text),
                                           "line_id": "p1.b0.l0", "page": 1}],
    }), encoding="utf-8")
    return folder / "document.json"


def extracted(topic, evidence_id="p1.b0.l0"):
    fields = {group: {name: {"status": "not_reported", "value": "",
                             "evidence_line_ids": []} for name in names}
              for group, names in FIELD_GROUPS.items()}
    fields["research_profile"]["research_topic"] = {
        "status": "found", "value": topic, "evidence_line_ids": [evidence_id]}
    return fields


def response(fields, doc_id):
    return {"id": f"resp-{doc_id}", "model": "test-model", "status": "completed",
            "usage": {"input_tokens": 120, "output_tokens": 30, "total_tokens": 150,
                      "input_tokens_details": {"cached_tokens": 0}},
            "output": [{"type": "message", "content": [
                {"type": "output_text", "text": json.dumps(fields)}]}]}


def test_fulltext_run_saves_reviewable_results_and_counts_only_new_calls(tmp_path):
    source = tmp_path / "source"
    first = make_archive(source, "first", "Healthcare roles and boundaries")
    second = make_archive(source, "second", "Professional roles and boundaries")
    output = tmp_path / "output"
    calls = []

    def caller(body, api_key, base_url):
        calls.append(body)
        doc_id = body["input"].split("Document ID: ")[1].splitlines()[0]
        return response(extracted("professional roles"), doc_id)

    result = run([first, second], output, "test-model", api_key="test", caller=caller)
    assert result["documents_completed"] == 2
    assert result["new_api_calls"] == 2
    assert result["new_api_usage"]["total_tokens"] == 300
    assert len(calls) == 2
    assert calls[0]["text"]["format"]["strict"] is True
    assert "[p1.b0.l0]" in calls[0]["input"]
    saved = json.loads((output / "first" / "fulltext.json").read_text(encoding="utf-8"))
    assert saved["extracted"]["research_profile"]["research_topic"]["evidence_line_ids"] == ["p1.b0.l0"]
    assert saved["validation_issues"] == []
    assert "professional roles" in (output / "first" / "fulltext.md").read_text(encoding="utf-8")
    assert (output / "first" / "fulltext-usage.json").exists()
    assert json.loads((output / "first" / "fulltext-usage.json").read_text(encoding="utf-8"))["totals"]["total_tokens"] == 150
    assert len(json.loads((output / "fulltext-associations.json").read_text(encoding="utf-8"))["pairs"]) == 1

    def must_not_call(*args):
        raise AssertionError("Existing results should be reused")

    repeated = run([first, second], output, "test-model", api_key="test", caller=must_not_call)
    assert repeated["new_api_calls"] == 0
    assert repeated["completed_document_usage"]["total_tokens"] == 300


def test_unknown_evidence_is_flagged_and_usage_survives_invalid_json(tmp_path):
    source = tmp_path / "source"
    file = make_archive(source, "first", "A source line")
    _, prompt, known_ids = source_input(file.parent)
    assert "A source line" in prompt
    assert evidence_issues(extracted("topic", "p9.b9.l9"), known_ids)

    bad_response = response(extracted("topic"), "first")
    bad_response["output"][0]["content"][0]["text"] = "not JSON"
    result = run([file], tmp_path / "output", "test-model", api_key="test",
                 caller=lambda *args: bad_response)
    assert result["documents_failed"] == 1
    assert result["new_api_usage"]["total_tokens"] == 150
    usage_path = tmp_path / "output" / "first" / "fulltext-usage.json"
    assert json.loads(usage_path.read_text(encoding="utf-8"))["totals"]["total_tokens"] == 150
    run([file], tmp_path / "output", "test-model", api_key="test",
        caller=lambda *args: bad_response)
    assert json.loads(usage_path.read_text(encoding="utf-8"))["totals"]["total_tokens"] == 300


def test_association_prefers_shared_extracted_terms():
    documents = [{"document_id": doc_id, "source_file": f"{doc_id}.pdf",
                  "extracted": extracted(topic)} for doc_id, topic in (
                      ("a", "healthcare professional roles"),
                      ("b", "healthcare professional boundaries"),
                      ("c", "military matching experiment"))]
    links = associate(documents, cluster_count=2)
    assert links["pairs"][0]["a"] == "a"
    assert links["pairs"][0]["b"] == "b"
    assert any(set(group["document_ids"]) == {"a", "b"} for group in links["clusters"])


def test_quota_exhaustion_stops_remaining_requests(tmp_path):
    source = tmp_path / "source"
    files = [make_archive(source, doc_id, "Article text") for doc_id in ("first", "second")]
    calls = []

    def exhausted(*args):
        calls.append(1)
        raise QuotaExhaustedError("credit_balance_exhausted")

    result = run(files, tmp_path / "output", "test-model", api_key="test", caller=exhausted)
    assert len(calls) == 1
    assert result["documents_completed"] == 0
    assert result["documents_pending"] == 1
    assert not (tmp_path / "output" / "fulltext-associations.json").exists()


def test_api_key_can_be_loaded_from_ignored_env_file(tmp_path, monkeypatch):
    module_file = tmp_path / "src" / "fulltext_extract.py"
    module_file.parent.mkdir()
    (tmp_path / ".env").write_text('OPENAI_API_KEY="test-key"\n', encoding="utf-8")
    monkeypatch.setattr(fulltext_extract, "__file__", str(module_file))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert fulltext_extract.configured_api_key() == "test-key"
    monkeypatch.setenv("OPENAI_API_KEY", "process-key")
    assert fulltext_extract.configured_api_key() == "process-key"
