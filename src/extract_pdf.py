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


# def extract_first_pages(doc):
#     text = []
#     for i in range(min(2, len(doc))):
#         text.append(doc[i].get_text())
#     first_page_texts = "\n".join(text)
#     return first_page_texts

def extract_pages(doc):
    page_texts = []
    for page in doc:
        # 提取当前页的纯文本内容
        text = page.get_text() or ""
        page_texts.append(text)
    return page_texts


# def extract_full_text(page_texts):
#     # texts = []
#     # for page in doc:
#     #     texts.append(page.get_text())
#     # full_text = "\n".join(texts)

#     full_text = "\n".join(page_texts)
#     ocr_need = len(full_text.strip()) < 100  # 如果无法提取，换ocr方法
#     return full_text, ocr_need


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
        page_texts = extract_pages(doc)
        # 另存一个full_text便于后续文本清洗
        full_text = "\n".join(page_texts)
        # 判断是否需要用ocr方法
        ocr_need = len(full_text.strip()) < 100
        # 一些无用小功能
        page_lengths = [len(text) for text in page_texts]

        result = {
            "file_name": pdf_path.name,
            "metadata": metadata,
            "page_count": len(doc),
            "page_texts": page_texts,
            "page_lengths": page_lengths,
            "full_text": full_text,
            "ocr_needed": ocr_need,
            "extracted_at": datetime.now().isoformat(),
            "pdf_path": str(pdf_path),
            "text_length": len(full_text),
            "avg_page_length": (len(full_text) / len(doc))
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
