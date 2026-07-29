"""
Document loader — detects file type and routes to the correct extractor.

Supported formats
-----------------
PDF   → PyPDFLoader (unchanged — do not modify)
CSV   → CSVLoader   (unchanged — do not modify)
PPTX  → UnstructuredPowerPointLoader + OCR fallback (unchanged — do not modify)
DOCX  → python-docx  (new)
DOC   → python-docx via fallback  (new)
XLSX  → openpyxl     (new)
XLS   → xlrd via openpyxl  (new)
TXT   → plain read   (new)
RTF   → striprtf     (new)
"""

# ── stdlib ───────────────────────────────────────────────────────────────────
import io
import os
import shutil
from datetime import datetime

# ── pptx / OCR (existing) ────────────────────────────────────────────────────
from pptx import Presentation
from PIL import Image
import pytesseract
pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

# ── LangChain ────────────────────────────────────────────────────────────────
from langchain_core.documents import Document
from langchain_community.document_loaders import (
    PyPDFLoader,
    CSVLoader,
)
from langchain_text_splitters.character import RecursiveCharacterTextSplitter

# ── project ──────────────────────────────────────────────────────────────────
from config import Config
from utils.logger import get_logger
from utils.chunker import chunk_documents
from utils.embeddings import EmbeddingManager

logger = get_logger(__name__)

# ── LangSmith ────────────────────────────────────────────────────────────────
if Config.LANGCHAIN_TRACING_V2:
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"]     = Config.LANGCHAIN_API_KEY
    os.environ["LANGCHAIN_PROJECT"]     = Config.LANGCHAIN_PROJECT

try:
    from langsmith import traceable as _traceable
    _LANGSMITH_AVAILABLE = True
except ImportError:
    # LangSmith not installed — define a no-op decorator so the rest of the
    # code is identical whether tracing is on or off.
    def _traceable(**_kwargs):
        def _decorator(fn):
            return fn
        return _decorator
    _LANGSMITH_AVAILABLE = False


# ════════════════════════════════════════════════════════════════════════════
# EXISTING HELPERS — DO NOT MODIFY
# ════════════════════════════════════════════════════════════════════════════

def _ocr_image(image_bytes, min_width=1600):
    img = Image.open(io.BytesIO(image_bytes)).convert("L")
    if img.width < min_width:
        scale = min_width / img.width
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    return pytesseract.image_to_string(img)


def load_pptx_with_ocr(file_path):
    """
    Load a .pptx file, OCR-ing any full-slide (or embedded) pictures,
    and return a list of LangChain Document objects — one per slide,
    matching the interface UnstructuredPowerPointLoader / PyPDFLoader use.
    """
    prs = Presentation(file_path)
    documents = []

    for i, slide in enumerate(prs.slides, start=1):
        slide_text_parts = []

        for shape in slide.shapes:
            if shape.shape_type == 13:  # PICTURE
                text = _ocr_image(shape.image.blob)
                if text.strip():
                    slide_text_parts.append(text.strip())
            elif getattr(shape, "has_text_frame", False):
                text = shape.text_frame.text.strip()
                if text:
                    slide_text_parts.append(text)

        page_content = "\n".join(slide_text_parts).strip()

        if page_content:
            documents.append(
                Document(
                    page_content=page_content,
                    metadata={
                        "source": file_path,
                        "slide_number": i,
                        "extraction_method": "ocr",
                    },
                )
            )

    print(f"[OCR loader] Extracted text from {len(documents)}/{len(prs.slides)} slides")
    return documents


def _pptx_has_real_text(documents, min_chars=30):
    """
    Heuristic: if UnstructuredPowerPointLoader barely extracted anything,
    the deck is almost certainly image-only slides.
    """
    total_chars = sum(len(doc.page_content.strip()) for doc in documents)
    return total_chars >= min_chars


def _load_pptx_text(file_path: str) -> list:
    """
    Extract text from a .pptx file using python-pptx directly.
    Returns one Document per slide (non-empty slides only).
    Falls back to OCR if a slide has no text shapes at all (image-only slide).
    """
    prs = Presentation(file_path)
    documents = []

    for i, slide in enumerate(prs.slides, start=1):
        text_parts = []
        has_picture = False

        for shape in slide.shapes:
            if shape.shape_type == 13:  # PICTURE
                has_picture = True
            if getattr(shape, "has_text_frame", False):
                text = shape.text_frame.text.strip()
                if text:
                    text_parts.append(text)

        content = "\n".join(text_parts).strip()

        if content:
            documents.append(
                Document(
                    page_content=content,
                    metadata={
                        "source": file_path,
                        "slide_number": i,
                        "extraction_method": "pptx_text",
                    },
                )
            )
        elif has_picture:
            # Image-only slide — try OCR if Tesseract is available, skip otherwise
            for shape in slide.shapes:
                if shape.shape_type == 13:
                    try:
                        ocr_text = _ocr_image(shape.image.blob)
                        if ocr_text.strip():
                            documents.append(
                                Document(
                                    page_content=ocr_text.strip(),
                                    metadata={
                                        "source": file_path,
                                        "slide_number": i,
                                        "extraction_method": "ocr",
                                    },
                                )
                            )
                            break  # one OCR doc per slide is enough
                    except Exception:
                        # Tesseract not installed or OCR failed — skip this slide
                        logger.warning(
                            f"  Slide {i}: image-only, OCR skipped "
                            f"(Tesseract not available)"
                        )
                        break

    logger.info(
        f"[PPTX loader] Extracted text from {len(documents)}/{len(prs.slides)} slides"
    )
    return documents


# ════════════════════════════════════════════════════════════════════════════
# NEW EXTRACTORS
# ════════════════════════════════════════════════════════════════════════════

def _load_docx(file_path: str) -> list:
    """
    Extract text from a .docx file using python-docx.
    Returns one Document per paragraph (non-empty paragraphs only).
    Tables are also extracted cell-by-cell.
    Note: legacy .doc (binary) format is not supported by python-docx;
    the user should convert to .docx first.
    """
    try:
        import docx  # python-docx
    except ImportError:
        raise ImportError(
            "python-docx is required to load .docx files. "
            "Install it with: pip install python-docx"
        )

    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".doc":
        raise Exception(
            "Legacy .doc (Word 97-2003) format is not supported. "
            "Please save the file as .docx (Word 2007+) and re-upload."
        )

    try:
        doc = docx.Document(file_path)
    except Exception as e:
        raise Exception(f"Could not open Word document: {e}")

    text_parts = []

    # Body paragraphs
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            text_parts.append(text)

    # Tables
    for table in doc.tables:
        for row in table.rows:
            row_texts = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if row_texts:
                text_parts.append(" | ".join(row_texts))

    full_text = "\n".join(text_parts)
    if not full_text.strip():
        return []

    return [
        Document(
            page_content=full_text,
            metadata={"source": file_path, "file_type": "docx"},
        )
    ]


def _load_xlsx(file_path: str) -> list:
    """
    Extract text from a .xlsx / .xls file using openpyxl.
    Returns one Document per sheet with rows formatted as pipe-separated text.
    """
    try:
        import openpyxl
    except ImportError:
        raise ImportError(
            "openpyxl is required to load .xlsx files. "
            "Install it with: pip install openpyxl"
        )

    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".xls":
        # openpyxl cannot read legacy .xls — use xlrd via read_only mode
        try:
            import xlrd
            workbook = xlrd.open_workbook(file_path)
            documents = []
            for sheet_name in workbook.sheet_names():
                sheet = workbook.sheet_by_name(sheet_name)
                rows = []
                for row_idx in range(sheet.nrows):
                    cells = [str(sheet.cell_value(row_idx, col)).strip()
                             for col in range(sheet.ncols)]
                    cells = [c for c in cells if c]
                    if cells:
                        rows.append(" | ".join(cells))
                if rows:
                    documents.append(
                        Document(
                            page_content="\n".join(rows),
                            metadata={
                                "source": file_path,
                                "sheet": sheet_name,
                                "file_type": "xls",
                            },
                        )
                    )
            return documents
        except ImportError:
            raise ImportError(
                "xlrd is required to load legacy .xls files. "
                "Install it with: pip install xlrd"
            )

    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    documents = []

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = []
        for row in ws.iter_rows(values_only=True):
            cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
            if cells:
                rows.append(" | ".join(cells))

        if rows:
            documents.append(
                Document(
                    page_content="\n".join(rows),
                    metadata={
                        "source": file_path,
                        "sheet": sheet_name,
                        "file_type": "xlsx",
                    },
                )
            )

    wb.close()
    return documents


def _load_txt(file_path: str) -> list:
    """
    Extract text from a plain .txt file.
    Tries UTF-8 first, falls back to latin-1.
    """
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            with open(file_path, "r", encoding=encoding) as f:
                content = f.read().strip()
            if content:
                return [
                    Document(
                        page_content=content,
                        metadata={"source": file_path, "file_type": "txt"},
                    )
                ]
            return []
        except UnicodeDecodeError:
            continue

    raise ValueError(f"Could not decode text file: {file_path}")


def _load_rtf(file_path: str) -> list:
    """
    Extract plain text from a .rtf file using striprtf.
    """
    try:
        from striprtf.striprtf import rtf_to_text
    except ImportError:
        raise ImportError(
            "striprtf is required to load .rtf files. "
            "Install it with: pip install striprtf"
        )

    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            with open(file_path, "r", encoding=encoding) as f:
                raw = f.read()
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"Could not decode RTF file: {file_path}")

    content = rtf_to_text(raw).strip()
    if not content:
        return []

    return [
        Document(
            page_content=content,
            metadata={"source": file_path, "file_type": "rtf"},
        )
    ]


# ════════════════════════════════════════════════════════════════════════════
# MAIN ROUTER — load_document()
# ════════════════════════════════════════════════════════════════════════════

def load_document(file_path: str) -> list:
    """
    Detect file type by extension and route to the correct loader.
    Returns a list of LangChain Document objects.

    PDF / CSV / PPTX pipelines are untouched from the original implementation.
    """

    extension = os.path.splitext(file_path)[1].lower()
    logger.info(f"Detected file extension: '{extension}' for '{os.path.basename(file_path)}'")

    # ── PDF (original — untouched) ──────────────────────────────────────────
    if extension == ".pdf":
        loader = PyPDFLoader(file_path)
        logger.info(f"Loading PDF document: {file_path}")
        documents = loader.load()

    # ── CSV (original — untouched) ──────────────────────────────────────────
    elif extension == ".csv":
        loader = CSVLoader(file_path)
        documents = loader.load()

    # ── PPTX / PPT — pure python-pptx (fast, no Unstructured hang) ─────────
    elif extension in (".ppt", ".pptx"):
        logger.info(f"Loading PowerPoint: {os.path.basename(file_path)}")
        documents = _load_pptx_text(file_path)

    # ── DOCX / DOC (new) ────────────────────────────────────────────────────
    elif extension in (".docx", ".doc"):
        logger.info(f"Loading Word document: {os.path.basename(file_path)}")
        documents = _load_docx(file_path)

    # ── XLSX / XLS (new) ────────────────────────────────────────────────────
    elif extension in (".xlsx", ".xls"):
        logger.info(f"Loading Excel spreadsheet: {os.path.basename(file_path)}")
        documents = _load_xlsx(file_path)

    # ── TXT (new) ────────────────────────────────────────────────────────────
    elif extension == ".txt":
        logger.info(f"Loading plain text file: {os.path.basename(file_path)}")
        documents = _load_txt(file_path)

    # ── RTF (new) ────────────────────────────────────────────────────────────
    elif extension == ".rtf":
        logger.info(f"Loading RTF file: {os.path.basename(file_path)}")
        documents = _load_rtf(file_path)

    else:
        raise Exception(
            f"Unsupported file type '{extension}'. "
            "Supported: PDF, DOCX, DOC, XLSX, XLS, PPTX, PPT, CSV, TXT, RTF"
        )

    logger.info(f"Loaded {len(documents)} document(s) from {file_path}")
    return documents


# ════════════════════════════════════════════════════════════════════════════
# PROCESS PIPELINE (unchanged logic, updated logging)
# ════════════════════════════════════════════════════════════════════════════

def create_chunks(documents):
    """Split documents into chunks (kept for backward compatibility)."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=Config.CHUNK_SIZE,
        chunk_overlap=Config.CHUNK_OVERLAP,
    )
    return splitter.split_documents(documents)


@_traceable(
    name="process_document",
    run_type="chain",
    tags=["ingestion", "docmind"],
    metadata={"component": "loader"},
)
def process_document(file_path: str) -> str:
    """
    Full ingestion pipeline:
      1. Detect type → load
      2. Chunk
      3. Embed → save / merge FAISS index
    Returns a human-readable result string.

    Decorated with @traceable so the entire pipeline appears as a single
    top-level run in LangSmith, with child spans for each step.
    """
    filename  = os.path.basename(file_path)
    extension = os.path.splitext(file_path)[1].lower().lstrip(".")

    logger.info("=" * 80)
    logger.info("📄 DOCUMENT PROCESSING STARTED")
    logger.info(f"File path : {file_path}")
    logger.info(f"Timestamp : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        # Step 1 — Load
        logger.info("Step 1: Loading document...")
        documents = _traced_load(file_path, filename=filename, file_type=extension)
        logger.info(f"✅ Loaded {len(documents)} document section(s)")

        if len(documents) == 0:
            logger.error("❌ No readable content found in document")
            raise Exception("No readable content found.")

        for i, doc in enumerate(documents):
            logger.info(f"  Section {i+1}: {len(doc.page_content)} characters")
            if hasattr(doc, "metadata"):
                logger.info(f"    Metadata: {doc.metadata}")

        # Step 2 — Chunk
        logger.info(
            f"Step 2: Chunking "
            f"(size={Config.CHUNK_SIZE}, overlap={Config.CHUNK_OVERLAP})..."
        )
        chunks = _traced_chunk(documents, filename=filename)
        logger.info(f"✅ Created {len(chunks)} chunks")

        for i, chunk in enumerate(chunks[:5]):
            logger.info(f"  Chunk {i+1}: {len(chunk.page_content)} chars")
            logger.info(f"    Preview: {chunk.page_content[:100]}...")
        if len(chunks) > 5:
            logger.info(f"  … and {len(chunks) - 5} more chunks")

        # Step 3 — Embed + save
        logger.info("Step 3: Creating embeddings and vector store...")
        embedding_manager = EmbeddingManager()
        result = embedding_manager.create_vector_store(chunks, source_path=file_path)

        if result is None:
            return f"'{filename}' is already in the knowledge base. No duplicate added."

        logger.info("✅ Vector store created/updated successfully")
        logger.info("📄 DOCUMENT PROCESSING COMPLETED")
        logger.info("=" * 80)

        return f"Document processed successfully. {len(chunks)} chunks created."

    except Exception as e:
        logger.error(f"❌ Error processing document: {str(e)}")
        logger.error("=" * 80)
        raise


# ── Traced sub-steps (appear as child spans in LangSmith) ───────────────────

@_traceable(
    name="load_document_file",
    run_type="tool",
    tags=["ingestion", "load"],
)
def _traced_load(file_path: str, filename: str = "", file_type: str = "") -> list:
    """Thin wrapper around load_document() so it gets its own LangSmith span."""
    return load_document(file_path)


@_traceable(
    name="chunk_documents",
    run_type="tool",
    tags=["ingestion", "chunking"],
)
def _traced_chunk(documents: list, filename: str = "") -> list:
    """Thin wrapper around chunk_documents() so it gets its own LangSmith span."""
    return chunk_documents(documents)


# ════════════════════════════════════════════════════════════════════════════
# URL INGESTION PIPELINE
# ════════════════════════════════════════════════════════════════════════════

def load_url(url: str) -> str:
    """
    Full ingestion pipeline for a web URL:
      1. Scrape with Playwright → list of LangChain Documents
      2. Chunk
      3. Embed → save to Qdrant

    Re-crawl support: if the URL was previously ingested, its old vectors
    are surgically deleted from Qdrant and the registry entry is removed
    before re-ingesting fresh content.

    Returns a human-readable result string.
    """
    from utils.scraper import scrape_url
    from utils.embeddings import (
        delete_document_chunks,
        _load_registry,
        _save_registry,
        REGISTRY_FILE,
    )

    logger.info("=" * 80)
    logger.info("🌐  URL INGESTION STARTED")
    logger.info(f"  URL       : {url}")
    logger.info(f"  Timestamp : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 80)

    try:
        # ── Re-crawl: remove old data if URL was previously ingested ──────
        registry = _load_registry()
        # Guard against null/malformed registry entries
        registry = [r for r in registry if r is not None]
        existing = [r for r in registry if r.get("filename") == url]

        if existing:
            logger.info(f"  🔄  URL already ingested — removing old data for re-crawl...")
            deleted = delete_document_chunks(url)
            logger.info(f"  🗑️  Deleted {deleted} old vector(s)")
            # Remove from registry
            registry = [r for r in registry if r.get("filename") != url]
            _save_registry(registry)
            logger.info(f"  ✅  Old registry entry removed — starting fresh crawl")

        # ── Step 1: Scrape ─────────────────────────────────────────────────
        logger.info("  Step 1: Scraping URL...")
        documents = scrape_url(url)
        logger.info(f"  ✅  Scraped {len(documents)} section document(s)")

        if not documents:
            raise Exception("No content extracted from URL.")

        # Guard: ensure every document has a metadata dict (never None)
        for doc in documents:
            if doc.metadata is None:
                doc.metadata = {"source": url, "source_type": "url"}

        # ── Step 2: Chunk ──────────────────────────────────────────────────
        logger.info(
            f"  Step 2: Chunking "
            f"(size={Config.CHUNK_SIZE}, overlap={Config.CHUNK_OVERLAP})..."
        )
        chunks = chunk_documents(documents)
        logger.info(f"  ✅  Created {len(chunks)} chunks")

        # ── Step 3: Embed + save to Qdrant ────────────────────────────────
        logger.info("  Step 3: Embedding and storing in Qdrant...")
        embedding_manager = EmbeddingManager()

        # Pass url as source_path so registry stores the URL as the identifier
        result = embedding_manager.create_vector_store(chunks, source_path=url)

        if result is None:
            # Shouldn't happen after re-crawl cleanup, but guard anyway
            return f"URL already in knowledge base: {url}"

        logger.info("  ✅  Vectors stored in Qdrant")
        logger.info("=" * 80)
        logger.info("🌐  URL INGESTION COMPLETE")
        logger.info("=" * 80)

        return f"URL scraped and ingested successfully. {len(chunks)} chunks created."

    except Exception as e:
        logger.error(f"  ❌  Error ingesting URL: {str(e)}")
        logger.error("=" * 80)
        raise
