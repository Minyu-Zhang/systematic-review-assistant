import json

from src.info_extract import build_screening, export_screening


def archive(texts, sections):
    blocks = []
    for bi, (size, entries) in enumerate(texts):
        lines = []
        for li, text in enumerate(entries):
            line_id = f"p1.b{bi}.l{li}"
            lines.append({"id": line_id, "page": 1, "block_id": f"p1.b{bi}",
                          "bbox": [50, 50 + bi * 30, 500, 65 + bi * 30],
                          "text": text, "spans": [{"text": text, "size": size}],
                          "excluded_reason": None})
        blocks.append({"id": f"p1.b{bi}", "lines": lines})
    all_lines = [line for block in blocks for line in block["lines"]]
    source_sections = []
    for si, (title, kind, start, end) in enumerate(sections):
        line_ids = [line["id"] for line in all_lines[start:end]]
        source_sections.append({"id": f"s{si}", "title": title, "kind": kind,
                                "heading_line_id": line_ids[0] if title else None,
                                "heading_line_ids": line_ids[:1] if title else [],
                                "line_ids": line_ids, "needs_review": True})
    return {"document_id": "abc", "source": {"file_name": "article.pdf"},
            "metadata": {}, "pages": [{"page_number": 1, "height": 800,
                                      "blocks": blocks,
                                      "reading_order": [line["id"] for line in all_lines],
                                      "quality": {"needs_ocr_review": False,
                                                  "needs_reading_order_review": False}}],
            "sections": source_sections}


def test_screening_modules_keep_text_and_native_line_ids(tmp_path):
    doc = archive([(20, ["研究标题"]), (10, ["内容提要：研究问题与方法", "研究结果"]),
                   (10, ["关键词：社会学；职业"]), (10, ["一、引言", "正文内容"])],
                  [(None, "front_matter_or_unknown", 0, 4), ("一、引言", "body", 4, 6)])
    card = export_screening(doc, tmp_path)
    assert card["modules"]["title"]["text"] == "研究标题"
    assert card["modules"]["abstract"]["text"] == "研究问题与方法\n研究结果"
    assert card["modules"]["abstract"]["line_ids"] == ["p1.b1.l0", "p1.b1.l1"]
    assert card["modules"]["keywords"]["text"] == "社会学；职业"
    assert card["sections"][1]["text"] == "一、引言\n正文内容"
    assert json.loads((tmp_path / "screening.json").read_text(encoding="utf-8")) == card
    assert "研究问题与方法" in (tmp_path / "screening.md").read_text(encoding="utf-8")


def test_unlabeled_abstract_and_keyword_continuation_are_reviewable():
    doc = archive([(20, ["Research title"]),
                   (10, ["Abstract", "Abstract evidence", "More evidence"]),
                   (8, ["# The Author 2026"]),
                   (10, ["Keywords: social work and", "practice"]),
                   (12, ["Introduction", "Body text"])],
                  [(None, "front_matter_or_unknown", 0, 7), ("Introduction", "body", 7, 9)])
    card = build_screening(doc)
    assert card["modules"]["abstract"]["text"] == "Abstract evidence\nMore evidence"
    assert card["modules"]["keywords"]["text"] == "social work and\npractice"

    doc["pages"][0]["blocks"][1]["lines"][0]["text"] = "Unlabeled opening"
    card = build_screening(doc)
    assert card["modules"]["abstract"]["status"] == "missing"
    assert "Unlabeled opening" in card["modules"]["opening_excerpt"]["text"]
