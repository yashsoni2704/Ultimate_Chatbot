import os
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
    # Qdrant Vector Store
    # ==============================

    QDRANT_PATH = os.getenv(
        "QDRANT_PATH",
        "vector_store"
    )

    QDRANT_COLLECTION_NAME = os.getenv(
        "QDRANT_COLLECTION_NAME",
        "docmind"
    )

    # Backward-compat alias (some older code may still reference VECTOR_DB_PATH)
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
            "5"
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