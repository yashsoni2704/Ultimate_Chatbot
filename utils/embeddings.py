import json
import os
from datetime import datetime

from config import Config
from utils.logger import get_logger

logger = get_logger(__name__)

# ── Registry file path ───────────────────────────────────────────────────────
# Stored inside the Qdrant data folder so everything stays together
REGISTRY_FILE = os.path.join(Config.QDRANT_PATH, "registry.json")


# ════════════════════════════════════════════════════════════════════════════
# Registry helpers  (unchanged interface — all callers depend on these)
# ════════════════════════════════════════════════════════════════════════════

def _load_registry() -> list:
    """Return the list of ingested document records."""
    if os.path.exists(REGISTRY_FILE):
        try:
            with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Filter out any null/malformed entries
                return [r for r in data if r is not None and isinstance(r, dict)]
        except (json.JSONDecodeError, IOError):
            return []
    return []


def _save_registry(records: list) -> None:
    os.makedirs(Config.QDRANT_PATH, exist_ok=True)
    with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)


def _is_already_ingested(filename: str) -> bool:
    for rec in _load_registry():
        if rec.get("filename") == filename:
            return True
    return False


def _register_document(filename: str, file_path: str, chunk_count: int) -> None:
    records = _load_registry()
    # For URLs don't resolve as filesystem path
    stored_path = file_path if (file_path.startswith("http://") or file_path.startswith("https://")) else os.path.abspath(file_path)
    records.append({
        "filename":    filename,
        "path":        stored_path,
        "chunks":      chunk_count,
        "ingested_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    _save_registry(records)


def get_all_documents() -> list:
    """Public helper — returns all registry records (used by Flask routes)."""
    return _load_registry()


# ════════════════════════════════════════════════════════════════════════════
# Qdrant client helper
# ════════════════════════════════════════════════════════════════════════════

def _get_qdrant_client():
    """Return a local persistent QdrantClient pointed at QDRANT_PATH."""
    from qdrant_client import QdrantClient
    os.makedirs(Config.QDRANT_PATH, exist_ok=True)
    return QdrantClient(path=Config.QDRANT_PATH)


# ════════════════════════════════════════════════════════════════════════════
# Public: delete chunks for a single document  ← KEY NEW FUNCTION
# ════════════════════════════════════════════════════════════════════════════

def delete_document_chunks(filename: str) -> int:
    """
    Surgically remove all vectors whose metadata 'source' field matches
    *filename* from the Qdrant collection.

    Uses Qdrant's native payload filter — no rebuild, no re-embedding,
    all other documents remain completely untouched.

    Returns the number of points deleted (0 if none found).
    """
    from qdrant_client.models import Filter, FieldCondition, MatchValue

    client = _get_qdrant_client()

    # Check collection exists
    collections = [c.name for c in client.get_collections().collections]
    if Config.QDRANT_COLLECTION_NAME not in collections:
        logger.warning(f"Collection '{Config.QDRANT_COLLECTION_NAME}' not found — nothing to delete.")
        return 0

    # Qdrant stores LangChain metadata under the key "metadata"
    # LangChain sets doc.metadata["source"] = file_path, so we match on
    # both the bare filename and any path ending with the filename.
    # We use the "source" key inside the nested metadata payload.
    delete_filter = Filter(
        must=[
            FieldCondition(
                key="metadata.source",
                match=MatchValue(value=filename)
            )
        ]
    )

    # Count before delete for logging
    before = client.count(
        collection_name=Config.QDRANT_COLLECTION_NAME,
        count_filter=delete_filter,
        exact=True,
    ).count

    if before == 0:
        # Try matching by full absolute path stored in registry
        records = _load_registry()
        matching = [r for r in records if r.get("filename") == filename]
        if matching:
            abs_path = matching[0].get("path", "")
            delete_filter = Filter(
                must=[
                    FieldCondition(
                        key="metadata.source",
                        match=MatchValue(value=abs_path)
                    )
                ]
            )
            before = client.count(
                collection_name=Config.QDRANT_COLLECTION_NAME,
                count_filter=delete_filter,
                exact=True,
            ).count

    client.delete(
        collection_name=Config.QDRANT_COLLECTION_NAME,
        points_selector=delete_filter,
    )

    logger.info(f"🗑️  Deleted {before} vector(s) for '{filename}' from Qdrant")
    return before


# ════════════════════════════════════════════════════════════════════════════
# EmbeddingManager
# ════════════════════════════════════════════════════════════════════════════

class EmbeddingManager:

    def __init__(self):
        from langchain_community.embeddings import OllamaEmbeddings
        logger.info(f"Initializing embedding model: {Config.EMBEDDING_MODEL}")
        self.embedding_model = OllamaEmbeddings(model=Config.EMBEDDING_MODEL)
        logger.info("✅ Embedding model initialized")

    # ── Create / add to vector store ────────────────────────────────────────

    def create_vector_store(self, chunks, source_path: str = ""):
        """
        Embed *chunks* and ADD them to the Qdrant collection.
        If the collection doesn't exist yet it is created automatically.

        Parameters
        ----------
        chunks      : list of LangChain Document objects
        source_path : original file path — used for dedup check and registry
        """
        from langchain_qdrant import QdrantVectorStore

        filename = os.path.basename(source_path) if source_path else ""

        # For URLs, os.path.basename returns the last path segment which is
        # not a useful key — use the full URL as the filename identifier
        if source_path and (source_path.startswith("http://") or source_path.startswith("https://")):
            filename = source_path

        # ── Duplicate guard ────────────────────────────────────────────────
        if filename and _is_already_ingested(filename):
            logger.warning(f"⚠️  '{filename}' is already in the knowledge base — skipping.")
            return None

        logger.info("")
        logger.info("Step 1️⃣  Generating embeddings...")
        logger.info(f"  Chunks      : {len(chunks)}")
        logger.info(f"  Model       : {Config.EMBEDDING_MODEL}")
        logger.info(f"  Source file : {filename or 'unknown'}")
        logger.info(f"  Timestamp   : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        os.makedirs(Config.QDRANT_PATH, exist_ok=True)

        # QdrantVectorStore.from_documents creates the collection if absent,
        # or ADDS to it if it already exists — exactly what we want.
        vectorstore = QdrantVectorStore.from_documents(
            documents=chunks,
            embedding=self.embedding_model,
            path=Config.QDRANT_PATH,
            collection_name=Config.QDRANT_COLLECTION_NAME,
        )

        logger.info(f"✅ Embeddings done — {len(chunks)} vectors added to Qdrant")

        # ── Register document ──────────────────────────────────────────────
        if filename:
            _register_document(filename, source_path, len(chunks))
            logger.info(f"✅ Registered '{filename}' in knowledge base registry")

        logger.info(f"✅ Qdrant store at: {os.path.abspath(Config.QDRANT_PATH)}")
        return vectorstore

    # ── Load existing vector store ──────────────────────────────────────────

    def load_vector_store(self):
        """Return a LangChain-compatible QdrantVectorStore for querying."""
        from langchain_qdrant import QdrantVectorStore

        client = _get_qdrant_client()
        collections = [c.name for c in client.get_collections().collections]

        if Config.QDRANT_COLLECTION_NAME not in collections:
            raise Exception("No documents have been processed yet. Please upload a document first.")

        return QdrantVectorStore(
            client=client,
            collection_name=Config.QDRANT_COLLECTION_NAME,
            embedding=self.embedding_model,
        )

    # ── Helpers ─────────────────────────────────────────────────────────────

    def vector_store_exists(self) -> bool:
        try:
            client = _get_qdrant_client()
            collections = [c.name for c in client.get_collections().collections]
            return Config.QDRANT_COLLECTION_NAME in collections
        except Exception:
            return False

    def delete_vector_store(self) -> bool:
        """Drop the entire collection (used for full reset only)."""
        try:
            client = _get_qdrant_client()
            client.delete_collection(Config.QDRANT_COLLECTION_NAME)
            logger.info(f"🗑️  Dropped Qdrant collection '{Config.QDRANT_COLLECTION_NAME}'")
            return True
        except Exception as e:
            logger.error(f"Failed to drop collection: {e}")
            return False
