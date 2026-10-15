# systematic-review-assistant
## Overview
An AI-assisted workflow for systematic literature reviews, including structured information extraction, topic discovery, relationship analysis, and knowledge mapping.
The project focuses on transforming unstructured academic literature (PDFs) into structured representations that can be used for literature mapping, topic discovery, relationship analysis, and knowledge visualization.
_**The goal is not to automate literature reviews**_, but to assist researchers in organizing, exploring, and understanding large collections of academic publications.

The project is expected to be used in social sciences (e.g., sociology, demography/population studies, economics, and computational social science).

### Planned General Workflow

```text
PDF
↓
Structured JSON  # Literature Structure Extraction
↓
Embeddings
↓
Topic Clustering / Relationship Discovery
↓
Visualization  # Literature Network / Knowledge Graph
```

## Current Scope (v1.0)
The first development stage focuses on structured information extraction from academic articles.

### Literature Schema v0.1(2026-6-4)

```text
document_metadata
├── file_name
├── page_count
├── creator
├── producer
├── creation_date
├── modification_date
├── pdf_path

bibliographic_metadata
├── title
├── authors
├── journal
├── year
├── doi
├── keywords

research_profile
├── research_topic
├── study_population
├── study_region
├── study_period

conceptual_framework
├── theories
├── concepts
├── variables

methodology
├── data_source
├── sample_size
├── methods
├── models

results
├── findings
├── limitations
├── research_gap

sections
├── abstract
├── introduction
├── methods
├── results
├── discussion
├── conclusion

citations
```

_The schema is designed to capture core research elements from academic literature and provide a structured foundation for subsequent topic clustering, relationship discovery, and knowledge mapping._

## Directory Structure(in Progress)
```text
systematic-review-assistant/

├── data/
├── src/
├── tests/
└── README.md
```

## Project Status

### Reproducible parsing baseline (2026-10-15)

An evidence-preserving pipeline is available alongside the original prototype.
It archives native page/block/line/span text and layout, checks each page against
PyMuPDF4LLM output, and exports concise model text with local provenance.
Markdown is optional. OCR and research-information extraction are not implemented.

```powershell
& .venv-review/Scripts/python.exe -X utf8 -m pytest -q
& .venv-review/Scripts/python.exe -X utf8 -m src.pipeline --markdown
& .venv-review/Scripts/python.exe -X utf8 -m scripts.evaluate_corpus --tokens
```

For environment setup, output schema, measured token counts, known limitations,
and the 11-document / 167-page baseline, see
[the parsing report](docs/parsing-baseline-2026-10-15.md).
Machine-readable results are in `reports/baseline/`; local full-text outputs are
in `data/processed/`. `requirements-lock.txt` records the tested environment.

The status and to-do list below describe the earlier June prototype.

**Current stage:**

- Design completed
- Primary PDF processing(from PDF parsing to JSON export) completed and tested
- Other functions(e.g., OCR/LLM using) is in progress
- Primary text-cleaning process completed

**To-do list**
1. extract_pdf:
- OCR pipeline(not necessary temporarily)
2. clean_text:
- Section parsing
3. other:
- Information extraction/LLM-based structure extraction
- Schema construction
- Literature matrix generation
- Embedding generation
- Topic clustering
- Relationship discovery
- Knowledge graph visualization

## License

MIT License
