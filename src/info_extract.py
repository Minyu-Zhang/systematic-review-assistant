"""Build a small, source-linked card for human title/abstract screening.

Run with: python -m src.info_extract --input data/processed
The extraction is a proposal, not an inclusion decision or a full-text analysis.
"""

import argparse
import json
from pathlib import Path
import re

from .layout_pipeline import page_lines, project_line, save_json, validate_document


ABSTRACT_LABEL = re.compile(r"^\s*(?:abstract|a\s+b\s+s\s+t\s+r\s+a\s+c\s+t|摘要|提要|内容提要)(?:\s*[:：]\s*(.*)|\s*)$", re.I)
KEYWORDS_LABEL = re.compile(r"^\s*(?:key\s*words?|关键词|关键字)(?:\s*[:：]\s*(.*)|\s*)$", re.I)
BODY_START = re.compile(r"^\s*(?:(?:\d+(?:\.\d+)*[.、]?|[一二三四五六七八九十]+[、．.])\s*)?(?:introduction|background|引\s*言|绪\s*论)\s*$", re.I)
PUBLICATION_NOTE = re.compile(r"^\s*(?:©|copyright\b|#\s*the author\b|published by\b|downloaded from\b|doi\s*:|advance access\b)", re.I)


def module(lines, source="pdf_text", first_text=None):
    """Keep display text and exact native line IDs together."""
    texts = [project_line(line["text"]).strip() for line in lines]
    if first_text is not None and texts:
        texts[0] = project_line(first_text).strip()
    text = "\n".join(part for part in texts if part)
    return {"status": "candidate" if text else "missing", "text": text or None,
            "source": source if text else None, "line_ids": [line["id"] for line in lines] if text else [],
            "pages": sorted({line["page"] for line in lines}) if text else []}


def article_lines(document):
    """Read up to three article pages, skipping a recognized archive cover."""
    cover_ids = {line_id for section in document["sections"] if section["kind"] == "cover"
                 for line_id in section["line_ids"]}
    pages = [page for page in document["pages"]
             if not all(line["id"] in cover_ids for line in page_lines(page))]
    lines = []
    for page in pages[:3]:
        lookup = {line["id"]: line for line in page_lines(page)}
        lines.extend(lookup[line_id] for line_id in page["reading_order"]
                     if not lookup[line_id]["excluded_reason"] and lookup[line_id]["text"].strip())
    return pages, lines


def labeled_module(lines, label, heading_ids, max_lines):
    for index, line in enumerate(lines):
        match = label.fullmatch(line["text"].strip())
        if not match:
            continue
        tail = match.group(1) or ""
        selected = [line]
        for next_line in lines[index + 1:]:
            if len(selected) >= max_lines or next_line["page"] > line["page"] + 1:
                break
            if (ABSTRACT_LABEL.fullmatch(next_line["text"].strip())
                    or KEYWORDS_LABEL.fullmatch(next_line["text"].strip())
                    or BODY_START.fullmatch(next_line["text"].strip())
                    or (label is ABSTRACT_LABEL and PUBLICATION_NOTE.match(next_line["text"].strip()))
                    or next_line["id"] in heading_ids):
                break
            # Keyword lists normally share one source block; stop before prose.
            if label is KEYWORDS_LABEL and next_line["block_id"] != line["block_id"]:
                break
            selected.append(next_line)
        return module(selected, first_text=tail)
    return module([])


def title_candidate(document, pages, lines):
    metadata_title = (document.get("metadata") or {}).get("title") or ""
    if metadata_title.strip().casefold() not in {"", "untitled", "unknown"}:
        return {"status": "candidate", "text": metadata_title.strip(),
                "source": "pdf_metadata", "line_ids": [], "pages": []}
    if not pages:
        return module([])
    first = pages[0]
    candidates = []
    for block in first["blocks"]:
        block_lines = [line for line in block["lines"] if any(c.isalnum() for c in line["text"])
                       and not line["excluded_reason"] and line["bbox"][1] < first["height"] * .45]
        if not block_lines:
            continue
        text = " ".join(line["text"].strip() for line in block_lines)
        if len(text) < 3 or len(text) > 250:
            continue
        sizes = [(span["size"], len(span["text"].strip())) for line in block_lines for span in line["spans"]]
        weight = sum(length for _, length in sizes)
        if weight:
            candidates.append((sum(size * length for size, length in sizes) / weight, block_lines))
    if not candidates:
        return module([])
    return module(max(candidates, key=lambda item: item[0])[1])


def build_screening(document):
    """Extract front-page modules without inferring relevance or altering the archive."""
    pages, lines = article_lines(document)
    heading_ids = {section.get("heading_line_id") for section in document["sections"]}
    abstract = labeled_module(lines, ABSTRACT_LABEL, heading_ids, 80)
    keywords = labeled_module(lines, KEYWORDS_LABEL, heading_ids, 20)
    opening = module(lines[:25]) if abstract["status"] == "missing" else module([])
    lookup = {line["id"]: line for page in document["pages"] for line in page_lines(page)}
    sections = []
    for section in document["sections"]:
        content = module([lookup[line_id] for line_id in section["line_ids"]])
        sections.append({"id": section["id"], "title": section["title"],
                         "kind": section["kind"], "text": content["text"],
                         "line_ids": content["line_ids"], "pages": content["pages"],
                         "needs_review": section["needs_review"]})
    return {
        "schema_version": "screening-0.1", "document_id": document["document_id"],
        "source_file": document["source"]["file_name"],
        "modules": {"title": title_candidate(document, pages, lines),
                    "abstract": abstract, "keywords": keywords,
                    "opening_excerpt": opening},
        "sections": sections,
        "quality": {
            "ocr_review_pages": [page["page_number"] for page in document["pages"]
                                 if page["quality"]["needs_ocr_review"]],
            "reading_order_review_pages": [page["page_number"] for page in document["pages"]
                                           if page["quality"]["needs_reading_order_review"]],
        },
    }


def screening_markdown(card):
    parts = [f"# 初筛摘录：{card['source_file']}", "", "以下内容均为自动提取候选，需对照 PDF 人工核查；本文件不作纳入或排除判断。"]
    for key, heading in (("title", "标题"), ("abstract", "摘要"),
                         ("keywords", "关键词"), ("opening_excerpt", "首页片段（未识别到摘要时提供）")):
        item = card["modules"][key]
        if key == "opening_excerpt" and item["status"] == "missing":
            continue
        ids = item["line_ids"]
        location = f"{ids[0]} 至 {ids[-1]}" if ids else "无"
        parts.extend(["", f"## {heading}", "", item["text"] or "未识别到",
                      "", f"来源：{item['source'] or '无'}；页码：{', '.join(map(str, item['pages'])) or '无'}；行 ID：{location}"])
    parts.extend(["", "## 章节目录（自动建议）", ""])
    parts.extend(f"- {item['title']}（{item['kind']}，第 {', '.join(map(str, item['pages']))} 页）"
                 for item in card["sections"] if item["title"])
    if not any(item["title"] for item in card["sections"]):
        parts.append("未识别到章节标题")
    return "\n".join(parts) + "\n"


def export_screening(document, output):
    validate_document(document)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    card = build_screening(document)
    save_json(output / "screening.json", card)
    (output / "screening.md").write_text(screening_markdown(card), encoding="utf-8")
    return card


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/processed"))
    args = parser.parse_args()
    files = [args.input] if args.input.is_file() else sorted(args.input.glob("*/document.json"))
    if not files:
        parser.error("No document.json archives found")
    for file in files:
        document = json.loads(file.read_text(encoding="utf-8"))
        export_screening(document, file.parent)
    print(f"Exported {len(files)} screening card(s)")


if __name__ == "__main__":
    main()
