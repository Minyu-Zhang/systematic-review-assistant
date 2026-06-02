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

### v1.0 Workflow:

```text
PDF
↓
Text Extraction
↓
Abstract Extraction
↓
Schema Extraction
↓
JSON Output
```
### Literature Schema v1.0

```{JSON}
{
  "research_question": "",
  "topic": [],
  "theory": [],
  "method": "",
  "data_source": "",
  "sample": "",  # Study Population/respondents(e.g.,Chinese women aged 20–49)
  "country": "",
  "variables": [],
  "findings": []
}
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

**Current stage:**

- Design completed
- Primary PDF processing(from PDF parsing to JSON export) completed
- Test v1.1 for "pdf_extraction.py" is in progress
- Other functions(e.g., OCR/Recognition for title, keywords, etc./LLM using) is in progress

**to-do list**
- OCR pipeline
- LLM-based structure extraction
- Literature matrix generation
- Embedding generation
- Topic clustering
- Relationship discovery
- Knowledge graph visualization

## License

MIT License
