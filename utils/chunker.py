"""
utils/chunker.py
~~~~~~~~~~~~~~~~
Splits documents into chunks and applies contextual enrichment.

Contextual enrichment (Anthropic-style):
  Every chunk gets a header prepended BEFORE embedding:

      [Document: KodiaqRS.pdf | Page: 5]
      Surrender to the colours
      Moon White, Magic Black, Velvet Red, Steel Grey

  This bakes the document identity into the vector itself so the
  retriever always knows which document/page a chunk belongs to —
  even when the chunk text has no car name or document reference.

  The original text is preserved in metadata["original_content"]
  so the LLM always reads clean text, not the header-prefixed version.

  Why this works:
  - Embedding encodes "KodiaqRS + colours" together → correct retrieval
  - No merging, no size thresholds, no contamination between chunks
  - Works for PDFs, DOCX, XLSX, PPTX, URLs — all document types
"""

import os

from langchain_core.documents import Document
from langchain_text_splitters.character import RecursiveCharacterTextSplitter

from config import Config
from utils.logger import get_logger

logger = get_logger(__name__)


def chunk_documents(documents: list) -> list:
    """
    Split documents into chunks and apply contextual enrichment.

    Each output chunk has:
      - page_content : enriched text (header + original) → embedded into Qdrant
      - metadata     : original metadata + original_content (clean text for LLM)
    """
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size    = Config.CHUNK_SIZE,
        chunk_overlap = Config.CHUNK_OVERLAP,
        separators    = ["\n\n", "\n", ". ", " ", ""],
    )

    raw_chunks = text_splitter.split_documents(documents)
    enriched   = [_enrich(chunk) for chunk in raw_chunks]

    logger.info(f"Created {len(enriched)} chunks from {len(documents)} document(s).")
    return enriched


def _enrich(chunk: Document) -> Document:
    """
    Prepend a context header to the chunk text before embedding.

    Header format:
        [Document: <filename> | Page: <n>]

    The original clean text is stored in metadata["original_content"]
    so callers can access it if needed (e.g. for display).
    """
    meta     = chunk.metadata or {}
    original = chunk.page_content

    # ── Resolve document name ────────────────────────────────────────────────
    # LangChain loaders set metadata["source"] to the file path or URL.
    source = meta.get("source", "")
    if source.startswith(("http://", "https://")):
        # For URLs use the domain + path, not the full URL
        doc_name = source
    else:
        doc_name = os.path.basename(source) if source else "Unknown Document"

    # ── Resolve page number ──────────────────────────────────────────────────
    # Different loaders use different keys: "page", "page_number", "slide_number"
    page = (
        meta.get("page") or
        meta.get("page_number") or
        meta.get("slide_number")
    )
    page_str = f" | Page: {page}" if page is not None else ""

    # ── Build header ─────────────────────────────────────────────────────────
    header = f"[Document: {doc_name}{page_str}]\n"

    # ── Return enriched chunk ────────────────────────────────────────────────
    enriched_meta = dict(meta)
    enriched_meta["original_content"] = original   # clean text preserved

    return Document(
        page_content = header + original,
        metadata     = enriched_meta,
    )


# ── Helpers (unchanged public interface) ────────────────────────────────────

def get_chunk_count(chunks: list) -> int:
    return len(chunks)


def preview_chunks(chunks: list, count: int = 3) -> list:
    previews = []
    for chunk in chunks[:count]:
        previews.append({
            "length":   len(chunk.page_content),
            "text":     chunk.page_content[:200],
            "original": chunk.metadata.get("original_content", "")[:200],
        })
    return previews
