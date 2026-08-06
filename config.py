import os
from dotenv import load_dotenv

load_dotenv()


class Config:

    # ==============================
    # Google API (optional)
    # ==============================

    GOOGLE_API_KEY = os.getenv(
        "GOOGLE_API_KEY",
        ""
    ).strip()


    # ==============================
    # Web Scraping
    # ==============================

    SCRAPING_TIMEOUT = int(os.getenv("SCRAPING_TIMEOUT", "60"))          # seconds to wait for page load
    SCRAPING_MIN_CHARS = int(os.getenv("SCRAPING_MIN_CHARS", "1"))       # effectively disabled — crawl everything
    SCRAPING_MAX_CHARS = int(os.getenv("SCRAPING_MAX_CHARS", "10000000"))# 10MB cap — virtually unlimited


    # ==============================
    # Qdrant Vector Store — Blue/Green Strategy
    # ==============================

    QDRANT_PATH = os.getenv("QDRANT_PATH", "vector_store")

    # Qdrant HTTP server settings (server mode — no file lock conflicts)
    QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
    QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))

    # Blue/Green collection names
    QDRANT_COLLECTION_BLUE  = os.getenv("QDRANT_COLLECTION_BLUE",  "docmind_blue")
    QDRANT_COLLECTION_GREEN = os.getenv("QDRANT_COLLECTION_GREEN", "docmind_green")

    # Active slot tracker file (inside QDRANT_PATH)
    ACTIVE_SLOT_FILE = "active_slot.json"

    # Backward-compat single-collection name (legacy migration only)
    QDRANT_COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME", "docmind")

    # Backward-compat alias
    VECTOR_DB_PATH = QDRANT_PATH


    # ==============================
    # File Storage
    # ==============================

    UPLOAD_FOLDER = os.getenv(
        "UPLOAD_FOLDER",
        "uploads"
    )


    # ==============================
    # Allowed Files
    # ==============================

    ALLOWED_EXTENSIONS = {
        "pdf",
        "docx", "doc",
        "xlsx", "xls",
        "pptx", "ppt",
        "csv",
        "txt",
        "rtf",
    }


    # ==============================
    # Chunking
    # ==============================

    CHUNK_SIZE = int(
        os.getenv(
            "CHUNK_SIZE",
            "2000"
        )
    )

    CHUNK_OVERLAP = int(
        os.getenv(
            "CHUNK_OVERLAP",
            "200"
        )
    )


    # ==============================
    # Retrieval
    # ==============================

    TOP_K = int(
        os.getenv(
            "TOP_K",
            "50"
        )
    )


    # ==============================
    # Reranker
    # ==============================

    RERANKER_ENABLED = os.getenv(
        "RERANKER_ENABLED",
        "True"
    ).strip().lower() == "true"

    RERANKER_MODEL = os.getenv(
        "RERANKER_MODEL",
        "BAAI/bge-reranker-v2-m3"
    ).strip()

    RERANKER_TOP_N = int(
        os.getenv(
            "RERANKER_TOP_N",
            "10"
        )
    )


    # ==============================
    # Embedding Model
    # ==============================

    EMBEDDING_MODEL = os.getenv(
        "EMBEDDING_MODEL"
    )

    EMBEDDING_DEVICE = os.getenv(
        "EMBEDDING_DEVICE",
        "cpu"
    )

    EMBEDDING_BATCH_SIZE = int(
        os.getenv(
            "EMBEDDING_BATCH_SIZE",
            "8"
        )
    )

    # A cold Ollama embedding model can take a few minutes to load on CPU.
    EMBEDDING_TIMEOUT = int(os.getenv("EMBEDDING_TIMEOUT", "600"))
    EMBEDDING_RETRIES = int(os.getenv("EMBEDDING_RETRIES", "2"))


    # ==============================
    # LLM (Ollama)
    # ==============================

    LLM_MODEL = os.getenv(
        "LLM_MODEL",
        "llama3.1:latest"
    )

    LLM_TEMPERATURE = float(
        os.getenv(
            "LLM_TEMPERATURE",
            "0.2"
        )
    )


    # ==============================
    # Conversation History
    # ==============================

    # True  → send last N turns to LLM for context awareness
    # False → each question is answered in isolation
    CONVERSATION_HISTORY = os.getenv(
        "CONVERSATION_HISTORY",
        "True"
    ).strip().lower() == "true"

    # How many past Q&A turns to include (each turn = 1 question + 1 answer)
    CONVERSATION_HISTORY_LIMIT = int(
        os.getenv(
            "CONVERSATION_HISTORY_LIMIT",
            "3"
        )
    )


    # ==============================
    # LangSmith Tracing (optional)
    # ==============================

    LANGCHAIN_TRACING_V2 = os.getenv(
        "LANGCHAIN_TRACING_V2",
        "false"
    ).strip().lower() == "true"

    LANGCHAIN_API_KEY = os.getenv(
        "LANGCHAIN_API_KEY",
        ""
    ).strip()

    LANGCHAIN_PROJECT = os.getenv(
        "LANGCHAIN_PROJECT",
        "docmind-chatbot"
    ).strip()


    # ==============================
    # MongoDB
    # ==============================

    MONGO_URI = os.getenv(
        "MONGO_URI",
        "mongodb://localhost:27017/"
    ).strip()

    MONGO_DB_NAME = os.getenv(
        "MONGO_DB_NAME",
        "Ultimate_Chatbot"
    ).strip()

    # ==============================
    # Mic Voice Input
    # ==============================

    # Seconds of silence before mic auto-closes
    MIC_SILENCE_TIMEOUT = int(os.getenv("MIC_SILENCE_TIMEOUT", "3"))
