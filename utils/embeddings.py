import json
import os
from datetime import datetime

from config import Config
from langchain_community.vectorstores import FAISS
from utils.logger import get_logger

logger = get_logger(__name__)

# Path to the JSON file that tracks every ingested document
REGISTRY_FILE = os.path.join(Config.VECTOR_DB_PATH, "registry.json")


# ── Registry helpers ────────────────────────────────────────────────────────

def _load_registry() -> list:
    """Return the list of ingested document records."""
    if os.path.exists(REGISTRY_FILE):
        try:
            with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    return []


def _save_registry(records: list) -> None:
    os.makedirs(Config.VECTOR_DB_PATH, exist_ok=True)
    with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)


def _is_already_ingested(filename: str) -> bool:
    for rec in _load_registry():
        if rec.get("filename") == filename:
            return True
    return False


def _register_document(filename: str, file_path: str, chunk_count: int) -> None:
    records = _load_registry()
    records.append({
        "filename":    filename,
        "path":        file_path,
        "chunks":      chunk_count,
        "ingested_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    _save_registry(records)


def get_all_documents() -> list:
    """Public helper — returns all registry records (used by Flask route)."""
    return _load_registry()


# ── EmbeddingManager ────────────────────────────────────────────────────────

class EmbeddingManager:

    def __init__(self):
        from langchain_community.embeddings import OllamaEmbeddings

        logger.info(f"Initializing embedding model: {Config.EMBEDDING_MODEL}")
        self.embedding_model = OllamaEmbeddings(model=Config.EMBEDDING_MODEL)
        logger.info("✅ Embedding model initialized")

    # ── Create / merge vector store ─────────────────────────────────────────

    def create_vector_store(self, chunks, source_path: str = ""):
        """
        Embed *chunks* and MERGE them into the existing FAISS index.
        If no index exists yet, a fresh one is created.

        Parameters
        ----------
        chunks      : list of LangChain Document objects
        source_path : original file path — used for dedup check and registry
        """

        filename = os.path.basename(source_path) if source_path else ""

        # ── Duplicate guard ────────────────────────────────────────────────
        if filename and _is_already_ingested(filename):
            logger.warning(f"⚠️  '{filename}' is already in the knowledge base — skipping.")
            return None   # caller can detect this via None return

        logger.info("")
        logger.info("Step 1️⃣  Generating embeddings...")
        logger.info(f"  Chunks      : {len(chunks)}")
        logger.info(f"  Model       : {Config.EMBEDDING_MODEL}")
        logger.info(f"  Source file : {filename or 'unknown'}")
        logger.info(f"  Timestamp   : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        new_db = FAISS.from_documents(
            documents=chunks,
            embedding=self.embedding_model,
        )
        logger.info(f"✅ Embeddings done — {len(chunks)} vectors created")

        # ── Merge or create ────────────────────────────────────────────────
        os.makedirs(Config.VECTOR_DB_PATH, exist_ok=True)
        index_file = os.path.join(Config.VECTOR_DB_PATH, "index.faiss")

        if os.path.exists(index_file):
            logger.info("Step 2️⃣  Existing index found — merging...")
            existing_db = FAISS.load_local(
                Config.VECTOR_DB_PATH,
                self.embedding_model,
                allow_dangerous_deserialization=True,
            )
            existing_db.merge_from(new_db)
            existing_db.save_local(Config.VECTOR_DB_PATH)
            logger.info("✅ Merged into existing index")
        else:
            logger.info("Step 2️⃣  No existing index — creating fresh one...")
            new_db.save_local(Config.VECTOR_DB_PATH)
            logger.info("✅ Fresh index saved")

        # ── Register document ──────────────────────────────────────────────
        if filename:
            _register_document(filename, source_path, len(chunks))
            logger.info(f"✅ Registered '{filename}' in knowledge base registry")

        logger.info(f"✅ Vector store saved at: {os.path.abspath(Config.VECTOR_DB_PATH)}")
        return new_db

    # ── Load existing vector store ──────────────────────────────────────────

    def load_vector_store(self):
        if not os.path.exists(Config.VECTOR_DB_PATH):
            raise Exception("No vector database found. Please load a document first.")

        return FAISS.load_local(
            Config.VECTOR_DB_PATH,
            self.embedding_model,
            allow_dangerous_deserialization=True,
        )

    # ── Helpers ─────────────────────────────────────────────────────────────

    def vector_store_exists(self) -> bool:
        return os.path.exists(os.path.join(Config.VECTOR_DB_PATH, "index.faiss"))

    def delete_vector_store(self) -> bool:
        import shutil
        if os.path.exists(Config.VECTOR_DB_PATH):
            shutil.rmtree(Config.VECTOR_DB_PATH)
            return True
        return False
