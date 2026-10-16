import hashlib

import pymupdf
import pytest

from src.layout_pipeline import (
    attach_layout, build_sections, extract_native_page, mark_artifacts,
    model_payload, page_lines, parse_pdf, project_line, validate_document,
)
from src.quality import candidate_issues, coverage


def create_pdf(path, texts):
    with pymupdf.open() as doc:
        for entries in texts:
            p = doc.new_page()
            for y, text in entries:
                p.insert_text((60, y), text)
        doc.save(path)
    return path


def test_native_evidence_and_model_offsets(tmp_path):
    path = create_pdf(tmp_path / "source.pdf", [[(120, "Preamble matters"), (200, "530"),
                                                (250, "Introduction"), (280, "Sample evidence"),
                                                (810, "1")], [(200, "More evidence")]])
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    doc = parse_pdf(path, use_layout=False)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert doc["page_count"] == 2
    assert doc["sections"][0]["kind"] == "front_matter_or_unknown"
    text, manifest = model_payload(doc)
    assert "Preamble matters" in text and "530" in text
    assert "\n1\n" not in text
    lines = {l["id"]: l for p in doc["pages"] for l in page_lines(p)}
    assert any(l["text"] == "1" for l in lines.values())  # Archive still has page number.
    for span in manifest["spans"]:
        line = lines[span["line_id"]]
        assert text[span["start"]:span["end"]] == line["text"]
        assert span["page"] == line["page"]
        assert line["spans"][0]["font"]
        assert len(span["bbox"]) == 4


def test_no_headings_and_empty_pages_preserved(tmp_path):
    path = create_pdf(tmp_path / "no-heading.pdf", [[(200, "ordinary sentence.")], []])
    doc = parse_pdf(path, use_layout=False)
    assert len(doc["sections"]) == 1
    assert "ordinary sentence." in model_payload(doc)[0]
    assert doc["pages"][1]["quality"]["needs_ocr_review"]
    assert doc["page_count"] == 2


def test_missing_candidate_triggers_native_fallback(tmp_path):
    path = create_pdf(tmp_path / "lost.pdf", [[(200, "A complete source sentence with important findings.")]])
    with pymupdf.open(path) as doc:
        page = extract_native_page(doc[0])
    attach_layout(page, {"text": "findings", "page_boxes": []})
    assert "candidate_character_loss" in page["layout"]["issues"]
    assert page["reading_order_source"] == "native_stream"
    assert len(page["reading_order"]) == len(page_lines(page))


def test_layout_failure_retains_page(monkeypatch, tmp_path):
    import pymupdf4llm

    def fail(*args, **kwargs):
        raise RuntimeError("intentional parser failure")

    monkeypatch.setattr(pymupdf4llm, "to_markdown", fail)
    path = create_pdf(tmp_path / "failed.pdf", [[(200, "Evidence survives parser failure")]])
    doc = parse_pdf(path)
    assert doc["pages"][0]["layout"]["error"] == "RuntimeError: intentional parser failure"
    assert "Evidence survives" in model_payload(doc)[0]


def test_layout_orders_columns_without_losing_lines(tmp_path):
    path = tmp_path / "columns.pdf"
    with pymupdf.open() as doc:
        p = doc.new_page()
        for point, text in [((60, 200), "Left first"), ((330, 200), "Right first"),
                            ((60, 230), "Left second"), ((330, 230), "Right second")]:
            p.insert_text(point, text)
        doc.save(path)
    with pymupdf.open(path) as doc:
        page = extract_native_page(doc[0])
    boxes = [{"class": "text", "bbox": [50, 180, 250, 250]},
             {"class": "text", "bbox": [320, 180, 550, 250]}]
    # Candidate recall is checked independently from the geometry-based order.
    attach_layout(page, {"text": page["raw_text"], "page_boxes": boxes})
    lookup = {l["id"]: l for l in page_lines(page)}
    assert [lookup[i]["text"] for i in page["reading_order"]] == ["Left first", "Left second", "Right first", "Right second"]
    assert page["reading_order_source"] == "layout_boxes"


def test_cover_references_do_not_start_bibliography(tmp_path):
    path = create_pdf(tmp_path / "jstor.pdf", [
        [(160, "Author(s) Example"), (200, "Your use of the JSTOR archive"), (230, "REFERENCES")],
        [(160, "Introduction"), (200, "Body"), (240, "References"), (280, "Smith 2020"),
         (320, "Appendix A"), (360, "Supplement")]])
    doc = parse_pdf(path, use_layout=False)
    assert doc["sections"][0]["kind"] == "cover"
    assert [s["kind"] for s in doc["sections"]].count("references") == 1
    full, _ = model_payload(doc)
    short, _ = model_payload(doc, exclude_references=True)
    assert "Smith 2020" in full and "Smith 2020" not in short
    assert "Supplement" in short and "REFERENCES" in short


def test_repeated_margin_text_is_auditable(tmp_path):
    path = create_pdf(tmp_path / "headers.pdf", [[(40, "Journal title"), (200, "42")]]*3)
    doc = parse_pdf(path, use_layout=False)
    text, _ = model_payload(doc)
    assert "Journal title" not in text and text.count("42") == 3
    assert all(any(l["excluded_reason"] == "repeated_margin_text" for l in page_lines(p)) for p in doc["pages"])


def test_validation_rejects_missing_section_evidence(tmp_path):
    path = create_pdf(tmp_path / "broken.pdf", [[(200, "Evidence")]])
    doc = parse_pdf(path, use_layout=False)
    doc["sections"][0]["line_ids"].clear()
    with pytest.raises(ValueError, match="Sections must cover"):
        validate_document(doc)


def test_unicode_formatting_and_quality_alarms():
    assert coverage("ﬁeld 研究", "field\n研究")["character_recall"] == 1
    assert candidate_issues("Important research evidence", "unrelated")[1]
    assert coverage("", "")["character_recall"] is None


def test_rotation_uses_unrotated_coordinates(tmp_path):
    path = tmp_path / "rotated.pdf"
    with pymupdf.open() as doc:
        p = doc.new_page(width=400, height=600)
        p.insert_text((60, 300), "Rotated evidence")
        p.set_rotation(90)
        doc.save(path)
    page = parse_pdf(path, use_layout=False)["pages"][0]
    assert (page["width"], page["height"], page["rotation"]) == (400, 600, 90)


def test_control_characters_are_only_changed_in_model_view(tmp_path):
    path = create_pdf(tmp_path / "control.pdf", [[(200, "530 subjects")]])
    doc = parse_pdf(path, use_layout=False)
    line = page_lines(doc["pages"][0])[0]
    line["text"] = "530\x08subjects"
    line["spans"][0]["text"] = line["text"]
    text, manifest = model_payload(doc)
    assert "530 subjects" in text and line["text"] == "530\x08subjects"
    assert manifest["spans"][0]["transformations"] == ["control_characters_to_spaces"]
    assert project_line("530") == "530"


def test_cjk_oversized_font_boxes_and_multiline_headings(tmp_path):
    from src.layout_pipeline import match_score
    assert match_score([156, 355, 283, 384], [156, 361, 283, 373]) >= .5
    path = create_pdf(tmp_path / "wrapped.pdf", [[(100, "Introduction"), (200, "1. A wrapped heading"),
                                                 (220, "continues here"), (250, "body sentence.")]])
    with pymupdf.open(path) as doc:
        page = extract_native_page(doc[0])
    attach_layout(page, {"text": page["raw_text"], "page_boxes": [
        {"class": "section-header", "bbox": [50, 80, 400, 110]},
        {"class": "section-header", "bbox": [50, 180, 400, 230]},
        {"class": "text", "bbox": [50, 235, 400, 260]}]})
    mark_artifacts([page])
    sections, _ = build_sections([page])
    assert [s["title"] for s in sections] == ["Introduction", "1. A wrapped heading continues here"]
    assert len(sections[1]["heading_line_ids"]) == 2


def test_appendix_mentioned_in_prose_is_not_a_heading():
    from src.layout_pipeline import heading_kind
    assert heading_kind("Appendix Table III contains the precise wording") is None
    assert heading_kind("Appendix A") == "appendix"


def test_cli_exports_valid_files_and_reports_partial_failure(tmp_path, monkeypatch):
    import json
    import sys
    from src.pipeline import main

    inputs = tmp_path / "pdfs"
    inputs.mkdir()
    create_pdf(inputs / "good.pdf", [[(200, "Useful evidence")]])
    (inputs / "bad.pdf").write_bytes(b"not a PDF")
    out = tmp_path / "outputs"
    monkeypatch.setattr(sys, "argv", ["pipeline", "--input", str(inputs), "--output", str(out), "--no-layout"])
    assert main() == 1
    assert len(list(out.glob("*/document.json"))) == 1
    assert "Useful evidence" in next(out.glob("*/model.txt")).read_text(encoding="utf-8")
    assert next(out.glob("*/screening.json")).is_file()
    assert next(out.glob("*/screening.md")).is_file()
    assert json.loads((out / "run-errors.json").read_text())[0]["file"] == "bad.pdf"


def test_cli_rejects_empty_input(tmp_path, monkeypatch):
    import sys
    from src.pipeline import main

    monkeypatch.setattr(sys, "argv", ["pipeline", "--input", str(tmp_path)])
    with pytest.raises(SystemExit) as err:
        main()
    assert err.value.code == 2


def test_overlapping_duplicate_text_is_retained_in_archive_only(tmp_path):
    path = create_pdf(tmp_path / "duplicates.pdf", [[(200, "Repeated OCR evidence"),
                                                    (200, "Repeated OCR evidence")]])
    doc = parse_pdf(path, use_layout=False)
    lines = page_lines(doc["pages"][0])
    duplicates = [l for l in lines if l["excluded_reason"] == "duplicate_at_same_position"]
    assert len(duplicates) == 1
    assert duplicates[0]["duplicate_of"] in {l["id"] for l in lines}
    assert model_payload(doc)[0].count("Repeated OCR evidence") == 1
    assert sum(l["text"].count("Repeated OCR evidence") for l in lines) == 2
