"""
utils/embeddings.py
~~~~~~~~~~~~~~~~~~~
Blue/Green vector database strategy using Qdrant HTTP server mode.

Qdrant runs as a standalone server (qdrant.exe) on localhost:6333.
All Python code connects via HTTP — no file locks, no conflicts.
Multiple processes (app.py, admin_app.py) and multiple threads can
all connect simultaneously without any locking issues.

Slot layout:
    docmind_blue   ← one Qdrant collection
    docmind_green  ← other Qdrant collection

active_slot.json (inside QDRANT_PATH):
    {"active": "blue"} or {"active": "green"}

Flow for every add/delete:
    1. Clone active → standby  (all existing data preserved)
    2. Modify standby           (add or delete)
    3. Switch pointer           (atomic JSON write, ~1ms)
    Users query active throughout — zero interruption.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime

from config import Config
from utils.logger import get_logger

logger = get_logger(__name__)

# ── Slot names ────────────────────────────────────────────────────────────────
BLUE  = "blue"
GREEN = "green"

# ── File paths ────────────────────────────────────────────────────────────────
REGISTRY_FILE    = os.path.join(Config.QDRANT_PATH, "registry.json")
ACTIVE_SLOT_FILE = os.path.join(Config.QDRANT_PATH, Config.ACTIVE_SLOT_FILE)

# ── Serialise writes — only one add/delete pipeline at a time ────────────────
_write_lock = threading.Lock()


# ═════════════════════════════════════════════════════════════════════════════
# Qdrant HTTP client helper
# ═════════════════════════════════════════════════════════════════════════════

def _get_qdrant_client():
    """Return a QdrantClient connected to the Qdrant HTTP server.
    Multiple callers get independent connections — no file lock, no conflict.
    """
    from qdrant_client import QdrantClient
    return QdrantClient(
        host    = Config.QDRANT_HOST,
        port    = Config.QDRANT_PORT,
        timeout = 60,
    )


# ═════════════════════════════════════════════════════════════════════════════
# Registry helpers
# ═════════════════════════════════════════════════════════════════════════════

def _load_registry() -> list:
    if os.path.exists(REGISTRY_FILE):
        try:
            with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return [r for r in data if r is not None and isinstance(r, dict)]
        except (json.JSONDecodeError, IOError):
            return []
    return []


def _save_registry(records: list) -> None:
    os.makedirs(Config.QDRANT_PATH, exist_ok=True)
    with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)


def _is_already_ingested(filename: str) -> bool:
    return any(r.get("filename") == filename for r in _load_registry())


def _register_document(filename: str, file_path: str, chunk_count: int) -> None:
    records     = _load_registry()
    stored_path = (file_path if file_path.startswith(("http://", "https://"))
                   else os.path.abspath(file_path))
    records.append({
        "filename":    filename,
        "path":        stored_path,
        "chunks":      chunk_count,
        "ingested_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    _save_registry(records)


def get_all_documents() -> list:
    return _load_registry()


# ═════════════════════════════════════════════════════════════════════════════
# Slot helpers
# ═════════════════════════════════════════════════════════════════════════════

def _collection_name(slot: str) -> str:
    if slot == BLUE:
        return Config.QDRANT_COLLECTION_BLUE
    if slot == GREEN:
        return Config.QDRANT_COLLECTION_GREEN
    raise ValueError(f"Unknown slot: {slot!r}")


def _read_active_slot() -> str:
    if os.path.exists(ACTIVE_SLOT_FILE):
        try:
            with open(ACTIVE_SLOT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                slot = data.get("active", BLUE)
                if slot in (BLUE, GREEN):
                    return slot
        except (json.JSONDecodeError, IOError):
            pass
    _migrate_legacy_if_needed()
    return BLUE


def _write_active_slot(slot: str) -> None:
    os.makedirs(Config.QDRANT_PATH, exist_ok=True)
    tmp = ACTIVE_SLOT_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"active": slot, "updated_at": datetime.now().isoformat()}, f)
    os.replace(tmp, ACTIVE_SLOT_FILE)
    logger.info(f"🔀 Active slot → {slot.upper()} ({_collection_name(slot)})")


def _standby_slot(active: str) -> str:
    return GREEN if active == BLUE else BLUE


def get_active_collection_name() -> str:
    return _collection_name(_read_active_slot())


# ═════════════════════════════════════════════════════════════════════════════
# Legacy migration  (runs once — converts old "docmind" → "docmind_blue")
# ═════════════════════════════════════════════════════════════════════════════

def _migrate_legacy_if_needed() -> None:
    try:
        client   = _get_qdrant_client()
        existing = {c.name for c in client.get_collections().collections}
        legacy   = Config.QDRANT_COLLECTION_NAME
        blue_c   = Config.QDRANT_COLLECTION_BLUE
        green_c  = Config.QDRANT_COLLECTION_GREEN

        if legacy not in existing:
            _write_active_slot(BLUE)
            return
        if blue_c in existing or green_c in existing:
            if not os.path.exists(ACTIVE_SLOT_FILE):
                _write_active_slot(BLUE)
            return

        logger.info(f"🔄 Migrating legacy '{legacy}' → '{blue_c}' ...")
        _clone_collection(client, src=legacy, dst=blue_c)
        _write_active_slot(BLUE)
        logger.info("✅ Migration complete.")
    except Exception as exc:
        logger.warning(f"⚠️  Legacy migration skipped: {exc}")
        try:
            _write_active_slot(BLUE)
        except Exception:
            pass


# ═════════════════════════════════════════════════════════════════════════════
# Clone helper — copies all vectors from src → dst via HTTP
# ═════════════════════════════════════════════════════════════════════════════

def _clone_collection(client, src: str, dst: str) -> int:
    from qdrant_client.models import Distance, VectorParams, PointStruct

    existing = {c.name for c in client.get_collections().collections}

    if src not in existing:
        # Active is empty (first ever upload) — just delete dst if it exists
        if dst in existing:
            client.delete_collection(dst)
        logger.info(f"📋 Source '{src}' is empty — standby will be created fresh")
        return 0

    # Read vector config from source
    src_info    = client.get_collection(src)
    vectors_cfg = src_info.config.params.vectors
    if hasattr(vectors_cfg, "size"):
        vector_size = vectors_cfg.size
    elif isinstance(vectors_cfg, dict):
        first       = next(iter(vectors_cfg.values()))
        vector_size = first.size
    else:
        vector_size = 1024

    # Recreate dst with same config
    if dst in existing:
        client.delete_collection(dst)
    client.create_collection(
        collection_name = dst,
        vectors_config  = vectors_cfg,
    )

    # Stream all points src → dst in batches of 256
    BATCH = 256
    offset = None
    total  = 0

    while True:
        results, next_offset = client.scroll(
            collection_name = src,
            limit           = BATCH,
            offset          = offset,
            with_vectors    = True,
            with_payload    = True,
        )
        if not results:
            break
        points = [PointStruct(id=p.id, vector=p.vector, payload=p.payload)
                  for p in results]
        client.upsert(collection_name=dst, points=points)
        total  += len(points)
        offset  = next_offset
        if next_offset is None:
            break

    logger.info(f"📋 Cloned {total} vectors  {src} → {dst}")
    return total


# ═════════════════════════════════════════════════════════════════════════════
# Public: delete chunks
# ═════════════════════════════════════════════════════════════════════════════

def delete_document_chunks(filename: str) -> int:
    from qdrant_client.models import Filter, FieldCondition, MatchValue

    with _write_lock:
        active      = _read_active_slot()
        standby     = _standby_slot(active)
        active_col  = _collection_name(active)
        standby_col = _collection_name(standby)
        client      = _get_qdrant_client()

        logger.info(f"🗑️  Delete: active={active.upper()} standby={standby.upper()}")

        # Step 1 — clone
        logger.info("Step 1/3 — Cloning active → standby …")
        _clone_collection(client, src=active_col, dst=standby_col)

        # Step 2 — delete from standby
        logger.info(f"Step 2/3 — Deleting '{filename}' from standby …")

        # If standby doesn't exist yet (source was empty → clone skipped creation),
        # create it now so the delete/count calls don't 404.
        existing_cols = {c.name for c in client.get_collections().collections}
        if standby_col not in existing_cols:
            from qdrant_client.models import Distance, VectorParams
            # We don't know vector size yet (no vectors exist), so use a placeholder.
            # The collection will be properly recreated on next upload anyway.
            client.create_collection(
                collection_name = standby_col,
                vectors_config  = VectorParams(size=1024, distance=Distance.COSINE),
            )
            logger.info(f"   Created empty standby '{standby_col}' (nothing to delete)")
            # Switch active slot and exit cleanly — nothing to delete
            logger.info("Step 3/3 — Switching …")
            _write_active_slot(standby)
            logger.info(f"✅ Delete complete (document had no vectors) — new active: {standby.upper()}")
            return 0
        delete_filter = Filter(must=[
            FieldCondition(key="metadata.source", match=MatchValue(value=filename))
        ])
        before = client.count(collection_name=standby_col,
                              count_filter=delete_filter, exact=True).count
        if before == 0:
            records  = _load_registry()
            matching = [r for r in records if r.get("filename") == filename]
            if matching:
                abs_path = matching[0].get("path", "")
                delete_filter = Filter(must=[
                    FieldCondition(key="metadata.source",
                                   match=MatchValue(value=abs_path))
                ])
                before = client.count(collection_name=standby_col,
                                      count_filter=delete_filter, exact=True).count

        client.delete(collection_name=standby_col, points_selector=delete_filter)
        logger.info(f"   Removed {before} vector(s) for '{filename}'")

        # Step 3 — switch
        logger.info("Step 3/3 — Switching …")
        _write_active_slot(standby)
        logger.info(f"✅ Delete complete — new active: {standby.upper()}")
        return before


# ═════════════════════════════════════════════════════════════════════════════
# EmbeddingManager
# ═════════════════════════════════════════════════════════════════════════════

class EmbeddingManager:

    def __init__(self):
        from langchain_ollama import OllamaEmbeddings
        logger.info(f"Initializing embedding model: {Config.EMBEDDING_MODEL}")
        self.embedding_model = OllamaEmbeddings(model=Config.EMBEDDING_MODEL)
        logger.info("✅ Embedding model initialized")

    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        """
        Call Ollama /api/embed directly via requests.
        Thread-safe, no LangChain overhead, no subprocess.  Ollama can return
        a transient timeout while loading a cold embedding model, so retry it.
        """
        import requests as _req
        attempts = max(1, Config.EMBEDDING_RETRIES + 1)
        data = None

        for attempt in range(1, attempts + 1):
            try:
                resp = _req.post(
                    "http://127.0.0.1:11434/api/embed",
                    json={"model": Config.EMBEDDING_MODEL, "input": texts},
                    timeout=Config.EMBEDDING_TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()
                break
            except (_req.RequestException, ValueError) as exc:
                if attempt == attempts:
                    raise RuntimeError(
                        f"Ollama embedding failed after {attempts} attempt(s): {exc}"
                    ) from exc
                logger.warning(
                    "Ollama embedding attempt %d/%d failed (%s); retrying in 5 seconds...",
                    attempt, attempts, exc,
                )
                time.sleep(5)

        assert data is not None
        # Ollama returns {"embeddings": [[...]]} or {"embedding": [...]} depending on version
        if "embeddings" in data:
            return data["embeddings"]
        # Single text fallback
        return [data["embedding"]]

    def create_vector_store(self, chunks, source_path: str = ""):
        """Add chunks via blue/green pipeline. No file locks — HTTP only."""
        from langchain_qdrant import QdrantVectorStore

        filename = (source_path if source_path.startswith(("http://", "https://"))
                    else os.path.basename(source_path)) if source_path else ""

        if filename and _is_already_ingested(filename):
            logger.warning(f"⚠️  '{filename}' already in knowledge base — skipping.")
            return None

        if not chunks:
            raise ValueError(
                f"Cannot embed empty chunk list for '{filename or 'unknown'}'. "
                "No content was extracted from the document."
            )

        with _write_lock:
            active      = _read_active_slot()
            standby     = _standby_slot(active)
            active_col  = _collection_name(active)
            standby_col = _collection_name(standby)
            client      = _get_qdrant_client()

            logger.info(f"\n📥 Add: active={active.upper()} standby={standby.upper()}")
            logger.info(f"   File: {filename or 'unknown'}  Chunks: {len(chunks)}")

            # Step 1 — clone active → standby
            logger.info("Step 1/3 — Cloning active → standby …")
            _clone_collection(client, src=active_col, dst=standby_col)

            # Step 2 — embed into standby in batches via direct Qdrant HTTP upsert.
            # We call Ollama for embeddings directly and upsert via qdrant_client
            # to avoid QdrantVectorStore loading the model into a second process.
            logger.info("Step 2/3 — Embedding chunks into standby …")

            from qdrant_client.models import Distance, VectorParams, PointStruct
            import uuid as _uuid

            BATCH_SIZE    = 8
            total_done    = 0
            total_batches = (len(chunks) + BATCH_SIZE - 1) // BATCH_SIZE

            # Get vector size by embedding one sample text directly via Ollama HTTP
            sample_vecs = self._embed_texts([chunks[0].page_content])
            vector_size = len(sample_vecs[0])

            existing_cols = {c.name for c in client.get_collections().collections}
            if standby_col not in existing_cols:
                client.create_collection(
                    collection_name = standby_col,
                    vectors_config  = VectorParams(size=vector_size, distance=Distance.COSINE),
                )
                logger.info(f"   Created collection '{standby_col}' (dim={vector_size})")

            for batch_num, start in enumerate(range(0, len(chunks), BATCH_SIZE), start=1):
                batch   = chunks[start : start + BATCH_SIZE]
                texts   = [c.page_content for c in batch]
                vectors = self._embed_texts(texts)

                points = [
                    PointStruct(
                        id      = _uuid.uuid4().hex,
                        vector  = vec,
                        payload = {
                            "page_content": chunk.page_content,
                            "metadata":     chunk.metadata,
                        },
                    )
                    for chunk, vec in zip(batch, vectors)
                ]
                client.upsert(collection_name=standby_col, points=points)
                total_done += len(batch)
                logger.info(f"   Batch {batch_num}/{total_batches}: {len(batch)} chunks  ({total_done}/{len(chunks)} total)")

            logger.info(f"   ✅ {total_done} vectors embedded into {standby_col}")

            # Step 3 — switch
            logger.info("Step 3/3 — Switching active slot …")
            _write_active_slot(standby)

            if filename:
                _register_document(filename, source_path, len(chunks))
                logger.info(f"   ✅ Registered '{filename}'")

            logger.info(f"✅ Add complete — new active: {standby.upper()}")

        return self.load_vector_store()

    def load_vector_store(self):
        """Return QdrantVectorStore pointed at active slot via HTTP."""
        from langchain_qdrant import QdrantVectorStore

        active_col = get_active_collection_name()
        client     = _get_qdrant_client()
        existing   = {c.name for c in client.get_collections().collections}

        if active_col not in existing:
            raise Exception(
                "No documents have been processed yet. Please upload a document first."
            )

        return QdrantVectorStore(
            client          = client,
            collection_name = active_col,
            embedding       = self.embedding_model,
        )

    def vector_store_exists(self) -> bool:
        try:
            client   = _get_qdrant_client()
            existing = {c.name for c in client.get_collections().collections}
            return get_active_collection_name() in existing
        except Exception:
            return False

    def delete_vector_store(self) -> bool:
        """Drop both collections and reset to clean state."""
        try:
            client = _get_qdrant_client()
            for slot in (BLUE, GREEN):
                col = _collection_name(slot)
                try:
                    client.delete_collection(col)
                    logger.info(f"🗑️  Dropped '{col}'")
                except Exception:
                    pass
            _write_active_slot(BLUE)
            _save_registry([])
            logger.info("🗑️  Full reset complete")
            return True
        except Exception as exc:
            logger.error(f"Failed to reset: {exc}")
            return False
