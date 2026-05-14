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
export HOUSE_JOURNALS_CORPUS_URL="https://approved-location/HouseJournalSample.zip"
export HOUSE_JOURNALS_START_DATE="20250101"
export HOUSE_JOURNALS_END_DATE="20261231"
export HOUSE_JOURNALS_LATEST_COUNT="0"
```

## Recommended Brev Setup For Customer Demo

Use these settings in Brev:

- Name: `NVIDIA Legislative Research Assistant`
- Compute: `2x L40S 48GB`
- RAM: `128 GB` preferred
- Disk: `500 GB`
- Exposed port: `5056`
- Setup script: `scripts/setup.sh`
- Run command: `scripts/run.sh`

Why GPU: the RAG Blueprint stack can use GPU Milvus/vector search and the normal
GPU compose path. It also avoids the CPU-only workaround that made the first
ingestion test slow.

## First-Time GPU Instance Setup

```bash
cd /home/ubuntu/house-journals-rag-assistant
cp .env.example .env
# Edit .env and add NVIDIA_API_KEY plus any corpus URL or local PDF folder.
./scripts/setup.sh

# Start the NVIDIA RAG Blueprint services on the GPU instance.
./scripts/start_rag_blueprint_gpu.sh

# Create the collection and ingest the newest indexed PDFs.
./scripts/ingest_house_journals.py \
  --pdf-dir "${HOUSE_JOURNALS_SAMPLE_DIR:-HouseJournalSample}" \
  --db "${HOUSE_JOURNALS_INDEX_DB:-data/house_journals_index.sqlite}" \
  --collection "${RAG_COLLECTION:-house_journals_full_demo}" \
  --latest "${HOUSE_JOURNALS_INGEST_LATEST:-40}"

# Start the custom research UI.
./scripts/run.sh
```

Open the exposed Brev port for `5056`.

For an all-in-one local demo start, after `.env` is filled in:

```bash
./scripts/start_demo_gpu.sh
```

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

For external sharing, only package approved public documents. The easiest repeatable pattern is to host a zip at an approved URL and set `HOUSE_JOURNALS_CORPUS_URL` in the launchable. The zip can contain either:

```bash
HouseJournalSample/*.pdf
```

or PDFs directly at the zip root. Setup will normalize them into the expected folder:

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

The RAG corpus also needs those same PDFs ingested into the NVIDIA RAG Blueprint collection. Use:

```bash
./scripts/ingest_house_journals.py \
  --pdf-dir "$HOUSE_JOURNALS_SAMPLE_DIR" \
  --db "$HOUSE_JOURNALS_INDEX_DB" \
  --collection "$RAG_COLLECTION" \
  --latest 40
```

The UI's `Add Journal PDFs` button can send more PDFs to the ingestor when `INGESTOR_API_URL` is reachable.

## GPU Demo Validation

After `start_rag_blueprint_gpu.sh`, check:

```bash
curl -s "http://127.0.0.1:8081/v1/health?check_dependencies=true"
curl -s "http://127.0.0.1:8082/v1/health?check_dependencies=true"
```

After ingestion, check:

```bash
curl -s "http://127.0.0.1:8082/v1/documents?collection_name=house_journals_full_demo"
```

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
