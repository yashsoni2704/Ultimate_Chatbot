"""
utils/downloader.py
~~~~~~~~~~~~~~~~~~~
File downloaders for every URL type that the url_resolver can identify.

Public API
----------
download_google_drive(url)  → local path   (uses gdown)
download_onedrive(url)      → local path   (follow redirect → stream)
download_direct_file(url)   → local path   (plain requests stream)

All three functions
  • save the file into uploads/
  • preserve the real filename / extension where possible
  • raise RuntimeError with a clear message on failure
  • never leave a partial file on disk (cleaned up on exception)

Industry-grade details
-----------------------
• Streaming downloads — no full file buffered in RAM
• Content-Disposition header parsed for real filename
• Redirect chain followed for OneDrive short-links (1drv.ms, etc.)
• MIME-type → extension fallback when no filename is available
• Duplicate-safe filenames (uuid4 stem when name is not deterministic)
• Configurable timeout and chunk size via module-level constants
• All helpers are private (_prefixed); only the three public functions
  are part of the stable interface
"""

from __future__ import annotations

import mimetypes
import os
import re
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

# ── optional gdown import (Google Drive only) ────────────────────────────
try:
    import gdown
    _GDOWN_AVAILABLE = True
except ImportError:
    _GDOWN_AVAILABLE = False

from utils.logger import get_logger

logger = get_logger(__name__)

# ── tunables ─────────────────────────────────────────────────────────────
_UPLOAD_DIR    = "uploads"
_CHUNK_BYTES   = 1024 * 1024 * 4   # 4 MB streaming chunks
_REQUEST_TIMEOUT = 60               # seconds; used for connect + read

# Browser-like headers to avoid 403s on protected CDN links
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "application/pdf,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Known document extensions (must stay in sync with Config.ALLOWED_EXTENSIONS)
_DOCUMENT_EXTENSIONS: frozenset[str] = frozenset({
    "pdf", "docx", "doc", "xlsx", "xls",
    "pptx", "ppt", "csv", "txt", "rtf",
})

# MIME type → extension map for fallback resolution
_MIME_TO_EXT: dict[str, str] = {
    "application/pdf":                                               "pdf",
    "application/msword":                                            "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.ms-excel":                                      "xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-powerpoint":                                 "ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "text/csv":                                                      "csv",
    "text/plain":                                                    "txt",
    "application/rtf":                                               "rtf",
    "text/rtf":                                                      "rtf",
}


# ════════════════════════════════════════════════════════════════════════════
# Private helpers
# ════════════════════════════════════════════════════════════════════════════

def _ensure_upload_dir() -> Path:
    path = Path(_UPLOAD_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_filename(name: str) -> str:
    """
    Sanitise *name* so it is safe to use as a filename on Windows / Linux.
    Strips path traversal characters and collapses whitespace.
    """
    # Remove any directory components
    name = Path(name).name
    # Replace path-unsafe chars with underscore
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    name = name.strip(". ")
    return name or f"downloaded_{uuid.uuid4().hex[:8]}"


def _extension_from_content_disposition(cd: str) -> str:
    """
    Parse a Content-Disposition header value and return the file extension
    (lower-case, no dot) inferred from the filename, or '' if none.

    Handles both:
        attachment; filename="report.pdf"
        attachment; filename*=UTF-8''Annual%20Report.xlsx
    """
    if not cd:
        return ""

    # filename*=UTF-8''<encoded-name>  (RFC 5987)
    m = re.search(r"filename\*\s*=\s*[^']*''(.+)", cd, re.IGNORECASE)
    if m:
        raw = unquote(m.group(1).strip().strip('"'))
        ext = Path(raw).suffix.lstrip(".").lower()
        if ext in _DOCUMENT_EXTENSIONS:
            return ext

    # filename="<name>"
    m = re.search(r'filename\s*=\s*"?([^";]+)"?', cd, re.IGNORECASE)
    if m:
        raw = m.group(1).strip().strip('"')
        ext = Path(raw).suffix.lstrip(".").lower()
        if ext in _DOCUMENT_EXTENSIONS:
            return ext

    return ""


def _filename_from_content_disposition(cd: str) -> str:
    """
    Return the full filename from a Content-Disposition header, or ''.
    """
    if not cd:
        return ""

    # filename*=UTF-8''<encoded-name>
    m = re.search(r"filename\*\s*=\s*[^']*''(.+)", cd, re.IGNORECASE)
    if m:
        return _safe_filename(unquote(m.group(1).strip().strip('"')))

    # filename="<name>"
    m = re.search(r'filename\s*=\s*"?([^";]+)"?', cd, re.IGNORECASE)
    if m:
        return _safe_filename(m.group(1).strip().strip('"'))

    return ""


def _extension_from_mime(content_type: str) -> str:
    """Map a MIME type to a document extension, or '' if unknown."""
    mime = content_type.split(";")[0].strip().lower()
    # Check explicit map first
    if mime in _MIME_TO_EXT:
        return _MIME_TO_EXT[mime]
    # Fall back to mimetypes stdlib
    ext = mimetypes.guess_extension(mime) or ""
    ext = ext.lstrip(".").lower()
    return ext if ext in _DOCUMENT_EXTENSIONS else ""


def _filename_from_url_path(url: str) -> str:
    """Extract a best-guess filename from the URL path component."""
    path = urlparse(url).path.rstrip("/")
    name = Path(unquote(path)).name
    return _safe_filename(name) if name else ""


def _resolve_filename(
    url: str,
    content_disposition: str,
    content_type: str,
    extension_hint: str = "",
) -> str:
    """
    Determine the best filename to save a download as, in priority order:

    1. Content-Disposition header  (most reliable — server-provided)
    2. URL path basename           (second most reliable)
    3. extension_hint from resolver + uuid stem
    4. MIME type mapping           + uuid stem
    5. Last resort: downloaded_<uuid>.bin
    """
    # 1. Content-Disposition
    cd_name = _filename_from_content_disposition(content_disposition)
    if cd_name and Path(cd_name).suffix.lstrip(".").lower() in _DOCUMENT_EXTENSIONS:
        return cd_name

    # 2. URL path
    url_name = _filename_from_url_path(url)
    if url_name and Path(url_name).suffix.lstrip(".").lower() in _DOCUMENT_EXTENSIONS:
        return url_name

    # 3. Extension hint from url_resolver (e.g. inferred from GDrive app type)
    if extension_hint and extension_hint in _DOCUMENT_EXTENSIONS:
        stem = cd_name or url_name or f"downloaded_{uuid.uuid4().hex[:8]}"
        stem_no_ext = Path(stem).stem
        return f"{stem_no_ext}.{extension_hint}"

    # 4. MIME type
    mime_ext = _extension_from_mime(content_type)
    if mime_ext:
        stem = cd_name or url_name or f"downloaded_{uuid.uuid4().hex[:8]}"
        stem_no_ext = Path(stem).stem
        return f"{stem_no_ext}.{mime_ext}"

    # 5. Last resort
    return f"downloaded_{uuid.uuid4().hex[:8]}.bin"


def _unique_path(directory: Path, filename: str) -> Path:
    """
    Return a Path that does not already exist in *directory*.
    Appends _(1), _(2), … before the extension if needed.
    """
    target = directory / filename
    if not target.exists():
        return target

    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 1
    while True:
        candidate = directory / f"{stem}_({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _stream_to_file(response: requests.Response, dest: Path) -> None:
    """Write a streaming response to *dest*, cleaning up on error."""
    try:
        with open(dest, "wb") as fh:
            for chunk in response.iter_content(chunk_size=_CHUNK_BYTES):
                if chunk:
                    fh.write(chunk)
    except Exception:
        # Remove partial file so a retry starts fresh
        if dest.exists():
            dest.unlink(missing_ok=True)
        raise


# ════════════════════════════════════════════════════════════════════════════
# Public downloaders
# ════════════════════════════════════════════════════════════════════════════

def _extract_gdrive_id(url: str) -> str | None:
    """
    Extract the Google Drive file ID from any recognised URL variant.

    Handles:
      • https://drive.google.com/file/d/<ID>/view
      • https://drive.google.com/file/d/<ID>/edit
      • https://drive.google.com/open?id=<ID>
      • https://drive.google.com/uc?id=<ID>&export=download
      • https://drive.google.com/uc?export=download&id=<ID>
    """
    # /file/d/<ID>/
    m = re.search(r"/file/d/([a-zA-Z0-9_-]+)", url)
    if m:
        return m.group(1)
    # ?id=<ID>
    m = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", url)
    if m:
        return m.group(1)
    return None


def download_google_drive(url: str, extension_hint: str = "") -> str:
    """
    Download a single file from Google Drive and return its local path.

    Uses *gdown* which handles:
      • OAuth-required large-file confirmations
      • Virus-scan bypass tokens
      • Both /file/d/<ID>/view and ?id=<ID> URL shapes
      • Preserving the original filename from Drive metadata

    Parameters
    ----------
    url            : str  — any recognised Google Drive file URL
    extension_hint : str  — optional extension hint from url_resolver
                            (used only if gdown cannot determine filename)

    Returns
    -------
    str — absolute path to the downloaded file inside uploads/

    Raises
    ------
    ImportError   if gdown is not installed
    RuntimeError  if the download fails
    """
    if not _GDOWN_AVAILABLE:
        raise ImportError(
            "gdown is required for Google Drive downloads. "
            "Install it with: pip install gdown"
        )

    upload_dir = _ensure_upload_dir()

    logger.info(f"  [GDrive] Downloading: {url}")

    # gdown 6.x removed the `fuzzy` parameter — extract the file ID manually
    # and pass it via the `id` keyword so all URL variants are handled.
    file_id = _extract_gdrive_id(url)
    if file_id:
        logger.info(f"  [GDrive] Extracted file ID: {file_id}")
        output = gdown.download(
            id=file_id,
            output=str(upload_dir) + "/",
            quiet=False,
        )
    else:
        # URL doesn't match known patterns — pass it directly and hope for the best
        output = gdown.download(
            url,
            output=str(upload_dir) + "/",
            quiet=False,
        )

    if not output:
        raise RuntimeError(
            f"Google Drive download failed. "
            f"The file may be private or the link may be invalid: {url}"
        )

    local_path = Path(output)

    # If gdown saved without extension (can happen for some shared files),
    # rename using the hint from url_resolver
    if not local_path.suffix and extension_hint:
        new_path = local_path.with_suffix(f".{extension_hint}")
        local_path.rename(new_path)
        local_path = new_path
        logger.info(f"  [GDrive] Renamed to add extension: {local_path.name}")

    logger.info(f"  [GDrive] Saved to: {local_path}")
    return str(local_path)


def download_onedrive(url: str, extension_hint: str = "") -> str:
    """
    Download a file shared via OneDrive (personal) or SharePoint.

    OneDrive share links typically redirect through several hops before
    reaching a direct download URL.  This function:

      1. Converts known short-link forms (1drv.ms, onedrive.live.com/redir)
         to a direct ?download=1 URL.
      2. Issues a streaming GET with redirect-following enabled.
      3. Reads Content-Disposition to recover the real filename.

    Parameters
    ----------
    url            : str — OneDrive share or embed link
    extension_hint : str — optional hint from url_resolver

    Returns
    -------
    str — absolute path to the downloaded file inside uploads/

    Raises
    ------
    RuntimeError  on HTTP errors or if no downloadable content is found
    """
    upload_dir = _ensure_upload_dir()
    download_url = _onedrive_to_download_url(url)

    logger.info(f"  [OneDrive] Resolved download URL: {download_url}")

    session = requests.Session()
    session.headers.update(_HEADERS)

    try:
        resp = session.get(
            download_url,
            stream=True,
            timeout=_REQUEST_TIMEOUT,
            allow_redirects=True,
        )
    except requests.exceptions.SSLError as e:
        raise RuntimeError(f"SSL error downloading OneDrive file: {e}") from e
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(f"Connection error downloading OneDrive file: {e}") from e
    except requests.exceptions.Timeout:
        raise RuntimeError(
            f"OneDrive download timed out after {_REQUEST_TIMEOUT}s. "
            "The server may be slow or the link expired."
        )

    if resp.status_code == 401:
        raise RuntimeError(
            "OneDrive returned 401 Unauthorized. "
            "The file is private or the share link has expired."
        )
    if resp.status_code == 403:
        raise RuntimeError(
            "OneDrive returned 403 Forbidden. "
            "You don't have permission to access this file."
        )
    if resp.status_code == 404:
        raise RuntimeError(
            "OneDrive returned 404 Not Found. "
            "The share link may have been deleted or expired."
        )
    if not resp.ok:
        raise RuntimeError(
            f"OneDrive download failed with HTTP {resp.status_code}."
        )

    content_disposition = resp.headers.get("Content-Disposition", "")
    content_type        = resp.headers.get("Content-Type", "")

    filename = _resolve_filename(
        url              = resp.url,       # final URL after redirects
        content_disposition = content_disposition,
        content_type     = content_type,
        extension_hint   = extension_hint,
    )

    dest = _unique_path(upload_dir, filename)
    logger.info(f"  [OneDrive] Saving as: {dest.name}")

    _stream_to_file(resp, dest)

    logger.info(f"  [OneDrive] Saved to: {dest}")
    return str(dest)


def download_direct_file(url: str, extension_hint: str = "") -> str:
    """
    Download any publicly accessible document file via a direct HTTP(S) URL.

    This is the simplest downloader — no special auth or redirect logic
    beyond what requests already handles.  Used for URLs like:
        https://example.com/docs/annual-report.pdf
        https://cdn.company.com/specs/datasheet.xlsx

    Parameters
    ----------
    url            : str — direct download URL
    extension_hint : str — optional hint from url_resolver

    Returns
    -------
    str — absolute path to the downloaded file inside uploads/

    Raises
    ------
    RuntimeError  on HTTP errors or download failures
    """
    upload_dir = _ensure_upload_dir()

    logger.info(f"  [Direct] Downloading: {url}")

    session = requests.Session()
    session.headers.update(_HEADERS)

    try:
        resp = session.get(
            url,
            stream=True,
            timeout=_REQUEST_TIMEOUT,
            allow_redirects=True,
        )
    except requests.exceptions.SSLError as e:
        raise RuntimeError(f"SSL error downloading file: {e}") from e
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(f"Connection error downloading file: {e}") from e
    except requests.exceptions.Timeout:
        raise RuntimeError(
            f"Download timed out after {_REQUEST_TIMEOUT}s: {url}"
        )

    if resp.status_code == 401:
        raise RuntimeError(
            "HTTP 401 Unauthorized. The file requires authentication."
        )
    if resp.status_code == 403:
        raise RuntimeError(
            "HTTP 403 Forbidden. Access to this file is restricted."
        )
    if resp.status_code == 404:
        raise RuntimeError(
            f"HTTP 404 Not Found. No file exists at: {url}"
        )
    if not resp.ok:
        raise RuntimeError(
            f"HTTP {resp.status_code} error downloading: {url}"
        )

    content_disposition = resp.headers.get("Content-Disposition", "")
    content_type        = resp.headers.get("Content-Type", "")

    filename = _resolve_filename(
        url                 = resp.url,
        content_disposition = content_disposition,
        content_type        = content_type,
        extension_hint      = extension_hint,
    )

    dest = _unique_path(upload_dir, filename)
    logger.info(f"  [Direct] Saving as: {dest.name}")

    _stream_to_file(resp, dest)

    logger.info(f"  [Direct] Saved to: {dest}")
    return str(dest)


# ════════════════════════════════════════════════════════════════════════════
# OneDrive URL normalisation helper
# ════════════════════════════════════════════════════════════════════════════

def _onedrive_to_download_url(url: str) -> str:
    """
    Convert any OneDrive share / embed URL variant to a direct download URL.

    Handles
    -------
    • https://1drv.ms/<short>              → follow redirect, inject ?download=1
    • https://onedrive.live.com/redir?...  → swap redir→download
    • https://onedrive.live.com/download?  → already good
    • https://<tenant>.sharepoint.com/:x:/... → append &download=1
    • https://<tenant>.sharepoint.com/sites/.../<file.xlsx> → append ?web=0
    """
    parsed = urlparse(url)
    host   = parsed.netloc.lower()

    # ── Short link: follow the redirect first ─────────────────────────────
    if host == "1drv.ms" or "/1drv.ms/" in url:
        try:
            head = requests.head(
                url,
                allow_redirects=True,
                timeout=15,
                headers=_HEADERS,
            )
            url    = head.url          # use the final resolved URL
            parsed = urlparse(url)
            host   = parsed.netloc.lower()
        except Exception:
            pass   # fall through with original URL; likely still works

    # ── onedrive.live.com/redir → swap to /download ───────────────────────
    if "onedrive.live.com" in host:
        url = url.replace("/redir?", "/download?").replace("/redir?", "/download?")
        # Ensure ?download=1 or similar is present
        if "download" not in parsed.path.lower():
            sep = "&" if "?" in url else "?"
            url = url + sep + "download=1"
        return url

    # ── SharePoint /:x:/ or /:w:/ share links ────────────────────────────
    # These use the format /sites/<name>/:x:/g/personal/...
    # Appending &download=1 forces the browser to download rather than open
    if "sharepoint.com" in host:
        if "/:" in url:
            sep = "&" if "?" in url else "?"
            return url + sep + "download=1"
        # Already a direct file URL path?  Append ?web=0 to force download
        sep = "&" if "?" in url else "?"
        return url + sep + "web=0"

    # ── Fallback — return unchanged (requests will follow any redirects) ──
    return url
