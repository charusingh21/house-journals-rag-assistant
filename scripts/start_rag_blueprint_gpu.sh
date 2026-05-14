#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

RAG_DIR="${RAG_BLUEPRINT_DIR:-$HOME/rag}"
RAG_REPO_URL="${RAG_REPO_URL:-https://github.com/NVIDIA-AI-Blueprints/rag.git}"
COLLECTION_NAME="${RAG_COLLECTION:-house_journals_full_demo}"

if [ -z "${NVIDIA_API_KEY:-${NGC_API_KEY:-}}" ]; then
  echo "NVIDIA_API_KEY or NGC_API_KEY is required before starting the RAG Blueprint."
  exit 1
fi

export NGC_API_KEY="${NGC_API_KEY:-$NVIDIA_API_KEY}"
export NVIDIA_API_KEY="${NVIDIA_API_KEY:-$NGC_API_KEY}"
export COLLECTION_NAME

if [ ! -d "$RAG_DIR/.git" ]; then
  echo "Cloning NVIDIA RAG Blueprint into $RAG_DIR"
  git clone "$RAG_REPO_URL" "$RAG_DIR"
fi

cd "$RAG_DIR"

echo "$NGC_API_KEY" | docker login nvcr.io -u '$oauthtoken' --password-stdin >/dev/null

set -a
source deploy/compose/.env
source deploy/compose/nvdev.env
set +a

export NVIDIA_API_KEY
export NGC_API_KEY
export COLLECTION_NAME
export MILVUS_VERSION="${MILVUS_VERSION:-v2.6.5-gpu}"
export APP_LLM_MODELNAME="${RAG_MODEL:-${APP_LLM_MODELNAME:-nvidia/llama-3.3-nemotron-super-49b-v1.5}}"
export APP_FILTEREXPRESSIONGENERATOR_MODELNAME="${APP_FILTEREXPRESSIONGENERATOR_MODELNAME:-$APP_LLM_MODELNAME}"
export APP_QUERYREWRITER_MODELNAME="${APP_QUERYREWRITER_MODELNAME:-$APP_LLM_MODELNAME}"
export SUMMARY_LLM="${SUMMARY_LLM:-$APP_LLM_MODELNAME}"
export REFLECTION_LLM="${REFLECTION_LLM:-$APP_LLM_MODELNAME}"
export APP_RETRIEVER_TOPK="${APP_RETRIEVER_TOPK:-6}"
export VECTOR_DB_TOPK="${VECTOR_DB_TOPK:-60}"
export LLM_MAX_TOKENS="${LLM_MAX_TOKENS:-4096}"

echo "Starting GPU Milvus/vector DB"
docker compose -f deploy/compose/vectordb.yaml up -d

echo "Starting NVIDIA RAG ingestor"
docker compose -f deploy/compose/docker-compose-ingestor-server.yaml up -d

echo "Starting NVIDIA RAG server and frontend"
docker compose -f deploy/compose/docker-compose-rag-server.yaml up -d

echo "Waiting for RAG services..."
sleep 20

echo
echo "RAG server health:"
curl -sS "http://127.0.0.1:8081/v1/health?check_dependencies=true" || true
echo
echo
echo "Ingestor health:"
curl -sS "http://127.0.0.1:8082/v1/health?check_dependencies=true" || true
echo

echo
echo "RAG Blueprint startup requested."
echo "RAG API: http://127.0.0.1:8081/v1/generate"
echo "Ingestor API: http://127.0.0.1:8082/v1/documents"
echo "Collection: $COLLECTION_NAME"
echo "LLM model: $APP_LLM_MODELNAME"
echo "Retriever top-k: $APP_RETRIEVER_TOPK"
