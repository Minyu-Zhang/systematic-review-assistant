import json

from src.contrastive_nlp import candidate_pairs, choose_diverse, text_windows


def archive(root):
    folder = root / "paper"
    folder.mkdir(parents=True)
    lines = [
        ("The study argues that professional boundaries change through daily practice.", "s0"),
        ("We examine how workers negotiate relationships with clients.", "s0"),
        ("References", "s1"),
        ("Smith 2001. Professional boundaries and social work.", "s1"),
    ]
    text, spans = "", []
    for index, (value, section_id) in enumerate(lines):
        spans.append({"start": len(text), "end": len(text) + len(value),
                      "line_id": f"p1.b{index}.l0", "page": 1, "section_id": section_id})
        text += value + "\n"
    (folder / "document.json").write_text(json.dumps({
        "document_id": "paper", "source": {"file_name": "paper.pdf"},
        "sections": [{"id": "s0", "kind": "body"},
                     {"id": "s1", "kind": "references"}],
    }), encoding="utf-8")
    (folder / "model.txt").write_text(text, encoding="utf-8")
    (folder / "model.provenance.json").write_text(json.dumps({
        "document_id": "paper", "spans": spans,
    }), encoding="utf-8")
    return folder


def test_page_local_windows_keep_source_lines_and_drop_references(tmp_path):
    windows = text_windows(archive(tmp_path), min_terms=5, target_chars=80)
    assert len(windows) == 1
    assert windows[0]["line_ids"] == ["p1.b0.l0", "p1.b1.l0"]
    assert "Smith" not in windows[0]["text"]


def test_cross_document_candidates_are_diversified():
    windows = [
        {"window_id": "a:1", "document_id": "a", "source_file": "a.pdf", "page": 1,
         "line_ids": ["p1.b0.l0"],
         "text": "We argue that professional boundaries shape social worker client relationships."},
        {"window_id": "b:1", "document_id": "b", "source_file": "b.pdf", "page": 2,
         "line_ids": ["p2.b0.l0"],
         "text": "We examine professional boundaries in social worker client relationships."},
        {"window_id": "c:1", "document_id": "c", "source_file": "c.pdf", "page": 1,
         "line_ids": ["p1.b0.l0"],
         "text": "We analyze military matching and productivity in officer assignments."},
    ]
    candidates, vocabulary = candidate_pairs(windows, threshold=0.1)
    assert vocabulary > 0
    assert len(candidates) == 1
    assert {candidates[0]["left"]["document_id"], candidates[0]["right"]["document_id"]} == {"a", "b"}
    assert len(choose_diverse(candidates)) == 1
