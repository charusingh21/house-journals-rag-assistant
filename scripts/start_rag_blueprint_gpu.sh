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
RAG_BACKEND_MODE="${RAG_BACKEND_MODE:-nvidia_hosted}"

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
if [ "$RAG_BACKEND_MODE" = "nvidia_hosted" ] || [ "$RAG_BACKEND_MODE" = "docker_hybrid" ]; then
  source deploy/compose/nvdev.env
elif [ "$RAG_BACKEND_MODE" != "docker_self_hosted" ]; then
  echo "Unsupported RAG_BACKEND_MODE: $RAG_BACKEND_MODE"
  echo "Use nvidia_hosted, docker_hybrid, or docker_self_hosted."
  exit 1
fi
set +a

export NVIDIA_API_KEY
export NGC_API_KEY
export COLLECTION_NAME
export MILVUS_VERSION="${MILVUS_VERSION:-v2.6.5-gpu}"
export MODEL_DIRECTORY="${MODEL_DIRECTORY:-$HOME/.cache/model-cache}"
export USERID="${USERID:-$(id -u)}"
export APP_LLM_MODELNAME="${RAG_MODEL:-${APP_LLM_MODELNAME:-nvidia/llama-3.3-nemotron-super-49b-v1.5}}"
export APP_FILTEREXPRESSIONGENERATOR_MODELNAME="${APP_FILTEREXPRESSIONGENERATOR_MODELNAME:-$APP_LLM_MODELNAME}"
export APP_QUERYREWRITER_MODELNAME="${APP_QUERYREWRITER_MODELNAME:-$APP_LLM_MODELNAME}"
export SUMMARY_LLM="${SUMMARY_LLM:-$APP_LLM_MODELNAME}"
export REFLECTION_LLM="${REFLECTION_LLM:-$APP_LLM_MODELNAME}"
export APP_RETRIEVER_TOPK="${APP_RETRIEVER_TOPK:-6}"
export VECTOR_DB_TOPK="${VECTOR_DB_TOPK:-60}"
export LLM_MAX_TOKENS="${LLM_MAX_TOKENS:-4096}"

mkdir -p "$MODEL_DIRECTORY"
if command -v sudo >/dev/null 2>&1; then
  sudo chown -R "$(id -u):$(id -g)" "$MODEL_DIRECTORY" 2>/dev/null || true
fi

if [ "$RAG_BACKEND_MODE" = "docker_self_hosted" ]; then
  export APP_LLM_SERVERURL="${APP_LLM_SERVERURL:-nim-llm:8000}"
  export APP_EMBEDDINGS_SERVERURL="${APP_EMBEDDINGS_SERVERURL:-nemotron-embedding-ms:8000}"
  export APP_RANKING_SERVERURL="${APP_RANKING_SERVERURL:-nemotron-ranking-ms:8000}"
  export SUMMARY_LLM_SERVERURL="${SUMMARY_LLM_SERVERURL:-nim-llm:8000}"
  export REFLECTION_LLM_SERVERURL="${REFLECTION_LLM_SERVERURL:-nim-llm:8000}"
  export LLM_MS_GPU_ID="${LLM_MS_GPU_ID:-1}"
  export EMBEDDING_MS_GPU_ID="${EMBEDDING_MS_GPU_ID:-0}"
  export RANKING_MS_GPU_ID="${RANKING_MS_GPU_ID:-0}"
elif [ "$RAG_BACKEND_MODE" = "docker_hybrid" ]; then
  export APP_LLM_SERVERURL="${APP_LLM_SERVERURL:-}"
  export APP_EMBEDDINGS_SERVERURL="${APP_EMBEDDINGS_SERVERURL:-nemotron-embedding-ms:8000}"
  export APP_RANKING_SERVERURL="${APP_RANKING_SERVERURL:-nemotron-ranking-ms:8000}"
  export SUMMARY_LLM_SERVERURL="${SUMMARY_LLM_SERVERURL:-}"
  export REFLECTION_LLM_SERVERURL="${REFLECTION_LLM_SERVERURL:-}"
  export EMBEDDING_MS_GPU_ID="${EMBEDDING_MS_GPU_ID:-0}"
  export RANKING_MS_GPU_ID="${RANKING_MS_GPU_ID:-0}"
else
  export APP_LLM_SERVERURL="${APP_LLM_SERVERURL:-}"
  export APP_EMBEDDINGS_SERVERURL="${APP_EMBEDDINGS_SERVERURL:-https://integrate.api.nvidia.com/v1}"
  export APP_RANKING_SERVERURL="${APP_RANKING_SERVERURL:-https://integrate.api.nvidia.com/v1}"
fi

echo "Starting GPU Milvus/vector DB"
docker compose -f deploy/compose/vectordb.yaml up -d

if [ "$RAG_BACKEND_MODE" = "docker_self_hosted" ]; then
  echo "Starting self-hosted NIMs for LLM, embedding, and reranking"
  docker compose -f deploy/compose/nims.yaml up -d nim-llm nemotron-embedding-ms nemotron-ranking-ms
elif [ "$RAG_BACKEND_MODE" = "docker_hybrid" ]; then
  echo "Starting self-hosted NIMs for embedding and reranking"
  docker compose -f deploy/compose/nims.yaml up -d nemotron-embedding-ms nemotron-ranking-ms
fi

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
echo "Backend mode: $RAG_BACKEND_MODE"
echo "LLM model: $APP_LLM_MODELNAME"
echo "Retriever top-k: $APP_RETRIEVER_TOPK"
