"""Global configuration for the Context-Engine / Agent backend.

Design goal: the system must run out-of-the-box *offline* (BM25 retrieval +
a deterministic fake model), and transparently upgrade to real backends when
they are available:

* ``DASHSCOPE_API_KEY`` present  -> Qwen (Tongyi) API for chat + embeddings
* a fine-tuned adapter on disk    -> local fine-tuned Qwen for chat

Everything is resolved lazily in ``models/`` and ``retrieval/`` so that a
missing key / adapter never crashes startup.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Project roots -----------------------------------------------------------------
BACKEND_DIR = Path(__file__).resolve().parents[1]   # .../backend
PROJECT_DIR = BACKEND_DIR.parent                    # .../context-engine-agent
DATA_DIR = BACKEND_DIR / "data"
KB_DIR = DATA_DIR / "kb"
FINETUNE_DIR = BACKEND_DIR / "finetune"
OUTPUTS_DIR = FINETUNE_DIR / "outputs"
FINETUNE_DATA_DIR = FINETUNE_DIR / "data"

# Allow overriding where the adapter is stored (useful for experiments)
ENV_FILE = BACKEND_DIR / ".env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)
load_dotenv()  # also try cwd

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "").strip()

# App ---------------------------------------------------------------------------
APP_TITLE = "Context Engine + Multi-Agent QA"
APP_PORT = int(os.getenv("PORT", "8000"))
ALLOW_ORIGINS = os.getenv(
    "ALLOW_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(",")

# Qwen (DashScope) ---------------------------------------------------------------
QWEN_CHAT_MODEL = os.getenv("QWEN_CHAT_MODEL", "qwen3-max")
QWEN_EMBED_MODEL = os.getenv("QWEN_EMBED_MODEL", "text-embedding-v4")

# Context Engine settings --------------------------------------------------------
# Token budget reserved for the final generation prompt. The context engine
# allocates the budget across (system + retrieval + history) and trims the
# lowest-priority pieces when the combined estimate exceeds it.
CONTEXT_TOKEN_BUDGET = int(os.getenv("CONTEXT_TOKEN_BUDGET", "4096"))
HISTORY_MAX_TURNS = int(os.getenv("HISTORY_MAX_TURNS", "8"))   # sliding window
HISTORY_SUMMARY_TOKENS = int(os.getenv("HISTORY_SUMMARY_TOKENS", "300"))
TOP_K = int(os.getenv("TOP_K", "3"))

# Retrieval ---------------------------------------------------------------------
# Default backend is bm25 (pure-python, offline). Set RETRIEVAL_BACKEND=dashscope
# to use embedding similarity + FAISS when DASHSCOPE_API_KEY is set.
RETRIEVAL_BACKEND = os.getenv("RETRIEVAL_BACKEND", "auto").lower()  # auto|bm25|dashscope
FAISS_PERSIST_DIR = os.getenv(
    "FAISS_INDEX_DIR",
    str(Path(os.environ.get("TEMP", "/tmp")) / "ctxeng_faiss_db"),
)
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "50"))
# 切分策略：sentence（按句/段边界打包，默认）| fixed（定长滑窗，baseline）
CHUNK_STRATEGY = os.getenv("CHUNK_STRATEGY", "sentence").lower()
# 单个上传文件的大小上限（字节）
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(2 * 1024 * 1024)))

# Storage / DB -------------------------------------------------------------------
# Conversational history is persisted to a relational store.
#   * Default: a local SQLite file (stdlib sqlite3, zero deps, offline).
#   * MySQL: set DATABASE_URL=mysql+pymysql://user:pass@host:3306/dbname
#            (requires `pip install pymysql` and a running MySQL server).
# The storage layer is isolated behind ChatStore so the switch is a config change.
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DB_PATH = DATA_DIR / "app.db"

# Cache --------------------------------------------------------------------------
# Retrieval results / computed values are cached to avoid repeated embedding calls.
#   * Default: in-process LRU (stdlib, offline).
#   * Redis: set REDIS_URL=redis://localhost:6379/0 (requires `pip install redis`).
REDIS_URL = os.getenv("REDIS_URL", "").strip()
CACHE_TTL = int(os.getenv("CACHE_TTL", "120"))
CACHE_MAXSIZE = int(os.getenv("CACHE_MAXSIZE", "256"))

# Fine-tuning --------------------------------------------------------------------
# Base model family used for the LoRA demo. 0.5B is the fastest to validate the
# full pipeline; 1.5B is a more credible result and still fits 8 GB in 4-bit.
FINE_TUNE_BASE_MODEL = os.getenv(
    "FINE_TUNE_BASE_MODEL", "Qwen/Qwen2.5-0.5B-Instruct"
)
LORA_R = int(os.getenv("LORA_R", "8"))
LORA_ALPHA = int(os.getenv("LORA_ALPHA", "16"))
LORA_DROPOUT = float(os.getenv("LORA_DROPOUT", "0.05"))
MAX_SEQ_LEN = int(os.getenv("MAX_SEQ_LEN", "512"))
USE_4BIT = os.getenv("USE_4BIT", "true").lower() == "true"
FT_OUTPUT_ADAPTER = OUTPUTS_DIR / "adapter"
FT_MERGED_MODEL = OUTPUTS_DIR / "merged"

# Fallback local model dir (optional pre-quantized GGUF / transformers path)
LOCAL_MODEL_DIR = os.getenv("LOCAL_MODEL_DIR", "")


def effective_chat_backend() -> str:
    """Return which chat backend will actually be used.

    Priority: local fine-tuned adapter > qwen api (if key) > fake.
    """
    if (FT_OUTPUT_ADAPTER / "adapter_config.json").exists():
        return "local_ft"
    if DASHSCOPE_API_KEY:
        return "qwen_api"
    return "fake"


def effective_retrieval_backend() -> str:
    """Return which retrieval backend will actually be used."""
    if RETRIEVAL_BACKEND == "bm25":
        return "bm25"
    if RETRIEVAL_BACKEND == "dashscope" and DASHSCOPE_API_KEY:
        return "dashscope"
    if RETRIEVAL_BACKEND == "auto":
        return "dashscope" if DASHSCOPE_API_KEY else "bm25"
    return "bm25"


def effective_db_backend() -> str:
    """Return the relational store backend actually used."""
    return "mysql" if DATABASE_URL.lower().startswith("mysql") else "sqlite"


def effective_cache_backend() -> str:
    """Return the cache backend actually used (Redis if configured, else LRU)."""
    return "redis" if REDIS_URL else "lru"
