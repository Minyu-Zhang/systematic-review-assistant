from pathlib import Path
import pymupdf4llm

# Disable AI layout analysis
# pymupdf4llm.use_layout(False)


def convert_pdf_to_md(pdf_file):
    pdf_path = Path(pdf_file)

    markdown = pymupdf4llm.to_markdown(
        str(pdf_path)
    )

    output_dir = Path("data/markdown")
    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    output_path = output_dir / f"{pdf_path.stem}.md"

    with open(
        output_path,
        "w",
        encoding="utf-8"
    ) as f:
        f.write(markdown)

    return markdown


def main():
    pdf_dir = Path("data/pdf")

    for pdf_file in pdf_dir.glob("*.pdf"):
        try:
            markdown = convert_pdf_to_md(pdf_file)

            print(
                f"Processed: {pdf_file.name} | "
                f"Chars: {len(markdown)}"
            )

        except Exception as e:
            print(
                f"Error: {pdf_file.name}"
            )
            print(e)


if __name__ == "__main__":
    main()
