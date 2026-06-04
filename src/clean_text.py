import re
from pathlib import Path
import json


# 去除控制字符
def remove_control_chars(text):
    return re.sub(
        r"[\x00-\x08\x0B\x0C\x0E-\x1F]",  # 删除ASCII控制字符
        "",
        text
    )


# 换行符
def normalize_newlines(text):
    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")
    return text


# 空行和空格
def normalize_whitespace(text):
    lines = []
    for line in text.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).strip()
        lines.append(line)

    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text


def remove_page_numbers(text):
    patterns = [
        r"^\d+$",
        r"^-+\s*\d+\s*-+$",
        r"^Page\s+\d+$",
        r"^page\s+\d+$",
        r"^p\.\s*\d+$"
    ]

    cleaned_lines = []
    # 逐行删除符合页码格式的内容
    for line in text.split("\n"):
        matched = False
        for pattern in patterns:
            if re.match(pattern, line.strip()):
                matched = True
                break
        if not matched:
            cleaned_lines.append(line)

    return "\n".join(cleaned_lines)


def clean_text(text):
    text = remove_control_chars(text)
    text = normalize_newlines(text)
    text = remove_page_numbers(text)
    text = normalize_whitespace(text)
    return text


def clean_json(json_file):
    json_path = Path(json_file)
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 新增“cleaned_text”存储处理后的full_text
    cleaned_text = clean_text(data["full_text"])
    # cleaned_text = clean_text(data.get("full_text", ""))?
    data["cleaned_text"] = cleaned_text

    # 新增“cleaned_page_text”存储清洗后的page_texts
    cleaned_page_texts = []
    for page in data["page_texts"]:
        # for page in data.get("page_texts", []):
        cleaned_page_texts.append(clean_text(page))
    data["cleaned_page_texts"] = cleaned_page_texts

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return data


# 遍历文件夹中的每个json
def main():
    json_dir = Path("data/json")

    for json_file in json_dir.glob("*.json"):
        try:
            clean_json(json_file)
            print(f"Cleaned: {json_file.name}")

        except Exception as e:
            print(f"Error: {json_file.name}")
            print(e)


if __name__ == "__main__":
    main()
