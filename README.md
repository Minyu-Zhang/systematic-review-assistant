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
Markdown is optional. OCR is not implemented; research-information extraction is described below.

```powershell
& .venv-review/Scripts/python.exe -X utf8 -m pytest -q
& .venv-review/Scripts/python.exe -X utf8 -m src.pipeline --markdown
& .venv-review/Scripts/python.exe -X utf8 -m scripts.evaluate_corpus --tokens
```

### Initial screening extracts

`src.pipeline` also writes `screening.json` and `screening.md` beside each
`document.json`. They collect a title candidate, explicitly labeled abstract and
keywords, and the proposed text of each section. PDF-text modules retain native
line IDs and physical page numbers so a reader can check the PDF; a title taken
from PDF metadata is marked as such.
If no abstract label is found, an opening excerpt is provided for manual review.
These files do not decide whether a paper should be included in a review.

To generate screening extracts from existing archives without parsing PDFs again:

```powershell
& .venv-review/Scripts/python.exe -X utf8 -m src.info_extract --input data/processed
```

### Full-text extraction and exploratory associations

The second screening pass reads all existing `model.txt` files with their native
line IDs. It asks an LLM for the research fields in Schema v0.1 and leaves every
field for human review. All 11 test articles are included. Set `OPENAI_API_KEY`
in the process environment or in the project's Git-ignored `.env` file before
the API run; the key is never written to results. The default model is
`gpt-4o-mini` and can be changed with `--model`.

```powershell
& .venv-review/Scripts/python.exe -X utf8 -m src.fulltext_extract --estimate-only
& .venv-review/Scripts/python.exe -X utf8 -m src.fulltext_extract
```

The first command writes `data/processed/fulltext-estimate.json`: a local
approximation of input tokens, not API usage. The second writes `fulltext.json`
(structured fields, evidence line IDs, review flags), `fulltext.md` (reading
copy), and `fulltext-usage.json` (API-reported tokens) beside each article's
archive. The usage file retains calls from retries. At the root of
`data/processed`, `fulltext-run.json` totals the API
usage, while `fulltext-associations.json` and `.md` show TF-IDF similarity and
exploratory average-link groups from selected extracted fields. Repeated runs
reuse matching extracts; `--force` requests new API calls. An invalid model
answer can still leave `fulltext-usage.json`, so token use remains visible.
The run stops when the API reports exhausted credits and records the remaining
document count in `fulltext-run.json`.
Line-ID checks verify that a cited source exists; researchers must still check
whether it supports the claimed value and make the second inclusion decision.
The test similarity has no bilingual alignment or stopword filtering; its groups
are a pipeline check, not substantive findings.

### Direct text comparison experiment

`src.contrastive_nlp` compares short, source-linked text windows directly from
the 11 PDF archives. It uses local TF-IDF and diverse candidate selection;
the full-text LLM extract and API key are not required.

```powershell
& .venv-review/Scripts/python.exe -X utf8 -m src.contrastive_nlp
```

Review `data/processed/contrastive-pairs.md` with the PDFs; the matching JSON
retains every native line ID. Scores suggest passages to compare, not agreement,
contradiction, or research gaps. The [experiment report](docs/contrastive-experiment-2026-10-16.md)
records results, false positives, and the external methods used.

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
