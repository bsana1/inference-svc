# inference-svc

Reference scripts demonstrating retrieval-augmented generation (RAG) over documents using
[Azure AI Search](https://learn.microsoft.com/azure/search/) and Azure OpenAI. These are
standalone demos, not a deployable service — kept here for reference.

## What's in here

- **`azure-search-ai-rag.py`** — minimal script: runs a fixed list of questions against an
  Azure AI Search index and answers each one with Azure OpenAI, grounded only in the
  retrieved chunks.
- **`azure-search-asservice.py`** — the same RAG pattern wrapped in a small Flask API with
  two endpoints:
  - `POST /upload` — uploads a PDF to Azure Blob Storage, triggers the search indexer, and
    waits for indexing to finish.
  - `POST /ask` — retrieves relevant chunks for a question and answers it with Azure OpenAI.
- **`azure-search-skillset-ada-02.json`** / **`azure-search-skillset-text-large-03.json`** —
  Azure AI Search [skillset](https://learn.microsoft.com/azure/search/cognitive-search-working-with-skillsets)
  definitions used to chunk documents and generate embeddings (via `text-embedding-ada-002`
  and `text-embedding-3-large` respectively) when building the search index. Import these
  through the Azure portal or the Search REST API — fill in `resourceUri` and `apiKey` with
  your own Azure OpenAI resource first.

## Prerequisites

- An Azure AI Search service with an index already created (see the skillset JSON files for
  how documents are chunked and embedded).
- An Azure OpenAI resource with a `gpt-4o` chat deployment (and an embeddings deployment for
  index building).
- Optionally, an Azure Storage account (only needed for `/upload` in `azure-search-asservice.py`).
- An OpenAI-compatible API key for `azure-search-asservice.py`'s `/ask` endpoint (it calls the
  `openai` SDK directly rather than the Azure OpenAI client).

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # then fill in your own values
```

## Usage

Run the standalone question/answer demo:

```bash
python azure-search-ai-rag.py
```

Run the Flask API:

```bash
python azure-search-asservice.py
# then, e.g.
curl -X POST localhost:5001/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What is this document about?", "filename": "whitepaper.pdf"}'
```

## Note on credentials

Earlier versions of this repo had a real Azure OpenAI key committed in
`azure-search-skillset-ada-02.json`. That Azure subscription no longer exists, but if you
fork or reuse this history, treat that key as compromised and never reuse it.
