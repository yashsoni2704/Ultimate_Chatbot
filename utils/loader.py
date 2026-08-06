"""
Document loader — detects file type and routes to the correct extractor.

Supported formats
-----------------
PDF   → pdfplumber  (primary)  + PyPDFLoader fallback + OCR fallback
CSV   → CSVLoader
PPTX  → python-pptx + OCR fallback
DOCX  → python-docx + parallel image OCR
DOC   → python-docx via fallback
XLSX  → openpyxl + parallel image OCR
XLS   → xlrd
TXT   → plain read
RTF   → striprtf

OCR pipeline (all formats)
--------------------------
• 2× upscale when the image is narrower than 1600 px
• Grayscale conversion before Tesseract
• ThreadPoolExecutor for parallel OCR across all images on a page/slide/sheet
• OCR text is **appended to the same page/slide/sheet Document** so the
  page-image relationship is preserved and everything chunks together.
"""

# ── stdlib ───────────────────────────────────────────────────────────────────
import io
import os
import shutil
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# ── pptx / OCR ───────────────────────────────────────────────────────────────
from pptx import Presentation
from PIL import Image
import pytesseract
pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

# ── LangChain ────────────────────────────────────────────────────────────────
from langchain_core.documents import Document
from langchain_community.document_loaders import CSVLoader
from langchain_text_splitters.character import RecursiveCharacterTextSplitter

# ── project ──────────────────────────────────────────────────────────────────
from config import Config
from utils.logger import get_logger
from utils.chunker import chunk_documents, _enrich
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
    def _traceable(**_kwargs):
        def _decorator(fn):
            return fn
        return _decorator
    _LANGSMITH_AVAILABLE = False


# ════════════════════════════════════════════════════════════════════════════
# Shared OCR helpers
# ════════════════════════════════════════════════════════════════════════════

_OCR_MIN_WIDTH = 1600   # upscale target (px)
_OCR_WORKERS   = 4      # parallel Tesseract threads


def _ocr_image(image_bytes: bytes, min_width: int = _OCR_MIN_WIDTH) -> str:
    """
    Preprocess a single image (grayscale + 2× upscale when needed) and run
    Tesseract OCR.  Returns the extracted string (may be empty).
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("L")   # grayscale
    if img.width < min_width:
        scale = min_width / img.width
        new_w = int(img.width  * scale)
        new_h = int(img.height * scale)
        img   = img.resize((new_w, new_h), Image.LANCZOS)
    return pytesseract.image_to_string(img)


def _ocr_images_parallel(
    image_blobs: list,
    *,
    max_workers: int = _OCR_WORKERS,
    label: str = "",
) -> list:
    """
    Run _ocr_image on every blob in *image_blobs* using a ThreadPoolExecutor.

    Returns a list of non-empty OCR strings, in the same order as the input
    (blanks are filtered out).

    Parameters
    ----------
    image_blobs : list of bytes
        Raw image data (PNG / JPEG / etc.) to OCR.
    max_workers : int
        Maximum parallel Tesseract threads.
    label : str
        Optional label for log messages (e.g. "slide 3" or "page 5").
    """
    if not image_blobs:
        return []

    results: list = [None] * len(image_blobs)

    def _task(idx: int, blob: bytes):
        try:
            return idx, _ocr_image(blob).strip()
        except Exception as exc:
            logger.warning(f"  OCR failed [{label} img {idx}]: {exc}")
            return idx, ""

    with ThreadPoolExecutor(max_workers=min(max_workers, len(image_blobs))) as pool:
        futures = {pool.submit(_task, i, b): i for i, b in enumerate(image_blobs)}
        for fut in as_completed(futures):
            idx, text = fut.result()
            results[idx] = text

    non_empty = [t for t in results if t]
    if non_empty:
        logger.info(
            f"  OCR [{label}]: {len(non_empty)}/{len(image_blobs)} "
            f"image(s) yielded text"
        )
    return non_empty


# ════════════════════════════════════════════════════════════════════════════
# PPTX loader
# ════════════════════════════════════════════════════════════════════════════

def _pptx_has_real_text(documents, min_chars: int = 30) -> bool:
    total_chars = sum(len(doc.page_content.strip()) for doc in documents)
    return total_chars >= min_chars


def _load_pptx_text(file_path: str) -> list:
    """
    Load a PPTX file.  For each slide:
      1. Collect all shape text-frame content.
      2. Collect all embedded image blobs (shape_type == 13).
      3. OCR the images in parallel.
      4. Append OCR text to the same slide's Document so text and images
         chunk together.

    A Document is created for every slide that has either text or image-OCR
    content.
    """
    prs       = Presentation(file_path)
    documents = []

    for i, slide in enumerate(prs.slides, start=1):
        text_parts  : list = []
        image_blobs : list = []

        for shape in slide.shapes:
            # Collect image blobs
            if shape.shape_type == 13:
                try:
                    image_blobs.append(shape.image.blob)
                except Exception as exc:
                    logger.debug(f"  Slide {i}: could not read image blob — {exc}")

            # Collect text-frame text
            if getattr(shape, "has_text_frame", False):
                t = shape.text_frame.text.strip()
                if t:
                    text_parts.append(t)

        # Parallel OCR for all images on this slide
        ocr_texts = _ocr_images_parallel(
            image_blobs, label=f"slide {i}"
        )
        text_parts.extend(ocr_texts)

        content = "\n".join(text_parts).strip()
        if not content:
            continue

        extraction_method = "pptx_text"
        if ocr_texts and not any(
            shape.has_text_frame and shape.text_frame.text.strip()
            for shape in slide.shapes
            if getattr(shape, "has_text_frame", False)
        ):
            extraction_method = "ocr"
        elif ocr_texts:
            extraction_method = "pptx_text+ocr"

        documents.append(Document(
            page_content=content,
            metadata={
                "source":            file_path,
                "slide_number":      i,
                "extraction_method": extraction_method,
            },
        ))

    logger.info(
        f"[PPTX loader] Extracted text from "
        f"{len(documents)}/{len(prs.slides)} slides"
    )
    return documents


# kept for any external callers that imported it directly
def load_pptx_with_ocr(file_path: str) -> list:
    """Alias — delegates to _load_pptx_text (which now always runs OCR)."""
    return _load_pptx_text(file_path)


# ════════════════════════════════════════════════════════════════════════════
# PDF loader  — pdfplumber (primary) + PyPDFLoader fallback + OCR
# ════════════════════════════════════════════════════════════════════════════

def _pdf_page_image_blobs(page) -> list:
    """
    Extract every embedded raster image from a pdfplumber Page and return
    a list of raw PNG bytes (via PIL round-trip for a consistent format).

    pdfplumber's page.images dicts contain a 'stream' key whose value is a
    pdfminer PDFStream object.  Raw bytes are retrieved via .get_data(), which
    handles any internal compression (FlateDecode, DCTDecode, etc.).

    Pages whose images use unsupported colour spaces (CMYK, ICCBased, etc.)
    are handled by converting through PIL so Tesseract always gets RGB/L.
    """
    blobs = []
    try:
        for img_obj in page.images:
            try:
                stream = img_obj.get("stream")
                if stream is None:
                    continue

                # PDFStream → raw decoded bytes
                raw = stream.get_data()
                if not raw:
                    continue

                # Normalise to PNG via PIL (handles JPEG, CMYK, ICCBased, etc.)
                pil_img = Image.open(io.BytesIO(raw))
                # Convert exotic colour spaces to RGB so PIL can save as PNG
                if pil_img.mode not in ("RGB", "L", "RGBA"):
                    pil_img = pil_img.convert("RGB")
                buf = io.BytesIO()
                pil_img.save(buf, format="PNG")
                blobs.append(buf.getvalue())
            except Exception:
                pass
    except Exception:
        pass
    return blobs


def _load_pdf(file_path: str) -> list:
    """
    Extract text from a PDF using pdfplumber (primary) with PyPDFLoader fallback.

    Per-page strategy
    -----------------
    1. Extract layout text + tables via pdfplumber.
    2. Extract all embedded images from the page.
    3. OCR the images in parallel (2× upscale + grayscale).
    4. Append OCR text to the **same** page Document so image captions,
       labels, and diagram text chunk together with the surrounding prose.
    5. If the page is completely text-free, render it at 200 dpi and OCR the
       whole page as a fallback.

    pdfplumber advantages over PyPDFLoader / pypdf:
      - Extracts floating text boxes and captions (common in designed brochures)
      - Better layout-aware text ordering
      - Handles multi-column layouts more accurately
      - Extracts table content as plain text rows
    """
    documents = []

    try:
        import pdfplumber

        with pdfplumber.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                parts = []

                # ── 1. Regular text ──────────────────────────────────────
                text = page.extract_text(x_tolerance=2, y_tolerance=2)
                if text and text.strip():
                    parts.append(text.strip())

                # ── 2. Tables ────────────────────────────────────────────
                for table in page.extract_tables():
                    if not table:
                        continue
                    rows = []
                    for row in table:
                        cells = [str(c).strip() for c in row
                                 if c and str(c).strip()]
                        if cells:
                            rows.append(" | ".join(cells))
                    if rows:
                        parts.append("\n".join(rows))

                # ── 3. Embedded-image OCR (parallel) ─────────────────────
                image_blobs = _pdf_page_image_blobs(page)
                if image_blobs:
                    ocr_texts = _ocr_images_parallel(
                        image_blobs, label=f"pdf page {i}"
                    )
                    parts.extend(ocr_texts)

                page_content = "\n".join(parts).strip()

                if page_content:
                    documents.append(Document(
                        page_content=page_content,
                        metadata={
                            "source":    file_path,
                            "page":      i,
                            "file_type": "pdf",
                            "extractor": "pdfplumber",
                        }
                    ))
                else:
                    # ── 4. Whole-page OCR fallback (image-only page) ──────
                    logger.info(f"  Page {i}: no text — attempting full-page OCR...")
                    try:
                        img      = page.to_image(resolution=200).original
                        buf      = io.BytesIO()
                        img.save(buf, format="PNG")
                        ocr_text = _ocr_image(buf.getvalue()).strip()
                        if ocr_text:
                            documents.append(Document(
                                page_content=ocr_text,
                                metadata={
                                    "source":    file_path,
                                    "page":      i,
                                    "file_type": "pdf",
                                    "extractor": "ocr",
                                }
                            ))
                            logger.info(
                                f"  Page {i}: full-page OCR extracted "
                                f"{len(ocr_text)} chars"
                            )
                        else:
                            logger.info(f"  Page {i}: OCR yielded nothing — skipping")
                    except Exception as ocr_err:
                        logger.debug(f"  Page {i}: OCR skipped ({ocr_err})")

        if documents:
            logger.info(
                f"✅ pdfplumber extracted {len(documents)} pages "
                f"from '{os.path.basename(file_path)}'"
            )
            return documents

        logger.warning("  pdfplumber returned no content — falling back to PyPDFLoader")

    except Exception as exc:
        logger.warning(f"  pdfplumber failed ({exc}) — falling back to PyPDFLoader")

    # Fallback: PyPDFLoader
    from langchain_community.document_loaders import PyPDFLoader
    docs = PyPDFLoader(file_path).load()
    for d in docs:
        d.metadata["extractor"] = "pypdf_fallback"
    logger.info(
        f"✅ PyPDFLoader (fallback) extracted {len(docs)} pages "
        f"from '{os.path.basename(file_path)}'"
    )
    return docs


# ════════════════════════════════════════════════════════════════════════════
# Other format loaders
# ════════════════════════════════════════════════════════════════════════════

def _docx_image_blobs(file_path: str) -> list:
    """
    Extract all embedded image blobs from a .docx file.

    A .docx is a ZIP archive.  Images live under word/media/*.
    Returns a list of raw bytes (one per image).
    """
    blobs = []
    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            for name in zf.namelist():
                if name.lower().startswith("word/media/"):
                    ext = os.path.splitext(name)[1].lower()
                    if ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp",
                               ".tiff", ".tif", ".webp"):
                        try:
                            blobs.append(zf.read(name))
                        except Exception:
                            pass
    except Exception as exc:
        logger.debug(f"  DOCX image extraction skipped: {exc}")
    return blobs


def _load_docx(file_path: str) -> list:
    """
    Load a Word document.

    1. Extract paragraph + table text.
    2. Extract all embedded images from the docx ZIP.
    3. OCR the images in parallel and append to the same Document.
    """
    try:
        import docx
    except ImportError:
        raise ImportError("python-docx is required. pip install python-docx")

    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".doc":
        raise Exception(
            "Legacy .doc format is not supported. "
            "Please save as .docx and re-upload."
        )
    try:
        doc = docx.Document(file_path)
    except Exception as e:
        raise Exception(f"Could not open Word document: {e}")

    text_parts = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            text_parts.append(text)
    for table in doc.tables:
        for row in table.rows:
            row_texts = [cell.text.strip() for cell in row.cells
                         if cell.text.strip()]
            if row_texts:
                text_parts.append(" | ".join(row_texts))

    # Parallel image OCR
    image_blobs = _docx_image_blobs(file_path)
    if image_blobs:
        ocr_texts = _ocr_images_parallel(image_blobs, label="docx")
        text_parts.extend(ocr_texts)

    full_text = "\n".join(text_parts).strip()
    if not full_text:
        return []
    return [Document(
        page_content=full_text,
        metadata={"source": file_path, "file_type": "docx"},
    )]


def _xlsx_sheet_image_blobs(zf: zipfile.ZipFile, sheet_index: int) -> list:
    """
    Extract embedded image blobs for a specific sheet (0-indexed) from an
    already-open XLSX ZipFile.

    XLSX drawing images live under xl/media/ and are referenced via
    xl/drawings/drawing<N>.xml.  We use a simple heuristic: images referenced
    by drawing<N>.xml belong to sheet index N-1 (the most common layout).
    All images not mapped to a specific sheet are attached to every sheet as a
    fallback so nothing is silently dropped.
    """
    # Collect all media blobs indexed by their archive name
    media: dict = {}
    for name in zf.namelist():
        if name.lower().startswith("xl/media/"):
            ext = os.path.splitext(name)[1].lower()
            if ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp",
                       ".tiff", ".tif", ".webp"):
                try:
                    media[name] = zf.read(name)
                except Exception:
                    pass

    if not media:
        return []

    # Try to find which images belong to this sheet via drawing relationships
    # drawing1.xml → sheet index 0, drawing2.xml → sheet index 1, …
    drawing_name = f"xl/drawings/drawing{sheet_index + 1}.xml"
    blobs = []

    if drawing_name in zf.namelist():
        # Parse the drawing XML to find referenced images
        try:
            import xml.etree.ElementTree as ET
            xml_bytes = zf.read(drawing_name)
            root = ET.fromstring(xml_bytes)
            # Collect all r:embed attributes (relationship IDs)
            ns = {"r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
            embeds = {el.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
                      for el in root.iter()
                      if el.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")}

            # Resolve relationship IDs via the drawing's .rels file
            rels_name = (
                f"xl/drawings/_rels/drawing{sheet_index + 1}.xml.rels"
            )
            if rels_name in zf.namelist():
                rels_xml   = zf.read(rels_name)
                rels_root  = ET.fromstring(rels_xml)
                id_to_target = {
                    rel.get("Id"): rel.get("Target")
                    for rel in rels_root
                }
                for embed_id in embeds:
                    target = id_to_target.get(embed_id, "")
                    # Target is relative to xl/drawings/, e.g. "../media/image1.png"
                    if target.startswith("../"):
                        media_key = "xl/" + target[3:]
                    else:
                        media_key = "xl/drawings/" + target
                    if media_key in media:
                        blobs.append(media[media_key])
        except Exception as exc:
            logger.debug(f"  XLSX drawing parse skipped (sheet {sheet_index}): {exc}")

    # If we found nothing via drawing XML, fall back to all media
    if not blobs:
        blobs = list(media.values())

    return blobs


def _load_xlsx(file_path: str) -> list:
    """
    Load an Excel file — one Document per data row.

    Strategy
    --------
    • The first non-empty row of each sheet is treated as the header row.
    • Every subsequent non-empty data row becomes its own Document:

          "Header1: Value1 | Header2: Value2 | Header3: Value3"

      This preserves the column–value relationship inside each chunk so
      retrieval is accurate without any row bleeding into another.
    • No overlap — every Document is a fully self-contained record.
    • Embedded sheet images are OCR-'d and appended as separate Documents
      at the end of the sheet's row list.

    XLS (legacy) path uses the same row-per-document strategy via xlrd.
    """
    try:
        import openpyxl
    except ImportError:
        raise ImportError("openpyxl is required. pip install openpyxl")

    ext = os.path.splitext(file_path)[1].lower()

    # ── Legacy .xls via xlrd ─────────────────────────────────────────────────
    if ext == ".xls":
        try:
            import xlrd
            workbook  = xlrd.open_workbook(file_path)
            documents = []
            for sheet_name in workbook.sheet_names():
                sheet = workbook.sheet_by_name(sheet_name)
                if sheet.nrows == 0:
                    continue

                # Find the first non-empty row to use as headers
                headers = []
                header_row_idx = 0
                for row_idx in range(sheet.nrows):
                    candidate = [
                        str(sheet.cell_value(row_idx, col)).strip()
                        for col in range(sheet.ncols)
                    ]
                    candidate = [c for c in candidate if c]
                    if candidate:
                        headers = candidate
                        header_row_idx = row_idx
                        break

                if not headers:
                    continue

                # One Document per data row
                for row_idx in range(header_row_idx + 1, sheet.nrows):
                    raw_cells = [
                        str(sheet.cell_value(row_idx, col)).strip()
                        for col in range(sheet.ncols)
                    ]
                    # Skip completely empty rows
                    if not any(raw_cells):
                        continue

                    # Pair each value with its column header
                    pairs = []
                    for col_idx, value in enumerate(raw_cells):
                        header = (
                            headers[col_idx]
                            if col_idx < len(headers)
                            else f"Column{col_idx + 1}"
                        )
                        # Include even empty cells so column positions are clear
                        pairs.append(f"{header}: {value if value else '-'}")

                    row_text = " | ".join(pairs)
                    documents.append(Document(
                        page_content=row_text,
                        metadata={
                            "source":     file_path,
                            "sheet":      sheet_name,
                            "row_number": row_idx,
                            "file_type":  "xls",
                        },
                    ))

            return documents
        except ImportError:
            raise ImportError("xlrd is required. pip install xlrd")

    # ── Modern .xlsx via openpyxl ────────────────────────────────────────────
    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    documents = []

    # Open ZIP once for image extraction across all sheets
    try:
        xlsx_zip = zipfile.ZipFile(file_path, "r")
    except Exception:
        xlsx_zip = None

    for sheet_idx, sheet_name in enumerate(wb.sheetnames):
        ws = wb[sheet_name]

        # Collect all rows as plain string lists (filter None)
        all_rows = []
        for row in ws.iter_rows(values_only=True):
            cells = [str(c).strip() if c is not None else "" for c in row]
            all_rows.append(cells)

        if not all_rows:
            continue

        # Find the first non-empty row → treat as column headers
        headers = []
        header_row_idx = 0
        for idx, row_cells in enumerate(all_rows):
            non_empty = [c for c in row_cells if c]
            if non_empty:
                # Use non-empty values as headers; blank header cells get
                # a fallback name so nothing is silently dropped
                headers = [
                    c if c else f"Column{i + 1}"
                    for i, c in enumerate(row_cells)
                ]
                header_row_idx = idx
                break

        if not headers:
            continue

        # One Document per data row
        for row_idx, row_cells in enumerate(all_rows[header_row_idx + 1:],
                                            start=header_row_idx + 1):
            # Skip completely empty rows
            if not any(c for c in row_cells):
                continue

            # Pair each cell value with its column header
            pairs = []
            for col_idx, value in enumerate(row_cells):
                header = (
                    headers[col_idx]
                    if col_idx < len(headers)
                    else f"Column{col_idx + 1}"
                )
                pairs.append(f"{header}: {value if value else '-'}")

            row_text = " | ".join(pairs)
            documents.append(Document(
                page_content=row_text,
                metadata={
                    "source":     file_path,
                    "sheet":      sheet_name,
                    "row_number": row_idx,
                    "file_type":  "xlsx",
                },
            ))

        # OCR images for this sheet → each OCR result is its own Document
        if xlsx_zip is not None:
            image_blobs = _xlsx_sheet_image_blobs(xlsx_zip, sheet_idx)
            if image_blobs:
                ocr_texts = _ocr_images_parallel(
                    image_blobs, label=f"xlsx sheet '{sheet_name}'"
                )
                for ocr_text in ocr_texts:
                    documents.append(Document(
                        page_content=ocr_text,
                        metadata={
                            "source":    file_path,
                            "sheet":     sheet_name,
                            "file_type": "xlsx",
                            "extractor": "ocr",
                        },
                    ))

    if xlsx_zip is not None:
        xlsx_zip.close()
    wb.close()
    return documents


def _load_txt(file_path: str) -> list:
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            with open(file_path, "r", encoding=encoding) as f:
                content = f.read().strip()
            if content:
                return [Document(
                    page_content=content,
                    metadata={"source": file_path, "file_type": "txt"},
                )]
            return []
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Could not decode text file: {file_path}")


def _load_rtf(file_path: str) -> list:
    try:
        from striprtf.striprtf import rtf_to_text
    except ImportError:
        raise ImportError("striprtf is required. pip install striprtf")

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
    return [Document(
        page_content=content,
        metadata={"source": file_path, "file_type": "rtf"},
    )]


# ════════════════════════════════════════════════════════════════════════════
# MAIN ROUTER
# ════════════════════════════════════════════════════════════════════════════

def load_document(file_path: str) -> list:
    """
    Detect file type by extension and route to the correct loader.
    Returns a list of LangChain Document objects.
    """
    extension = os.path.splitext(file_path)[1].lower()
    logger.info(
        f"Detected file extension: '{extension}' "
        f"for '{os.path.basename(file_path)}'"
    )

    if extension == ".pdf":
        logger.info(f"Loading PDF: {os.path.basename(file_path)}")
        documents = _load_pdf(file_path)

    elif extension == ".csv":
        loader    = CSVLoader(file_path)
        documents = loader.load()

    elif extension in (".ppt", ".pptx"):
        logger.info(f"Loading PowerPoint: {os.path.basename(file_path)}")
        documents = _load_pptx_text(file_path)

    elif extension in (".docx", ".doc"):
        logger.info(f"Loading Word document: {os.path.basename(file_path)}")
        documents = _load_docx(file_path)

    elif extension in (".xlsx", ".xls"):
        logger.info(f"Loading Excel: {os.path.basename(file_path)}")
        documents = _load_xlsx(file_path)

    elif extension == ".txt":
        logger.info(f"Loading plain text: {os.path.basename(file_path)}")
        documents = _load_txt(file_path)

    elif extension == ".rtf":
        logger.info(f"Loading RTF: {os.path.basename(file_path)}")
        documents = _load_rtf(file_path)

    else:
        raise Exception(
            f"Unsupported file type '{extension}'. "
            "Supported: PDF, DOCX, DOC, XLSX, XLS, PPTX, PPT, CSV, TXT, RTF"
        )

    logger.info(f"Loaded {len(documents)} document section(s) from {file_path}")
    return documents


# ════════════════════════════════════════════════════════════════════════════
# PROCESS PIPELINE
# ════════════════════════════════════════════════════════════════════════════

def create_chunks(documents):
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
      2. Chunk + contextual enrichment
      3. Embed → blue/green vector store
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

        if not documents:
            raise Exception("No readable content found.")

        for i, doc in enumerate(documents):
            logger.info(f"  Section {i+1}: {len(doc.page_content)} characters")

        # Step 2 — Chunk + enrich
        # Excel files: each Document is already one complete row — skip the
        # text splitter entirely so rows are never broken across chunks.
        # Just apply contextual enrichment (_enrich) to each row as-is.
        if extension in ("xlsx", "xls"):
            logger.info("Step 2: Excel detected — skipping splitter, enriching rows as whole units...")
            chunks = [_enrich(doc) for doc in documents]
            logger.info(f"✅ Created {len(chunks)} enriched row chunks (no splitting)")
        else:
            logger.info(
                f"Step 2: Chunking + contextual enrichment "
                f"(size={Config.CHUNK_SIZE}, overlap={Config.CHUNK_OVERLAP})..."
            )
            chunks = _traced_chunk(documents, filename=filename)
            logger.info(f"✅ Created {len(chunks)} enriched chunks")

        if not chunks:
            raise Exception(
                f"No text could be extracted from '{filename}'. "
                "The file may be a scanned image-only PDF without readable text, "
                "or the content is not supported. "
                "Please try a text-based PDF or a different file."
            )

        for i, chunk in enumerate(chunks[:3]):
            logger.info(f"  Chunk {i+1} preview: {chunk.page_content[:120]!r}")

        # Step 3 — Embed + save via blue/green pipeline
        logger.info("Step 3: Embedding into vector store (blue/green pipeline)...")
        embedding_manager = EmbeddingManager()
        result = embedding_manager.create_vector_store(chunks, source_path=file_path)

        if result is None:
            return f"'{filename}' is already in the knowledge base. No duplicate added."

        logger.info("✅ Vector store updated successfully")
        logger.info("📄 DOCUMENT PROCESSING COMPLETED")
        logger.info("=" * 80)

        return f"Document processed successfully. {len(chunks)} chunks created."

    except Exception as e:
        logger.error(f"❌ Error processing document: {str(e)}")
        logger.error("=" * 80)
        raise


@_traceable(name="load_document_file", run_type="tool", tags=["ingestion", "load"])
def _traced_load(file_path: str, filename: str = "", file_type: str = "") -> list:
    return load_document(file_path)


@_traceable(name="chunk_documents", run_type="tool", tags=["ingestion", "chunking"])
def _traced_chunk(documents: list, filename: str = "") -> list:
    return chunk_documents(documents)


# ════════════════════════════════════════════════════════════════════════════
# URL INGESTION PIPELINE
# ════════════════════════════════════════════════════════════════════════════

def load_url(url: str) -> str:
    """
    Smart ingestion pipeline for any URL.

    The URL is first classified by utils.url_resolver:
      • GOOGLE_DRIVE  → download via gdown     → process_document()
      • ONEDRIVE      → download via requests   → process_document()
      • DIRECT_FILE   → download via requests   → process_document()
      • WEB_PAGE      → Playwright scrape        → chunk + embed directly

    In all file-download cases the temporary file is cleaned up after
    ingestion (success or failure) so uploads/ does not accumulate
    scratch files.  The original URL is used as the canonical source
    identifier in the vector registry so the knowledge-base table shows
    the URL, not the temp filename.
    """
    from utils.url_resolver import classify, UrlType
    from utils.scraper import scrape_url
    from utils.embeddings import (
        delete_document_chunks,
        _load_registry,
        _save_registry,
    )

    url = url.strip()

    logger.info("=" * 80)
    logger.info("🌐  URL INGESTION STARTED")
    logger.info(f"  URL       : {url}")
    logger.info(f"  Timestamp : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # ── Classify ──────────────────────────────────────────────────────────
    # classify() is pure (no network) and raises ValueError for bad inputs
    # such as folder links.
    classification = classify(url)
    logger.info(f"  🔍 Classified as: {classification}")

    try:
        # ── De-duplicate: remove previous ingestion of the same URL ──────
        registry = [r for r in _load_registry() if r is not None]
        existing = [r for r in registry if r.get("filename") == url]
        if existing:
            logger.info("  🔄  Already ingested — removing old data for re-ingestion...")
            deleted = delete_document_chunks(url)
            logger.info(f"  🗑️  Deleted {deleted} old vector(s)")
            registry = [r for r in registry if r.get("filename") != url]
            _save_registry(registry)

        # ── Route based on classification ─────────────────────────────────
        if classification.url_type == UrlType.WEB_PAGE:
            return _ingest_web_page(url, scrape_url, chunk_documents, EmbeddingManager)

        else:
            # All file types share the same download → process flow
            return _ingest_file_from_url(url, classification)

    except Exception as e:
        logger.error(f"  ❌ Error ingesting URL: {str(e)}")
        logger.error("=" * 80)
        raise


# ── Private routing helpers ───────────────────────────────────────────────

def _ingest_web_page(url, scrape_url_fn, chunk_fn, EmbeddingManagerCls) -> str:
    """Scrape a generic web page and embed its sections."""
    logger.info("  Step 1: Scraping web page with Playwright...")
    documents = scrape_url_fn(url)
    logger.info(f"  ✅ Scraped {len(documents)} section(s)")

    if not documents:
        raise Exception("No content extracted from URL.")

    for doc in documents:
        if doc.metadata is None:
            doc.metadata = {"source": url, "source_type": "url"}

    logger.info("  Step 2: Chunking + contextual enrichment...")
    chunks = chunk_fn(documents)
    logger.info(f"  ✅ Created {len(chunks)} enriched chunks")

    if not chunks:
        raise Exception("No text content could be extracted from the URL.")

    logger.info("  Step 3: Embedding into vector store...")
    embedding_manager = EmbeddingManagerCls()
    result = embedding_manager.create_vector_store(chunks, source_path=url)

    if result is None:
        return f"URL already in knowledge base: {url}"

    logger.info("  ✅ Vectors stored")
    logger.info("🌐  URL INGESTION COMPLETE")
    logger.info("=" * 80)
    return f"Web page scraped and ingested successfully. {len(chunks)} chunks created."


def _ingest_file_from_url(url: str, classification) -> str:
    """
    Download a file (Google Drive / OneDrive / direct) and run it through
    the standard process_document() pipeline.

    The downloaded temp file is always removed after ingestion finishes,
    regardless of success or failure.  The URL is patched back as the
    canonical source so the KB table shows the original link.
    """
    from utils.url_resolver import UrlType
    from utils.downloader import (
        download_google_drive,
        download_onedrive,
        download_direct_file,
    )
    from utils.embeddings import _load_registry, _save_registry

    ext_hint   = classification.extension_hint
    url_type   = classification.url_type
    local_path = None

    try:
        # ── Step 1: Download ──────────────────────────────────────────────
        logger.info(f"  Step 1: Downloading {classification.label}...")

        if url_type == UrlType.GOOGLE_DRIVE:
            local_path = download_google_drive(url, extension_hint=ext_hint)
        elif url_type == UrlType.ONEDRIVE:
            local_path = download_onedrive(url, extension_hint=ext_hint)
        elif url_type == UrlType.DIRECT_FILE:
            local_path = download_direct_file(url, extension_hint=ext_hint)
        else:
            raise RuntimeError(f"Unexpected URL type: {url_type}")

        logger.info(f"  ✅ Downloaded to: {local_path}")

        # ── Step 2 + 3: Load → Chunk → Embed via process_document ────────
        logger.info(f"  Step 2/3: Processing downloaded file: {os.path.basename(local_path)}")
        process_document(local_path)

        # ── Step 4: Re-key the registry entry from temp path → original URL ──
        # process_document() registers the local file path as the source.
        # We rewrite it to the original URL so the admin KB table shows
        # the link the admin submitted, not an internal temp path.
        logger.info(f"  Step 4: Re-keying registry source to original URL...")
        _rekey_registry_source(local_path, url)

        logger.info("🌐  URL INGESTION COMPLETE")
        logger.info("=" * 80)

        return (
            f"{classification.label} downloaded and ingested successfully. "
            f"Source recorded as: {url}"
        )

    finally:
        # Always clean up the temp file — whether ingestion succeeded or failed
        if local_path and os.path.exists(local_path):
            try:
                os.remove(local_path)
                logger.info(f"  🧹 Cleaned up temp file: {local_path}")
            except OSError as rm_err:
                logger.warning(f"  ⚠️  Could not remove temp file {local_path}: {rm_err}")


def _rekey_registry_source(old_source: str, new_source: str) -> None:
    """
    Update the vector registry so any entry whose filename / source equals
    *old_source* is rewritten to *new_source*.

    This allows process_document() to work transparently with a local path
    while the KB table displays the original URL.
    """
    from utils.embeddings import _load_registry, _save_registry

    try:
        registry = [r for r in _load_registry() if r is not None]
        updated  = False
        for entry in registry:
            if entry.get("filename") == old_source:
                entry["filename"] = new_source
                updated = True
            # Some registries also store a "source" key
            if entry.get("source") == old_source:
                entry["source"] = new_source
                updated = True
        if updated:
            _save_registry(registry)
            logger.info(f"  ✅ Registry re-keyed: {os.path.basename(old_source)} → {new_source}")
        else:
            logger.warning(
                f"  ⚠️  Re-key: no registry entry found for '{old_source}'. "
                "KB table may show local path instead of URL."
            )
    except Exception as e:
        logger.warning(f"  ⚠️  Registry re-key failed (non-fatal): {e}")
