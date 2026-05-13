# House Journals Research Assistant - Brev Launchable

This app is a partner-facing research UI over the NVIDIA RAG Blueprint. It lets a user ask grounded questions over indexed Pennsylvania House Journal PDFs, see retrieved sources, upload more PDFs, and use an exact bill lookup index for questions like `Tell me about HB 41`.

## What Runs

- Custom House Journals web UI on port `5056`
- Metadata index for exact bill lookup, built from local PDF files
- NVIDIA RAG Blueprint backend, expected at `RAG_API_URL`
- NVIDIA RAG Blueprint ingestor, expected at `INGESTOR_API_URL`

The UI does not store NVIDIA API keys. The key is needed by the RAG Blueprint services.

## Required Environment Variables

```bash
export NVIDIA_API_KEY="nvapi-..."
export RAG_API_URL="http://127.0.0.1:8081/v1/generate"
export INGESTOR_API_URL="http://127.0.0.1:8082/v1/documents"
export RAG_COLLECTION="house_journals_full_demo"
export RAG_MODEL="nvidia/llama-3.3-nemotron-super-49b-v1.5"
export HOUSE_JOURNALS_SAMPLE_DIR="/opt/house-journals/HouseJournalSample"
export HOUSE_JOURNALS_INDEX_DB="/opt/house-journals/app/data/house_journals_index.sqlite"
export HOUSE_JOURNALS_START_DATE="20250101"
export HOUSE_JOURNALS_END_DATE="20261231"
export HOUSE_JOURNALS_LATEST_COUNT="0"
```

## Brev Launchable Setup

Use these settings in Brev:

- Name: `NVIDIA Legislative Research Assistant`
- Compute: CPU is enough when using NVIDIA-hosted endpoints; use GPU only if self-hosting models
- RAM: `32 GB` minimum, `64 GB` preferred for larger PDF corpora
- Disk: `200 GB` minimum, `500 GB` if packaging many PDFs
- Exposed port: `5056`
- Setup script: `scripts/setup.sh`
- Run command: `scripts/run.sh`

## First-Time Instance Setup

```bash
cd /opt/house-journals/app
cp .env.example .env
# Edit .env and add the RAG endpoints / key values supplied for the demo.
./scripts/setup.sh
./scripts/run.sh
```

Open the exposed Brev port for `5056`.

## Sample Partner Demo Questions

Ask exactly these from the UI:

- `Tell me about HB 41`
- `What bills address environmental issues?`
- `What bills are still in committee?`
- `Which bills were referred to the Education committee?`

Off-topic examples should be refused:

- `What is the weather today?`
- `Who won the football game?`
- `Tell me about California bills`

## Packaging PDFs

For external sharing, only package approved public documents. Recommended path inside Brev:

```bash
/opt/house-journals/HouseJournalSample
```

Then build the exact bill lookup index:

```bash
source .venv/bin/activate
python scripts/build_metadata_index.py \
  --pdf-dir /opt/house-journals/HouseJournalSample \
  --db /opt/house-journals/app/data/house_journals_index.sqlite
```

For the demo, setup indexes the 2025-2026 slice by default. This keeps the demo focused while preserving important examples like `HB 41`. Set `HOUSE_JOURNALS_START_DATE`, `HOUSE_JOURNALS_END_DATE`, or `HOUSE_JOURNALS_LATEST_COUNT` to change the sample selection.

The RAG corpus also needs those same PDFs ingested into the NVIDIA RAG Blueprint collection. The UI's `Add Journal PDFs` button can send more PDFs to the ingestor when `INGESTOR_API_URL` is reachable.

## What To Share With External Partners

Share only the Brev Launchable URL and usage instructions. Do not share personal API keys in the repository. Use one of:

- partner-provided NVIDIA API key
- a temporary limited demo key
- a controlled backend/service key managed by the launchable owner

## Validation Checklist

Before sharing externally:

- UI opens on port `5056`
- Indexed PDFs appear in the left panel
- 2025-2026 demo PDFs are indexed, or the selected demo corpus is clearly shown
- A list question returns a markdown table with source files
- Off-topic questions are refused
- Stop button interrupts long UI requests
- Upload button is either working or intentionally disabled/documented
