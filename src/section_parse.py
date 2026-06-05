import re
from collections import Counter
from pathlib import Path
import json

# 定义标题格式
heading_patterns = {
    "uppercase": re.compile(r"^[A-Z][A-Z\s\-:&]{2,}$"),
    "titlecase": re.compile(
        r"^[A-Z][A-Za-z\-]*(\s+(?:[A-Z][A-Za-z\-]*|and|or|of|in|on|for|the|to|with))*$"
        ),  # 允许首字母非大写的介词
    "arabic": re.compile(r"^\d+\.?\s+.+$"),
    "arabic_sub": re.compile(r"^\d+\.\d+\.?\s+.+$"),
    "roman": re.compile(r"^[IVXLCDM]+\.\s+.+$"),
    "cn_level1": re.compile(r"^[一二三四五六七八九十百]+、.+$"),
    "cn_level2": re.compile(r"^（[一二三四五六七八九十]+）.+$")
}


def score_heading(lines, idx):
    """
    lines: 全部行
    idx: 当前行号
    pattern_name: 匹配到的模式
    """
    line = lines[idx].strip()
    score = 0
    # 前空行
    if idx > 0 and lines[idx - 1].strip() == "":
        score += 2
    # 后空行
    if idx < len(lines)-1 and lines[idx + 1].strip() == "":
        score += 2
    # 无句号
    if not line.endswith((".", "。")):
        score += 2
    # 长度限制
    if len(line) < 120:
        score += 1

    return score


# 识别标题
def detect_heading_candidates(text):
    lines = text.split("\n")
    candidates = []
    for idx, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        for pattern_name, pattern in heading_patterns.items():
            if pattern.match(line):
                score = score_heading(lines, idx)
                candidates.append({
                    "title": line,
                    "line_number": idx,
                    "pattern": pattern_name,
                    "score": score
                })
                break

    return candidates


# 删除可能出现的页眉页脚
def remove_repeated_headers(candidates):
    title_counter = Counter(c["title"] for c in candidates)
    filtered = []
    for c in candidates:
        if title_counter[c["title"]] >= 3:
            continue
        filtered.append(c)
    return filtered


# 判断标题的主要模式
def infer_main_pattern(candidates):
    if not candidates:
        return None
    pattern_counter = Counter(c["pattern"] for c in candidates)
    return pattern_counter.most_common(1)[0][0]


# 过滤出最有可能的标题格式
def filter_candidates(candidates, main_pattern):
    headings = []
    for c in candidates:
        score = c["score"]
        if c["pattern"] == main_pattern:
            score += 3
        if score >= 6:
            c["final_score"] = score
            headings.append(c)
    return headings


def split_sections(text, headings):
    lines = text.split("\n")
    sections = []
    for i, heading in enumerate(headings):
        start = heading["line_number"]
        if i < len(headings)-1:
            end = headings[i+1]["line_number"]
        else:
            end = len(lines)
        section_text = "\n".join(lines[start:end])
        sections.append({
            "title": heading["title"],
            "text": section_text
        })
    return sections


def section_parse(text):
    candidates = detect_heading_candidates(text)
    candidates = remove_repeated_headers(candidates)
    main_pattern = infer_main_pattern(candidates)
    headings = filter_candidates(candidates, main_pattern)
    sections = split_sections(text, headings)
    return {
        "main_pattern": main_pattern,
        "heading_candidates": candidates,
        "headings": headings,
        "sections": sections
        }


def parse_json(json_file):
    json_path = Path(json_file)
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # 使用 cleaned_text
    text = data.get("cleaned_text")

    result = section_parse(text)
    data["main_pattern"] = result["main_pattern"]
    data["heading_candidates"] = result["heading_candidates"]
    data["headings"] = (result["headings"])
    data["sections"] = result["sections"]

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return data


def main():
    json_dir = Path("data/json")
    for json_file in json_dir.glob("*.json"):
        try:
            result = parse_json(json_file)
            if result is not None:
                print(
                    f"Parsed: {json_file.name} | "
                    f"Sections: {len(result['sections'])}"
                )
        except Exception as e:
            print(f"Error: {json_file.name}")
            print(e)


if __name__ == "__main__":
    main()


# """几点问题：
# 1. sections到底在统计什么？
# 2. 因为论文中的数字没有被清除，数字和后续文本连接在一起，也被判定为是标题。
#   如Abbott的文章中，页码没有被清除，所以页码和下一页的页眉被首先判定为标题。
# > “通过前三页的内容识别出一种标题模式，并固定下来，在后续页数中继续识别”——这种方法是有必要的。
# > 但这种方法同样可能出现上述问题。
# 3. 因为一开始定义的标题模式为多种混合，所以最后识别出来的内容里既有真正的节标题，也有非节标题。
# > 建议还是从前三页中识别出一种主要标题模式。但同时要思考怎么才能避免把各种可能全部识别为标题的情况。

# 我的结论和意见：要么增加标题识别的复杂性，要么引入更复杂的方法。
# """
