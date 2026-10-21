import json

import pytest

from src.pilot_prepare import chunk_lines, load_evidence, prepare
from scripts.experiments.render_pilot_review import render


def archive(root, name):
    folder = root / name
    folder.mkdir(parents=True)
    text = "Cover\nAn actual claim.\nA reference."
    (folder / "model.txt").write_text(text, encoding="utf-8")
    document = {"document_id": name, "source": {"file_name": name + ".pdf"},
                "pages": [{}, {}], "sections": [
                    {"id": "c", "kind": "cover"}, {"id": "b", "kind": "body"},
                    {"id": "r", "kind": "references"}]}
    spans = [{"line_id": "p1.b0.l0", "page": 1, "start": 0, "end": 5, "section_id": "c"},
             {"line_id": "p2.b0.l0", "page": 2, "start": 6, "end": 22, "section_id": "b"},
             {"line_id": "p2.b1.l0", "page": 2, "start": 23, "end": len(text), "section_id": "r"}]
    (folder / "document.json").write_text(json.dumps(document), encoding="utf-8")
    (folder / "model.provenance.json").write_text(json.dumps({"document_id": name, "spans": spans}), encoding="utf-8")
    return folder


def setup_run(tmp_path):
    inputs = tmp_path / "archives"
    archive(inputs, "a")
    archive(inputs, "b")
    selection = tmp_path / "selection.json"
    selection.write_text(json.dumps({"documents": [{"alias": "A", "archive": "a"},
                                                  {"alias": "B", "archive": "b"}],
                                     "initial_api_comparison": ["A", "B"]}), encoding="utf-8")
    output = tmp_path / "run"
    return inputs, output, selection


def test_preparation_preserves_sources_and_records_exclusions(tmp_path):
    inputs, output, selection = setup_run(tmp_path)
    before = (inputs / "a" / "model.txt").read_bytes()
    result = prepare(inputs, output, selection, max_chars=100)
    rows = [json.loads(line) for line in (output / "evidence.jsonl").read_text().splitlines()]
    assert [r["text"] for r in rows] == ["An actual claim."] * 2
    assert result["api_calls"] == 0 and result["paid_run_approved"] is False
    assert result["paper_pairs"] == 1 and result["document_count"] == 2
    assert {r["reason"] for r in json.loads((output / "exclusions.json").read_text())} == {"cover", "references"}
    assert (inputs / "a" / "model.txt").read_bytes() == before
    with pytest.raises(FileExistsError):
        prepare(inputs, output, selection)


def test_foreign_provenance_is_rejected(tmp_path):
    folder = archive(tmp_path, "a")
    path = folder / "model.provenance.json"
    value = json.loads(path.read_text())
    value["document_id"] = "another-paper"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="identity"):
        load_evidence(folder, {"alias": "A", "archive": "a"})


def test_invalid_offsets_are_rejected(tmp_path):
    folder = archive(tmp_path, "a")
    path = folder / "model.provenance.json"
    value = json.loads(path.read_text())
    value["spans"][1]["end"] = 9999
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="offset"):
        load_evidence(folder, {"alias": "A", "archive": "a"})


def test_chunks_keep_long_lines_and_all_evidence_once():
    rows = [{"evidence_id": f"A:{i}", "text": "x" * length} for i, length in enumerate([5, 90, 5])]
    chunks = chunk_lines(rows, max_chars=30)
    assert len(chunks) == 3
    assert [r for chunk in chunks for r in chunk] == rows


def test_output_must_not_be_inside_source_archives(tmp_path):
    inputs, _, selection = setup_run(tmp_path)
    with pytest.raises(ValueError, match="separate"):
        prepare(inputs, inputs / "new-run", selection)
    assert not (inputs / "new-run").exists()


def test_review_refuses_tampered_evidence(tmp_path):
    inputs, output, selection = setup_run(tmp_path)
    prepare(inputs, output, selection)
    (output / "assistant-review.json").write_text('{}')
    path = output / "evidence.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]["text"] = "A fabricated conclusion"
    path.write_text("\n".join(json.dumps(r) for r in rows))
    with pytest.raises(ValueError, match="differs from original"):
        render(output)
