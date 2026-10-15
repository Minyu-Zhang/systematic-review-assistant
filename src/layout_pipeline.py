"""Preserve native PDF evidence; use PyMuPDF4LLM for layout suggestions.

Archive JSON is deliberately verbose. Exported model input is a separate view.
No OCR or external LLM is invoked. All page numbers are physical, one-based.
"""

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import re

import pymupdf

from .quality import candidate_issues, normalized, text_health

SCHEMA_VERSION = "layout-0.2"
STANDARD_HEADINGS = {
    "abstract": "abstract", "摘要": "abstract", "提要": "abstract",
    "introduction": "body", "background": "body", "引言": "body", "绪论": "body",
    "methods": "body", "method": "body", "methodology": "body",
    "results": "body", "discussion": "body", "conclusion": "body",
    "conclusions": "body", "结论": "body", "references": "references",
    "bibliography": "references", "参考文献": "references",
    "appendix": "appendix", "appendices": "appendix", "附录": "appendix",
}
NUMBERED = re.compile(r"^(?:\d+(?:\.\d+)*[.、]?\s+|\d+[∙．、]\s*|[IVXLCDM]+\.\s+|[一二三四五六七八九十]+\s*、|[（(][一二三四五六七八九十]+[）)])")


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def extract_native_page(page):
    # Bypass layout interpretation: archive the native text layer, including
    # invisible OCR text. Exclude binary image payloads from the dictionary.
    flags = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES
    textpage = page.get_textpage(flags=flags)
    source = textpage.extractDICT(sort=False)
    blocks = []
    for bi, block in enumerate(source["blocks"]):
        if block["type"] != 0:
            continue
        block_id = f"p{page.number+1}.b{bi}"
        lines = []
        for li, line in enumerate(block["lines"]):
            spans = [{k: s[k] for k in ("text", "bbox", "font", "size", "flags", "origin", "color")
                      if k in s} for s in line["spans"]]
            lines.append({"id": f"{block_id}.l{li}", "page": page.number+1,
                          "block_id": block_id, "bbox": list(line["bbox"]),
                          "direction": list(line["dir"]), "spans": spans,
                          "text": "".join(s["text"] for s in spans),
                          "role": "unknown", "excluded_reason": None})
        blocks.append({"id": block_id, "bbox": list(block["bbox"]), "lines": lines})
    return {"page_number": page.number+1, "width": page.cropbox.width,
            "height": page.cropbox.height, "rotation": page.rotation,
            "coordinate_system": "unrotated PDF points, origin top-left",
            "raw_text": textpage.extractText(sort=False), "blocks": blocks}


def page_lines(page):
    return [line for block in page["blocks"] for line in block["lines"]]


def intersection_fraction(a, b):
    intersection = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    return intersection / max(.001, (a[2]-a[0])*(a[3]-a[1]))


def match_score(line_bbox, box_bbox):
    score = intersection_fraction(line_bbox, box_bbox)
    # Some embedded CJK fonts report oversized ascender/descender boxes.
    # Their centers and horizontal extents are more stable than area overlap.
    cx = (line_bbox[0] + line_bbox[2]) / 2
    cy = (line_bbox[1] + line_bbox[3]) / 2
    horizontal = max(0, min(line_bbox[2], box_bbox[2])-max(line_bbox[0], box_bbox[0]))
    if (box_bbox[0] <= cx <= box_bbox[2] and box_bbox[1] <= cy <= box_bbox[3]
            and horizontal / max(.001, line_bbox[2]-line_bbox[0]) >= .7):
        score = max(score, .75)
    return score


def attach_layout(page, chunk=None, error=None):
    lines = page_lines(page)
    candidate = chunk["text"] if chunk else ""
    boxes = chunk.get("page_boxes", []) if chunk else []
    scores, issues = candidate_issues(page["raw_text"], candidate)
    if error:
        issues.append("layout_error")
    if chunk is None and not error:
        issues.append("layout_disabled")
    if not boxes and chunk:
        issues.append("layout_boxes_missing")
    page["layout"] = {"markdown": candidate if chunk else None, "boxes": boxes,
                      "comparison": scores, "issues": issues, "error": error}
    # Keep every native line even when no model box includes it.
    for line in lines:
        hits = [(match_score(line["bbox"], box["bbox"]), i) for i, box in enumerate(boxes)]
        best = max(hits, default=(0, -1))
        line["layout_box"] = best[1] if best[0] >= .5 else None
        line["layout_class"] = boxes[best[1]]["class"] if best[0] >= .5 else None
    unmatched = [line["id"] for line in lines if line["layout_box"] is None]
    if chunk and unmatched:
        issues.append("unmapped_native_lines")
    # Lossy pages use native stream order. No blind y/x sort across columns.
    trusted = chunk is not None and not issues
    ordered = sorted(lines, key=lambda x: x["layout_box"]) if trusted else lines
    page["reading_order"] = [line["id"] for line in ordered]
    page["reading_order_source"] = "layout_boxes" if trusted else "native_stream"
    page["unmapped_line_ids"] = unmatched
    health = text_health(page["raw_text"])
    page["quality"] = health | {
        "needs_ocr_review": health["alnum_chars"] < 100 or health["suspicious_unicode_ratio"] > .02,
        "needs_reading_order_review": bool(issues),
    }


def mark_artifacts(pages):
    """Conservative, reversible exclusions; never delete numbers in the body."""
    occurrences = defaultdict(set)
    for page in pages:
        for line in page_lines(page):
            y0, y1 = line["bbox"][1], line["bbox"][3]
            margin = y1 < page["height"] * .12 or y0 > page["height"] * .88
            line["in_margin"] = margin
            if margin and normalized(line["text"]):
                key = re.sub(r"\d+", "#", normalized(line["text"]))
                occurrences[key].add(page["page_number"])
    for page in pages:
        seen = {}
        for line in page_lines(page):
            text = line["text"].strip()
            key = (text, tuple(round(v, 1) for v in line["bbox"]))
            if text and key in seen:
                line["excluded_reason"] = "duplicate_at_same_position"
                line["duplicate_of"] = seen[key]
            else:
                seen[key] = line["id"]
            if line["in_margin"]:
                repeated = re.sub(r"\d+", "#", normalized(text))
                if re.fullmatch(r"(?:[Pp]age\s*|p\.\s*)?[-–—]?\s*\d+\s*[-–—]?", text):
                    line["excluded_reason"] = "margin_page_number"
                elif len(occurrences[repeated]) >= 3 and len(text) <= 180:
                    line["excluded_reason"] = "repeated_margin_text"
            if line["excluded_reason"]:
                line["role"] = "artifact"


def heading_kind(text):
    key = normalized(text)
    if key in STANDARD_HEADINGS:
        return STANDARD_HEADINGS[key]
    if re.fullmatch(r"(?:appendix|附录)\s*[A-Z一二三\d](?:\s*[:：.].{1,80})?", text, re.I):
        return "appendix"
    return None


def build_sections(pages):
    """Use model headings plus native typography; keep unknown/preamble text.

    These are proposals for review, not gold labels. Section membership covers
    every non-artifact native line exactly once, even when no heading exists.
    """
    sections, candidates = [], []
    current = None
    body_started = False
    size_weights = Counter()
    for page in pages:
        for line in page_lines(page):
            for span in line["spans"]:
                size_weights[round(span["size"], 1)] += len(normalized(span["text"]))
    body_size = size_weights.most_common(1)[0][0] if size_weights else 0
    for page in pages:
        lookup = {line["id"]: line for line in page_lines(page)}
        cover = (page["page_number"] == 1 and "Your use of the JSTOR archive" in page["raw_text"]
                 and "Author(s)" in page["raw_text"])
        units = []
        for line_id in page["reading_order"]:
            line = lookup[line_id]
            if line["excluded_reason"]:
                continue
            if (units and line["layout_class"] == "section-header"
                    and units[-1][-1]["layout_class"] == "section-header"
                    and line["layout_box"] == units[-1][-1]["layout_box"]):
                units[-1].append(line)
            else:
                units.append([line])
        for unit in units:
            line = unit[0]
            line_id = line["id"]
            text = " ".join(l["text"].strip() for l in unit).strip()
            kind = heading_kind(text)
            numbered = bool(NUMBERED.match(text))
            styled = any(s["flags"] & 18 for l in unit for s in l["spans"])
            larger = any(s["size"] >= body_size + .4 for l in unit for s in l["spans"])
            model_heading = line["layout_class"] == "section-header"
            acceptable = (0 < len(text) <= 140 and "。" not in text and not text.endswith((";", "；"))
                          and not re.match(r"^(table|figure|表\s*\d|图\s*\d|https?://)", text, re.I))
            # Exact standard headings work on OCR layers even without styling.
            accepted = not cover and acceptable and (
                kind is not None or (model_heading and (numbered or (body_started and (styled or larger))))
                or (numbered and styled and len(text) < 90))
            if model_heading or kind or numbered:
                candidates.append({"line_id": line_id, "page": page["page_number"],
                                   "text": text, "line_ids": [l["id"] for l in unit], "accepted": accepted,
                                   "evidence": {"model_heading": model_heading, "bold_or_italic": styled,
                                                "larger_than_body": larger, "body_font_size": body_size,
                                                "standard_name": kind, "numbered": numbered}})
            if accepted:
                # Keep bibliography content separate until an explicit appendix.
                section_kind = kind or ("references" if current and current["kind"] == "references" else "body")
                current = {"id": f"s{len(sections)}", "title": text, "kind": section_kind,
                           "heading_line_id": line_id, "heading_line_ids": [l["id"] for l in unit],
                           "line_ids": [], "needs_review": True}
                sections.append(current)
                body_started = True
                for l in unit:
                    l["role"] = "heading"
            elif current is None or (current["kind"] == "cover" and not cover):
                current = {"id": f"s{len(sections)}", "title": None,
                           "kind": "cover" if cover else "front_matter_or_unknown",
                           "heading_line_id": None, "line_ids": [], "needs_review": True}
                sections.append(current)
            for l in unit:
                current["line_ids"].append(l["id"])
                l["section_id"] = current["id"]
                if l["role"] == "unknown":
                    l["role"] = "text"
    return sections, candidates


def parse_pdf(path, use_layout=True):
    path = Path(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with pymupdf.open(path) as doc:
        if doc.needs_pass:
            raise ValueError("Password-protected PDF is not supported without unlocking it first")
        pages = [extract_native_page(page) for page in doc]
        metadata = dict(doc.metadata or {})
        toc = doc.get_toc()
    # Separate document instance protects the raw extraction from parser changes.
    if use_layout:
        import pymupdf4llm
        pymupdf4llm.use_layout(True)
        with pymupdf.open(path) as doc:
            for i, page in enumerate(pages):
                try:
                    chunks = pymupdf4llm.to_markdown(doc, pages=[i], page_chunks=True,
                                                   use_ocr=False, force_text=True,
                                                   header=True, footer=True)
                    if len(chunks) != 1 or chunks[0]["metadata"]["page_number"] != i+1:
                        raise ValueError("Unexpected page mapping from layout parser")
                    attach_layout(page, chunks[0])
                except Exception as exc:
                    attach_layout(page, error=f"{type(exc).__name__}: {exc}")
    else:
        for page in pages:
            attach_layout(page)
    mark_artifacts(pages)
    sections, candidates = build_sections(pages)
    result = {
        "schema_version": SCHEMA_VERSION, "document_id": digest,
        "source": {"file_name": path.name, "sha256": digest, "bytes": path.stat().st_size},
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "parser": {"pymupdf": version("pymupdf"),
                   "pymupdf4llm": version("pymupdf4llm") if use_layout else None,
                   "ocr_executed": False, "layout_enabled": use_layout,
                   "coverage_character_threshold": .97, "coverage_ngram_threshold": .90},
        "metadata": metadata, "page_count": len(pages), "toc": toc,
        "pages": pages, "sections": sections, "heading_candidates": candidates,
    }
    validate_document(result)
    return result


def validate_document(document):
    """Fail before export if source references or section coverage are broken."""
    all_ids, active = [], []
    for page in document["pages"]:
        lines = page_lines(page)
        ids = [line["id"] for line in lines]
        if Counter(ids) != Counter(page["reading_order"]):
            raise ValueError("Reading order must include each native line once")
        for line in lines:
            if line["text"] != "".join(s["text"] for s in line["spans"]):
                raise ValueError("Span text does not reconstruct source line")
            if not line["excluded_reason"]:
                active.append(line["id"])
        all_ids.extend(ids)
    if len(set(all_ids)) != len(all_ids):
        raise ValueError("Duplicate source IDs")
    section_ids = [line_id for s in document["sections"] for line_id in s["line_ids"]]
    if Counter(active) != Counter(section_ids):
        raise ValueError("Sections must cover every non-artifact line exactly once")


def model_payload(document, exclude_references=False):
    """One copy of text, grouped by source block, with compact source markers.

    The manifest maps each output character interval back to exact native lines.
    No coordinates or repeated full_text/page_texts are sent to the model.
    """
    section_kinds = {s["id"]: s["kind"] for s in document["sections"]}
    parts, manifest, offset = [], [], 0
    for page in document["pages"]:
        lookup = {line["id"]: line for line in page_lines(page)}
        group = []

        def flush():
            nonlocal offset
            if not group:
                return
            first = group[0]
            marker = f"[{first['block_id']}]\n"
            parts.append(marker)
            offset += len(marker)
            for line in group:
                projected = project_line(line["text"])
                text = projected + "\n"
                manifest.append({"start": offset, "end": offset+len(projected),
                                 "line_id": line["id"], "page": page["page_number"],
                                 "bbox": line["bbox"], "section_id": line["section_id"],
                                 "transformations": ["control_characters_to_spaces"] if projected != line["text"] else []})
                parts.append(text)
                offset += len(text)
            parts.append("\n")
            offset += 1
            group.clear()

        for line_id in page["reading_order"]:
            line = lookup[line_id]
            skip = bool(line["excluded_reason"]) or (exclude_references and section_kinds.get(line.get("section_id")) == "references")
            if skip:
                continue
            if group and group[-1]["block_id"] != line["block_id"]:
                flush()
            group.append(line)
        flush()
    return "".join(parts), {"document_id": document["document_id"],
                            "offset_unit": "Unicode code points", "spans": manifest,
                            "exclude_references": exclude_references}


def project_line(text):
    """Sanitize controls in model input only; never delete numeric body lines."""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)
