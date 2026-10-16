"""Find reviewable cross-paper text comparisons directly from PDF text.

Run from the project root: python -m src.contrastive_nlp
The scores retrieve candidates; they do not establish agreement or conflict.
"""

import argparse
import json
from pathlib import Path
import re

from sklearn.feature_extraction.text import TfidfVectorizer

from .layout_pipeline import save_json


# Adapted at the method level from scikit-learn's text clustering example and
# KeyBERT's MMR selection. No source code from those projects is copied here.
METHOD_SOURCES = {
    "tfidf": "https://scikit-learn.org/stable/auto_examples/text/plot_document_clustering.html",
    "diverse_selection": "https://github.com/MaartenGr/KeyBERT/blob/master/keybert/_mmr.py",
}
ENGLISH_STOP = set("a an and are as at be been but by can do for from had has have in into is it its of on or our that the their there these this those to was were which while with would we they also than such not only more most one two study paper article research results".split())
SKIP_KINDS = {"references", "appendix", "cover"}
ENGLISH_ARGUMENT = re.compile(
    r"\b(?:argue[ds]?|suggest(?:s|ed)?|indicat(?:e|es|ed)|demonstrat(?:e|es|ed)|"
    r"show(?:s|ed)?|find(?:s|ings)?|found|however|whereas|rather than|in contrast|"
    r"therefore|thus|examin(?:e|es|ed)|explor(?:e|es|ed)|propos(?:e|es|ed))\b",
    re.I,
)
CHINESE_ARGUMENT = re.compile(r"本文|本研究|我们|发现|指出|认为|表明|然而|但是|因此|影响|机制|关系|研究表明")
ADMINISTRATIVE = re.compile(
    r"https?://|www\.|jstor|downloaded|copyright|creative commons|"
    r"competing interests|author information|correspondence|grant number|"
    r"university of .* faculty|责任编辑|作者简介|本期新锐|出版社|出版年",
    re.I,
)


def terms(text):
    """Simple English words and Chinese bigrams; no cross-language alignment."""
    result = []
    for chunk in re.findall(r"[a-z][a-z'-]*|[\u4e00-\u9fff]+", text.casefold()):
        if "\u4e00" <= chunk[0] <= "\u9fff":
            result.extend(chunk[i:i + 2] for i in range(len(chunk) - 1))
        else:
            chunk = chunk.strip("-'")
            if len(chunk) > 2 and chunk not in ENGLISH_STOP:
                result.append(chunk)
    return result


def is_substantive(text):
    """Favor argumentative prose and reject obvious publication machinery."""
    if ADMINISTRATIVE.search(text):
        return False
    if len(re.findall(r"\b(?:19|20)\d{2}\b", text)) >= 4:
        return False
    if sum(char.isdigit() for char in text) / max(1, len(text)) > 0.18:
        return False
    return bool(ENGLISH_ARGUMENT.search(text) or CHINESE_ARGUMENT.search(text))


def text_windows(folder, min_terms=25, target_chars=420, max_chars=650):
    """Group adjacent native lines into short page-local windows with exact IDs.

    PDF blocks are not used as paragraphs: several articles have one block per
    printed line, and older articles have unreliable section headings.
    """
    document = json.loads((folder / "document.json").read_text(encoding="utf-8"))
    source = (folder / "model.txt").read_text(encoding="utf-8")
    manifest = json.loads((folder / "model.provenance.json").read_text(encoding="utf-8"))
    if document["document_id"] != manifest["document_id"]:
        raise ValueError(f"Document/provenance ID mismatch: {folder}")
    kinds = {section["id"]: section["kind"] for section in document["sections"]}
    has_cover = any(section["kind"] == "cover" for section in document["sections"])
    result, lines, ids = [], [], []
    page = None

    def flush():
        nonlocal lines, ids
        value = " ".join(lines)
        value = re.sub(r"\s+", " ", value).strip()
        # Recover words broken at a printed line boundary ("pro- fession").
        value = re.sub(r"(?<=[A-Za-z])- (?=[A-Za-z])", "", value)
        if len(terms(value)) >= min_terms and is_substantive(value):
            result.append({"window_id": f"{folder.name}:w{len(result) + 1}",
                           "document_id": document["document_id"],
                           "source_file": document["source"]["file_name"],
                           "page": page, "line_ids": ids[:], "text": value})
        lines, ids = [], []

    for span in manifest["spans"]:
        kind = kinds.get(span.get("section_id"))
        # Cover pages of JSTOR scans often contain licensing text and links.
        if kind in SKIP_KINDS or (has_cover and span["page"] == 1):
            flush()
            page = None
            continue
        value = source[span["start"]:span["end"]].strip()
        if not value:
            continue
        if page is not None and span["page"] != page:
            flush()
        page = span["page"]
        if lines and sum(map(len, lines)) + len(value) > max_chars:
            flush()
        lines.append(value)
        ids.append(span["line_id"])
        if sum(map(len, lines)) >= target_chars and re.search(r"[.!?。！？][\s\"'”’)]*$", value):
            flush()
    flush()
    return result


def describe_pair(left, right, matrix, names, score):
    a = matrix.getrow(left["index"])
    b = matrix.getrow(right["index"])
    wa = dict(zip(a.indices, a.data))
    wb = dict(zip(b.indices, b.data))
    shared = sorted(wa.keys() & wb.keys(), key=lambda i: wa[i] + wb[i], reverse=True)
    a_only = sorted(wa.keys() - wb.keys(), key=wa.get, reverse=True)
    b_only = sorted(wb.keys() - wa.keys(), key=wb.get, reverse=True)
    return {"similarity": round(float(score), 4),
            "shared_terms": [names[i] for i in shared[:8]],
            "left_distinctive_terms": [names[i] for i in a_only[:8]],
            "right_distinctive_terms": [names[i] for i in b_only[:8]],
            "left": {key: value for key, value in left.items() if key != "index"},
            "right": {key: value for key, value in right.items() if key != "index"}}


def candidate_pairs(windows, threshold=0.15):
    """Retrieve cross-document neighbors; keep sparse matrix operations sparse."""
    if len(windows) < 2:
        return [], 0
    vectorizer = TfidfVectorizer(analyzer=terms, min_df=2,
                                 max_df=1.0 if len(windows) < 4 else 0.9,
                                 sublinear_tf=True, norm="l2")
    matrix = vectorizer.fit_transform(item["text"] for item in windows)
    indexed = [dict(item, index=i) for i, item in enumerate(windows)]
    names = vectorizer.get_feature_names_out()
    matches = (matrix @ matrix.T).tocoo()
    candidates = []
    for i, j, score in zip(matches.row, matches.col, matches.data):
        if i >= j or score < threshold or indexed[i]["document_id"] == indexed[j]["document_id"]:
            continue
        pair = describe_pair(indexed[i], indexed[j], matrix, names, score)
        if len(pair["shared_terms"]) >= 2:
            candidates.append(pair)
    return candidates, matrix.shape[1]


def choose_diverse(candidates, limit=12):
    """MMR-style reranking: reward similarity and penalize repeated examples."""
    remaining = sorted(candidates, key=lambda item: item["similarity"], reverse=True)[:500]
    selected, used_windows = [], set()
    while remaining and len(selected) < limit:
        choices = []
        for index, item in enumerate(remaining):
            ids = {item["left"]["window_id"], item["right"]["window_id"]}
            if ids & used_windows:
                continue
            pair = frozenset((item["left"]["document_id"], item["right"]["document_id"]))
            redundancy = max((0.6 * (pair == frozenset((old["left"]["document_id"],
                                                          old["right"]["document_id"]))) +
                              0.4 * len(set(item["shared_terms"]) & set(old["shared_terms"])) /
                              max(1, len(set(item["shared_terms"]) | set(old["shared_terms"])))
                              for old in selected), default=0)
            choices.append((0.8 * item["similarity"] - 0.2 * redundancy, -index, index))
        if not choices:
            break
        index = max(choices)[2]
        item = remaining.pop(index)
        selected.append(item)
        used_windows.update((item["left"]["window_id"], item["right"]["window_id"]))
    return selected


def report_markdown(result):
    lines = ["# 跨文献文本对照实验", "", "相似度只用于寻找候选；独有词只是词汇差异，不能判定观点冲突。", "",
             f"文献：{result['documents']} 篇；文本片段：{result['windows']} 个；候选对：{result['candidates']} 对；展示：{len(result['pairs'])} 对。", "",
             "方法：TF-IDF 余弦相似度；MMR 式去重复选择。中文双字片段与英文词分别计数，尚无跨语言语义对齐。", ""]
    for number, pair in enumerate(result["pairs"], 1):
        lines.extend([f"## {number}. 相似度 {pair['similarity']:.4f}", "",
                      f"共同词：{', '.join(pair['shared_terms'])}", "",
                      f"左侧独有词：{', '.join(pair['left_distinctive_terms'])}", "",
                      f"右侧独有词：{', '.join(pair['right_distinctive_terms'])}", ""])
        for label, side in (("左", pair["left"]), ("右", pair["right"])):
            lines.extend([f"### {label}：{side['source_file']}", "",
                          f"PDF 第 {side['page']} 页；来源行：{side['line_ids'][0]} 至 {side['line_ids'][-1]}"
                          f"（共 {len(side['line_ids'])} 行；完整列表见 JSON）", "",
                          f"> {side['text']}", ""])
    lines.extend(["## 借鉴的方法", "",
                  f"- TF-IDF 文献聚类示例：{METHOD_SOURCES['tfidf']}",
                  f"- KeyBERT 的 MMR 多样性选择：{METHOD_SOURCES['diverse_selection']}", ""])
    return "\n".join(lines)


def run(input_root, output_root, limit=12, threshold=0.15):
    files = sorted(Path(input_root).glob("*/document.json"))
    if not files:
        raise ValueError(f"No document.json files under {input_root}")
    windows = [window for file in files for window in text_windows(file.parent)]
    candidates, vocabulary = candidate_pairs(windows, threshold)
    result = {"schema_version": "contrastive-nlp-0.1", "documents": len(files),
              "windows": len(windows), "vocabulary": vocabulary,
              "candidates": len(candidates), "pairs": choose_diverse(candidates, limit),
              "method_sources": METHOD_SOURCES,
              "limits": ["No cross-language semantic alignment", "No agreement or contradiction inference",
                         "PDF section labels can be wrong; source lines require human checking"]}
    output = Path(output_root)
    save_json(output / "contrastive-pairs.json", result)
    (output / "contrastive-pairs.md").write_text(report_markdown(result), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/processed"))
    parser.add_argument("--output", type=Path, default=Path("data/processed"))
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--threshold", type=float, default=0.15)
    args = parser.parse_args()
    result = run(args.input, args.output, args.limit, args.threshold)
    print(json.dumps({key: value for key, value in result.items() if key != "pairs"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
