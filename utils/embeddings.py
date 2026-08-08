"""
utils/embeddings.py
~~~~~~~~~~~~~~~~~~~
Blue/Green vector database strategy using Qdrant HTTP server mode.

Slot layout:
    docmind_blue   ← one Qdrant collection
    docmind_green  ← other Qdrant collection

active_slot.json (inside QDRANT_PATH):
    {"active": "blue"} or {"active": "green"}

Flow for every add/delete:
    1. Acquire cross-process file lock  (portalocker — works across app.py + admin_app.py)
    2. Clone active → standby           (users query active throughout, zero interruption)
    3. Modify standby                   (add or delete)
    4. Atomic pointer switch            (~1 ms JSON write via tmp + os.replace)
    5. Release lock

Rollback on any failure in steps 2-4:
    • The active slot pointer is restored to its original value
    • The dirty standby collection is dropped from Qdrant
    • The caller receives a clean exception — nothing is left half-written

Registry writes are always atomic (write to .tmp → os.replace) so a crash
mid-write can never corrupt registry.json.
"""

from __future__ import annotations

import json
import os
import time
import threading
from datetime import datetime
from pathlib import Path

import portalocker          # cross-process file locking (already in requirements.txt)

from config import Config
from utils.logger import get_logger

logger = get_logger(__name__)

# ── Slot names ────────────────────────────────────────────────────────────────
BLUE  = "blue"
GREEN = "green"

# ── File paths ────────────────────────────────────────────────────────────────
REGISTRY_FILE    = os.path.join(Config.QDRANT_PATH, "registry.json")
ACTIVE_SLOT_FILE = os.path.join(Config.QDRANT_PATH, Config.ACTIVE_SLOT_FILE)

# Cross-process lock file — one file covers both app.py and admin_app.py
_LOCK_FILE = os.path.join(Config.QDRANT_PATH, "write.lock")

# In-process threading lock — guards against concurrent threads within one process
# (the portalocker handles inter-process; this handles intra-process)
_thread_lock = threading.Lock()


# ═════════════════════════════════════════════════════════════════════════════
# Cross-process + cross-thread write lock
# ═════════════════════════════════════════════════════════════════════════════

class _WriteLock:
    """
    Combines threading.Lock (intra-process) with portalocker (inter-process).
    Use as a context manager:

        with _WriteLock():
            ...  # only one thread/process inside here at a time
    """
    TIMEOUT = 600   # seconds — longest expected embedding job

    def __enter__(self):
        os.makedirs(Config.QDRANT_PATH, exist_ok=True)
        self._thread_acquired = _thread_lock.acquire(timeout=self.TIMEOUT)
        if not self._thread_acquired:
            raise TimeoutError("Could not acquire intra-process write lock after 10 min.")
        try:
            self._fh = open(_LOCK_FILE, "w")
            portalocker.lock(self._fh, portalocker.LOCK_EX | portalocker.LOCK_NB)
            # If lock is held by another process, poll until timeout
            deadline = time.monotonic() + self.TIMEOUT
            while True:
                try:
                    portalocker.lock(self._fh, portalocker.LOCK_EX | portalocker.LOCK_NB)
                    break
                except portalocker.LockException:
                    if time.monotonic() > deadline:
                        raise TimeoutError(
                            "Could not acquire cross-process write lock after 10 min. "
                            "Another ingestion job may be stuck."
                        )
                    time.sleep(0.5)
        except Exception:
            _thread_lock.release()
            raise
        return self

    def __exit__(self, *_):
        try:
            portalocker.unlock(self._fh)
            self._fh.close()
        except Exception:
            pass
        finally:
            if self._thread_acquired:
                _thread_lock.release()


_write_lock = _WriteLock()   # singleton — used everywhere


# ═════════════════════════════════════════════════════════════════════════════
# Qdrant HTTP client helper
# ═════════════════════════════════════════════════════════════════════════════

def _get_qdrant_client():
    from qdrant_client import QdrantClient
    return QdrantClient(
        host    = Config.QDRANT_HOST,
        port    = Config.QDRANT_PORT,
        timeout = 60,
    )


# ═════════════════════════════════════════════════════════════════════════════
# Registry helpers — all writes are atomic (tmp → replace)
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
    """Atomic write: serialise to a .tmp file then os.replace() it into place.
    If the process dies mid-write the old registry.json is left intact."""
    os.makedirs(Config.QDRANT_PATH, exist_ok=True)
    tmp = REGISTRY_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    os.replace(tmp, REGISTRY_FILE)


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
    """Atomic write via tmp + os.replace — crash-safe."""
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
        if dst in existing:
            client.delete_collection(dst)
        logger.info(f"📋 Source '{src}' is empty — standby will be created fresh")
        return 0

    src_info    = client.get_collection(src)
    vectors_cfg = src_info.config.params.vectors
    if hasattr(vectors_cfg, "size"):
        pass  # used directly below
    elif isinstance(vectors_cfg, dict):
        pass
    else:
        vectors_cfg = VectorParams(size=1024, distance=Distance.COSINE)

    if dst in existing:
        client.delete_collection(dst)
    client.create_collection(
        collection_name = dst,
        vectors_config  = vectors_cfg,
    )

    BATCH  = 256
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


def _drop_collection_safe(client, name: str) -> None:
    """Drop a collection, ignoring errors (used in rollback)."""
    try:
        existing = {c.name for c in client.get_collections().collections}
        if name in existing:
            client.delete_collection(name)
            logger.info(f"🧹 Rolled back: dropped '{name}'")
    except Exception as exc:
        logger.warning(f"  Rollback drop failed for '{name}': {exc}")


# ═════════════════════════════════════════════════════════════════════════════
# Public: delete chunks  — with rollback
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

        # ── Step 1 — clone active → standby ──────────────────────────────
        logger.info("Step 1/3 — Cloning active → standby …")
        try:
            _clone_collection(client, src=active_col, dst=standby_col)
        except Exception as exc:
            logger.error(f"  Clone failed during delete: {exc} — aborting, nothing changed")
            raise RuntimeError(f"Delete aborted (clone failed): {exc}") from exc

        # ── Step 2 — delete from standby ─────────────────────────────────
        logger.info(f"Step 2/3 — Deleting '{filename}' from standby …")
        try:
            existing_cols = {c.name for c in client.get_collections().collections}
            if standby_col not in existing_cols:
                from qdrant_client.models import VectorParams, Distance
                client.create_collection(
                    collection_name = standby_col,
                    vectors_config  = VectorParams(size=1024, distance=Distance.COSINE),
                )
                logger.info(f"   Created empty standby '{standby_col}' (nothing to delete)")
                # Nothing to delete — just switch
                _write_active_slot(standby)
                logger.info(f"✅ Delete complete (no vectors) — new active: {standby.upper()}")
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

        except Exception as exc:
            logger.error(f"  Delete from standby failed: {exc} — rolling back")
            _drop_collection_safe(client, standby_col)
            # Active slot is unchanged — no switch happened yet — nothing broken
            raise RuntimeError(f"Delete failed (standby modify): {exc}") from exc

        # ── Step 3 — switch pointer ───────────────────────────────────────
        logger.info("Step 3/3 — Switching …")
        try:
            _write_active_slot(standby)
        except Exception as exc:
            # Pointer write failed — rollback standby, keep original active
            logger.error(f"  Slot switch failed: {exc} — rolling back")
            _drop_collection_safe(client, standby_col)
            raise RuntimeError(f"Delete failed (slot switch): {exc}") from exc

        logger.info(f"✅ Delete complete — new active: {standby.upper()}")
        return before


# ═════════════════════════════════════════════════════════════════════════════
# EmbeddingManager — with rollback on create_vector_store failure
# ═════════════════════════════════════════════════════════════════════════════

class EmbeddingManager:

    def __init__(self):
        from langchain_ollama import OllamaEmbeddings
        logger.info(f"Initializing embedding model: {Config.EMBEDDING_MODEL}")
        self.embedding_model = OllamaEmbeddings(model=Config.EMBEDDING_MODEL)
        logger.info("✅ Embedding model initialized")

    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Call Ollama /api/embed directly. Retries on transient failures."""
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
                    "Ollama embedding attempt %d/%d failed (%s); retrying in 5 s…",
                    attempt, attempts, exc,
                )
                time.sleep(5)

        assert data is not None
        if "embeddings" in data:
            return data["embeddings"]
        return [data["embedding"]]

    def create_vector_store(self, chunks, source_path: str = ""):
        """
        Add chunks via the blue/green pipeline.

        Rollback guarantee
        ------------------
        If any step after clone fails (embed crash, slot write error, etc.):
          1. The dirty standby collection is dropped from Qdrant
          2. The active slot pointer is left at its original value
          3. The uploaded physical file is NOT removed here — the caller owns cleanup
          4. A RuntimeError is raised so the job is marked as failed
        """
        from qdrant_client.models import Distance, VectorParams, PointStruct
        import uuid as _uuid

        filename = (source_path if source_path.startswith(("http://", "https://"))
                    else os.path.basename(source_path)) if source_path else ""

        # ── Duplicate check (outside lock — fast path) ────────────────────
        if filename and _is_already_ingested(filename):
            logger.warning(f"⚠️  '{filename}' already in knowledge base — skipping.")
            # Remove the duplicate file from disk so uploads/ does not bloat
            if source_path and not source_path.startswith(("http://", "https://")):
                if os.path.exists(source_path):
                    try:
                        os.remove(source_path)
                        logger.info(f"🧹 Removed duplicate file from disk: {source_path}")
                    except OSError as rm_err:
                        logger.warning(f"  Could not remove duplicate file: {rm_err}")
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

            # ── Step 1 — clone active → standby ──────────────────────────
            logger.info("Step 1/3 — Cloning active → standby …")
            try:
                _clone_collection(client, src=active_col, dst=standby_col)
            except Exception as exc:
                logger.error(f"  Clone failed: {exc} — aborting, nothing changed")
                raise RuntimeError(f"Ingestion aborted (clone failed): {exc}") from exc

            # ── Step 2 — embed chunks into standby ───────────────────────
            logger.info("Step 2/3 — Embedding chunks into standby …")
            try:
                BATCH_SIZE    = 8
                total_done    = 0
                total_batches = (len(chunks) + BATCH_SIZE - 1) // BATCH_SIZE

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
                    logger.info(
                        f"   Batch {batch_num}/{total_batches}: "
                        f"{len(batch)} chunks  ({total_done}/{len(chunks)} total)"
                    )

                logger.info(f"   ✅ {total_done} vectors embedded into {standby_col}")

            except Exception as exc:
                logger.error(f"  Embedding failed: {exc} — rolling back standby")
                _drop_collection_safe(client, standby_col)
                raise RuntimeError(f"Ingestion failed (embedding): {exc}") from exc

            # ── Step 3 — switch pointer ───────────────────────────────────
            logger.info("Step 3/3 — Switching active slot …")
            try:
                _write_active_slot(standby)
            except Exception as exc:
                logger.error(f"  Slot switch failed: {exc} — rolling back")
                _drop_collection_safe(client, standby_col)
                raise RuntimeError(f"Ingestion failed (slot switch): {exc}") from exc

            # ── Register document ─────────────────────────────────────────
            if filename:
                try:
                    _register_document(filename, source_path, len(chunks))
                    logger.info(f"   ✅ Registered '{filename}'")
                except Exception as reg_err:
                    # Registry write failure is non-fatal — vectors are live.
                    # Log it prominently so the admin notices.
                    logger.error(
                        f"  ⚠️  Registry write failed for '{filename}': {reg_err}. "
                        "Vectors are live but the document won't appear in the KB table "
                        "until the registry is repaired."
                    )

            logger.info(f"✅ Add complete — new active: {standby.upper()}")

        return self.load_vector_store()

    def load_vector_store(self):
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
