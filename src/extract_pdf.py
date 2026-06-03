import fitz
import json
from pathlib import Path
from datetime import datetime

# pdf_file = r"data/pdf/test.pdf"
# pdf_path = Path(pdf_file)
# doc = fitz.open(pdf_path)

# output_dir = Path("data/json")
# output_dir.mkdir(parents=True,exist_ok=True)
# output_path = output_dir / f"{pdf_path.stem}.json"


def extract_metadata(doc):
    metadata = dict(doc.metadata)
    return metadata


def extract_first_pages(doc):
    text = []
    for i in range(min(2, len(doc))):
        text.append(doc[i].get_text())
    first_pages_text = "\n".join(text)
    return first_pages_text


def extract_full_text(doc):
    texts = []
    for page in doc:
        texts.append(page.get_text())
    full_text = "\n".join(texts)

    ocr_need = len(full_text.strip()) < 100  # 如果无法提取，换ocr方法

    return full_text, ocr_need


# 保存结果
def save_json(result, output_path):
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            result,
            f,
            ensure_ascii=False,
            indent=2
        )


def extract_pdf(pdf_file):
    # 打开pdf
    pdf_path = Path(pdf_file)
    doc = fitz.open(pdf_path)

    try:
        # 定义输出路径
        output_dir = Path("data/json")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{pdf_path.stem}.json"

        # 运行上述各函数
        metadata = extract_metadata(doc)
        full_text, ocr_need = extract_full_text(doc)
        first_pages_text = extract_first_pages(doc)
        result = {
            "file_name": pdf_path.name,
            "metadata": metadata,
            "page_count": len(doc),
            "full_text": full_text,
            "first_pages_text": first_pages_text,
            "ocr_needed": ocr_need,
            "extracted_at": datetime.now().isoformat(),
            "pdf_path": str(pdf_path),
            "text_length": len(full_text),
            "first_pages_length": len(first_pages_text)
        }
        save_json(result, output_path)

    finally:
        doc.close()  # 关闭文档

    return result


# 遍历文件夹中的pdf
def main():
    pdf_dir = Path("data/pdf")

    for pdf_file in pdf_dir.glob("*.pdf"):
        try:
            result = extract_pdf(pdf_file)
            print(
                f"Processed: {pdf_file.name} |"
                f"Pages: {result['page_count']} | "
                f"Chars: {result['text_length']} | "
                f"OCR: {result['ocr_needed']}"
                )
        except Exception as e:
            print(f"Error: {pdf_file}")
            print(e)


if __name__ == "__main__":
    main()
