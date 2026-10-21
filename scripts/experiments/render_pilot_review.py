"""Validate and render the assistant-authored pilot notes against archived lines.

This does not extract claims or call a model. It renders a separately authored review.
"""

import argparse
import hashlib
import json
from pathlib import Path


def render(root):
    review = json.loads((root / "assistant-review.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in (root / "evidence.jsonl").read_text(encoding="utf-8").splitlines()]
    indices = {row["evidence_id"]: index for index, row in enumerate(rows)}
    if len(indices) != len(rows):
        raise ValueError("Duplicate evidence IDs")
    sources = {}
    for document in manifest["documents"]:
        folder = Path(manifest["input_root"]) / document["archive"]
        for name, expected_hash in document["archive_hashes"].items():
            if hashlib.sha256((folder / name).read_bytes()).hexdigest() != expected_hash:
                raise ValueError(f"Source changed since preparation: {folder / name}")
        source = (folder / "model.txt").read_text(encoding="utf-8")
        spans = json.loads((folder / "model.provenance.json").read_text(encoding="utf-8"))["spans"]
        sources[document["alias"]] = (document["document_id"], source, {s["line_id"]: s for s in spans})
    for row in rows:
        alias, line_id = row["evidence_id"].split(":", 1)
        doc_id, source, spans = sources[alias]
        span = spans[line_id]
        if (row["document_id"] != doc_id or row["line_id"] != line_id or
                any(row[key] != span[key] for key in ("start", "end", "page")) or
                row["text"] != source[span["start"]:span["end"]]):
            raise ValueError(f"Evidence differs from original source: {row['evidence_id']}")
    claims = {claim["id"]: claim for claim in review["claims"]}
    if len(claims) != len(review["claims"]):
        raise ValueError("Duplicate claim IDs")
    evidence = {}
    for claim in claims.values():
        selected = {}
        for start, end in claim["ranges"]:
            a, b = indices[start], indices[end]
            if a > b:
                raise ValueError("Reversed evidence range")
            for row in rows[a:b+1]:
                if row["evidence_id"].split(":")[0] != claim["document"]:
                    raise ValueError("Evidence range crosses document")
                selected[row["evidence_id"]] = row
        if not selected:
            raise ValueError("Claim has no evidence")
        evidence[claim["id"]] = list(selected.values())
    expected_pairs = json.loads((root / "pairs.json").read_text(encoding="utf-8"))
    actual = [(r["pair_id"], r["left"], r["right"]) for r in review["relations"]]
    expected = [(r["pair_id"], r["left"], r["right"]) for r in expected_pairs]
    if actual != expected:
        raise ValueError("Comparison does not cover the selected pairs exactly once")
    for relation in review["relations"]:
        documents = {claims[key]["document"] for key in relation["claims"]}
        if documents != {relation["left"], relation["right"]}:
            raise ValueError("Relation lacks evidence from both papers")
    relation_ids = {r["pair_id"] for r in review["relations"]}
    for item in review["topics"] + review["questions"]:
        if not set(item["relations"]) <= relation_ids:
            raise ValueError("Unknown relation reference")
    validation = {"claims": len(claims), "pairs": len(actual),
                  "unique_cited_lines": len({r["evidence_id"] for v in evidence.values() for r in v}),
                  "source_id_validation": "passed", "human_validation": "not_done",
                  "semantic_support": "assistant_review_only", "external_api_calls": 0}
    (root / "review-evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (root / "review-validation.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# 六篇试点论文：助手初步阅读工作记录", "", review["coverage"], "",
             "本文件是便于核对的内部工作记录，Markdown 不是已确定的最终产品格式。分析由当前对话助手撰写；本地脚本只整理材料、校验引用和生成此阅读副本。", "",
             "## 文献清单", "", "| 代号 | 论文 | PDF页数 |", "| --- | --- | --- |"]
    for document in manifest["documents"]:
        lines.append(f'| {document["alias"]} | {document["source_file"]} | {document["pages"]} |')
    lines += ["", "## 关系总览", "", "15 对均作了初步比较，其中的理论连接与条件张力是助手解释，不代表已确认的引用关系、因果关系或直接矛盾。", "",
              "| 编号 | 文献对 | 关系 | 初步判断 | 边界与证据 |", "| --- | --- | --- | --- | --- |"]
    for rel in review["relations"]:
        refs = "、".join(f'[{key}](#{key.lower()})' for key in rel["claims"])
        lines.append(f'| {rel["pair_id"]} | {rel["left"]} / {rel["right"]} | {"、".join(rel["types"])} | {rel["statement"]} | {rel["limit"]} {refs} |')
    lines += ["", "## 议题详情", ""]
    for topic in review["topics"]:
        lines += [f'### {topic["id"]}：{topic["title"]}', "", topic["assessment"], "", "关联记录：" + "、".join(topic["relations"]), ""]
    lines += ["## 问题线索", "", "以下是基于本次比较提出的待研究问题，没有进行领域新颖性检索。", ""]
    for question in review["questions"]:
        lines += [f'### {question["id"]}：{question["question"]}', "", "依据：" + "、".join(question["relations"]), "", "需补充：" + question["what_to_check"], ""]
    lines += ["## 逐篇要点与证据说明", "", "引用文本直接取自现有 model.txt 的来源映射；保留提取缺字与断行，不作静默补字。页码为 PDF 物理页。", ""]
    for claim in claims.values():
        lines += [f'<a id="{claim["id"].lower()}"></a>', "", f'### {claim["id"]}', "", claim["statement"], "",
                  f'类型：{claim["type"]}。限定：{claim["conditions"]}', "", "原文证据：", ""]
        for row in evidence[claim["id"]]:
            lines.append(f'> [{row["evidence_id"]}] ' + row["text"].replace("\n", "\n> "))
        lines.append("")
    lines += ["## 验证与下一步", "", f'已验证 {len(claims)} 条要点的来源 ID 和 15 个文献对的双方引用；这些机械检查不能证明学术解释正确。', "",
              "外部 API 尚未调用。下一步用相同的中文/英文试点材料对 GLM 与 DeepSeek 做小规模直接分析，再与分阶段方案对照；费用上限和实际调用范围仍待确认。", ""]
    (root / "working-notes.md").write_text("\n".join(lines), encoding="utf-8")
    return validation


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("outputs/pilot-2026-10-21"))
    args = parser.parse_args()
    print(json.dumps(render(args.input), indent=2))
