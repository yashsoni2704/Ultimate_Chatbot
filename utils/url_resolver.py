"""
utils/url_resolver.py
~~~~~~~~~~~~~~~~~~~~~
Classifies an incoming URL and decides how to ingest it.

Routing decisions
-----------------
GOOGLE_DRIVE   → Google Drive file link  (gdown download → load_document)
ONEDRIVE       → OneDrive / SharePoint share link (requests download → load_document)
DIRECT_FILE    → Any URL whose path ends with a known document extension
                 (requests streaming download → load_document)
WEB_PAGE       → Everything else          (Playwright scraper → chunk)

Design goals
------------
• Zero network calls for classification — purely URL-pattern based so the
  router is fast and never blocks on a bad link before telling the user.
• A single public function: classify(url) → UrlClassification
• A separate public function: extract_gdrive_file_id(url) so the downloader
  can use it without re-parsing.
• Robust against the many Google Drive / OneDrive link variants found in the
  wild (shared links, export links, webview links, short links, etc.).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto
from urllib.parse import parse_qs, urlparse


# ════════════════════════════════════════════════════════════════════════════
# Public enums / dataclasses
# ════════════════════════════════════════════════════════════════════════════

class UrlType(Enum):
    GOOGLE_DRIVE = auto()   # Google Drive file (single file, not a folder)
    ONEDRIVE     = auto()   # OneDrive personal / SharePoint
    DIRECT_FILE  = auto()   # Direct link to a document file (.pdf, .xlsx, …)
    WEB_PAGE     = auto()   # Generic web page → Playwright scrape


@dataclass
class UrlClassification:
    """Result returned by classify()."""

    url_type: UrlType

    # Human-readable label for logging / UI messages
    label: str

    # Detected file extension hint (lower-case, no dot).
    # May be empty for GOOGLE_DRIVE when the extension can only be
    # determined after download (gdown reads the metadata header).
    extension_hint: str = ""

    # Extra metadata preserved for the downloader
    extra: dict = field(default_factory=dict)

    @property
    def is_file(self) -> bool:
        """True when the URL points to a downloadable file (not a web page)."""
        return self.url_type in (
            UrlType.GOOGLE_DRIVE,
            UrlType.ONEDRIVE,
            UrlType.DIRECT_FILE,
        )

    def __str__(self) -> str:          # handy for log messages
        hint = f" [{self.extension_hint.upper()}]" if self.extension_hint else ""
        return f"{self.label}{hint}"


# ════════════════════════════════════════════════════════════════════════════
# Known document extensions
# ════════════════════════════════════════════════════════════════════════════

# Must stay in sync with Config.ALLOWED_EXTENSIONS
_DOCUMENT_EXTENSIONS: frozenset[str] = frozenset({
    "pdf",
    "docx", "doc",
    "xlsx", "xls",
    "pptx", "ppt",
    "csv",
    "txt",
    "rtf",
})


# ════════════════════════════════════════════════════════════════════════════
# Google Drive patterns
# ════════════════════════════════════════════════════════════════════════════

# Matches all of:
#   https://drive.google.com/file/d/<ID>/view
#   https://drive.google.com/file/d/<ID>/edit
#   https://drive.google.com/open?id=<ID>
#   https://drive.google.com/uc?id=<ID>&export=download
#   https://docs.google.com/document/d/<ID>/export?format=docx
#   https://docs.google.com/spreadsheets/d/<ID>/export?format=xlsx
#   https://docs.google.com/presentation/d/<ID>/export/pptx
_GDRIVE_HOSTS = frozenset({
    "drive.google.com",
    "docs.google.com",
    "sheets.google.com",
    "slides.google.com",
})

# Regex to pull the file ID out of a /d/<ID>/ path segment
_GDRIVE_ID_FROM_PATH = re.compile(r"/d/([a-zA-Z0-9_-]{20,})")

# Google Docs/Sheets/Slides export → we can infer the extension
_GDRIVE_EXPORT_FORMAT: dict[str, str] = {
    # URL path fragment : extension
    "/document/d/":      "docx",
    "/spreadsheets/d/":  "xlsx",
    "/presentation/d/":  "pptx",
}

# Folder URL pattern — we must reject these clearly
_GDRIVE_FOLDER_PATH = re.compile(r"/folders/")


# ════════════════════════════════════════════════════════════════════════════
# OneDrive / SharePoint patterns
# ════════════════════════════════════════════════════════════════════════════

_ONEDRIVE_HOSTS = frozenset({
    "onedrive.live.com",
    "1drv.ms",
    "sharepoint.com",                   # wildcard matched below
})

_SHAREPOINT_HOST_RE = re.compile(
    r"^[a-zA-Z0-9-]+\.sharepoint\.com$"
)

# OneDrive personal direct-download pattern
# e.g. https://onedrive.live.com/download?resid=...&authkey=...
_ONEDRIVE_DIRECT_DOWNLOAD_RE = re.compile(
    r"onedrive\.live\.com/download"
)


# ════════════════════════════════════════════════════════════════════════════
# Internal helpers
# ════════════════════════════════════════════════════════════════════════════

def _get_path_extension(path: str) -> str:
    """
    Return the lowercase extension (without dot) of a URL path, or ''.

    Examples
    --------
    '/reports/Q1.pdf'       → 'pdf'
    '/file?name=data.xlsx'  → ''   (query params ignored here)
    '/page/'                → ''
    """
    # Strip trailing slashes / query fragments
    clean = path.rstrip("/").split("?")[0].split("#")[0]
    dot_idx = clean.rfind(".")
    if dot_idx == -1:
        return ""
    ext = clean[dot_idx + 1:].lower()
    # Guard against very long or garbage "extensions"
    return ext if len(ext) <= 6 and ext.isalnum() else ""


def _is_google_drive(parsed) -> bool:
    return parsed.netloc.lower() in _GDRIVE_HOSTS


def _is_onedrive(parsed) -> bool:
    host = parsed.netloc.lower()
    if host in _ONEDRIVE_HOSTS:
        return True
    if _SHAREPOINT_HOST_RE.match(host):
        return True
    return False


def _gdrive_extension_hint(parsed) -> str:
    """Infer extension from Google Docs/Sheets/Slides export URLs."""
    path = parsed.path.lower()

    # Explicit ?format= or /export/<ext> query / path
    qs = parse_qs(parsed.query)
    fmt = qs.get("format", [""])[0].lower()
    if fmt in _DOCUMENT_EXTENSIONS:
        return fmt

    # /export/pptx  /export/pdf  etc.
    export_match = re.search(r"/export[/=]([a-z]{2,6})", path)
    if export_match:
        ext = export_match.group(1)
        if ext in _DOCUMENT_EXTENSIONS:
            return ext

    # Infer from app type
    for fragment, ext in _GDRIVE_EXPORT_FORMAT.items():
        if fragment in path:
            return ext

    # File path extension (rare but possible for /uc?export=download links)
    path_ext = _get_path_extension(parsed.path)
    if path_ext in _DOCUMENT_EXTENSIONS:
        return path_ext

    return ""   # unknown — gdown will resolve it


def _onedrive_extension_hint(parsed) -> str:
    """Best-effort extension from OneDrive URL path."""
    # SharePoint / OneDrive often embeds filename in path
    path_ext = _get_path_extension(parsed.path)
    if path_ext in _DOCUMENT_EXTENSIONS:
        return path_ext

    # Check query string for file name hints
    qs = parse_qs(parsed.query)
    for key in ("file", "name", "FileName", "sourcedoc"):
        val = qs.get(key, [""])[0]
        if val:
            ext = _get_path_extension(val)
            if ext in _DOCUMENT_EXTENSIONS:
                return ext

    return ""


# ════════════════════════════════════════════════════════════════════════════
# Public API
# ════════════════════════════════════════════════════════════════════════════

def extract_gdrive_file_id(url: str) -> str | None:
    """
    Extract the Google Drive file ID from any recognised Drive URL variant.

    Returns None if no ID can be found (e.g. folder links, malformed URLs).
    """
    parsed = urlparse(url)
    if not _is_google_drive(parsed):
        return None

    # /d/<ID>/ pattern (most common)
    m = _GDRIVE_ID_FROM_PATH.search(parsed.path)
    if m:
        return m.group(1)

    # ?id=<ID> query param
    qs = parse_qs(parsed.query)
    fid = qs.get("id", [""])[0]
    if fid and len(fid) >= 20:
        return fid

    return None


def classify(url: str) -> UrlClassification:
    """
    Classify *url* and return a :class:`UrlClassification`.

    This function is **pure** — it makes no network calls.  All decisions
    are based exclusively on URL structure and known hostname patterns.

    Parameters
    ----------
    url : str
        A fully-qualified URL starting with http:// or https://

    Returns
    -------
    UrlClassification

    Raises
    ------
    ValueError
        If the URL does not start with http:// or https://.
    """
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"Invalid URL (must start with http:// or https://): {url!r}")

    parsed = urlparse(url)

    # ── 1. Google Drive ───────────────────────────────────────────────────
    if _is_google_drive(parsed):
        # Reject folder links up-front with a clear message
        if _GDRIVE_FOLDER_PATH.search(parsed.path):
            raise ValueError(
                "Google Drive folder links are not supported. "
                "Please share a single file and paste its link."
            )

        ext_hint = _gdrive_extension_hint(parsed)
        file_id  = extract_gdrive_file_id(url)

        return UrlClassification(
            url_type       = UrlType.GOOGLE_DRIVE,
            label          = "Google Drive file",
            extension_hint = ext_hint,
            extra          = {"file_id": file_id},
        )

    # ── 2. OneDrive / SharePoint ──────────────────────────────────────────
    if _is_onedrive(parsed):
        ext_hint = _onedrive_extension_hint(parsed)

        return UrlClassification(
            url_type       = UrlType.ONEDRIVE,
            label          = "OneDrive / SharePoint file",
            extension_hint = ext_hint,
        )

    # ── 3. Direct file URL (path ends with a known extension) ────────────
    path_ext = _get_path_extension(parsed.path)
    if path_ext in _DOCUMENT_EXTENSIONS:
        return UrlClassification(
            url_type       = UrlType.DIRECT_FILE,
            label          = "Direct file URL",
            extension_hint = path_ext,
        )

    # ── 4. Fallback — generic web page ───────────────────────────────────
    return UrlClassification(
        url_type = UrlType.WEB_PAGE,
        label    = "Web page",
    )
