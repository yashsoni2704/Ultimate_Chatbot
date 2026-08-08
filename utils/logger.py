import logging
import logging.handlers
import os
import sys

# ── UTF-8 stdout (Windows fix) ────────────────────────────────────────────
if sys.platform == "win32":
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── Log directory ─────────────────────────────────────────────────────────
LOG_DIR  = "logs"
LOG_FILE = os.path.join(LOG_DIR, "app.log")
os.makedirs(LOG_DIR, exist_ok=True)

# ── Formatter ─────────────────────────────────────────────────────────────
_fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")

# ── Rotating file handler — 5 MB per file, keep 10 files ─────────────────
# This replaces the old timestamped FileHandler that created a new file on
# every server start (1194 files found in production).
_file_handler = logging.handlers.RotatingFileHandler(
    LOG_FILE,
    maxBytes    = 5 * 1024 * 1024,   # 5 MB
    backupCount = 10,
    encoding    = "utf-8",
    delay       = False,
)
_file_handler.setFormatter(_fmt)
_file_handler.setLevel(logging.DEBUG)

# ── Console handler ───────────────────────────────────────────────────────
_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setFormatter(_fmt)
_console_handler.setLevel(logging.DEBUG)

# ── Root logger ───────────────────────────────────────────────────────────
root = logging.getLogger()
root.setLevel(logging.INFO)

# Guard: only add handlers once (safe for multiple imports)
_log_file_abs = os.path.abspath(LOG_FILE)
if not any(
    isinstance(h, logging.handlers.RotatingFileHandler)
    and os.path.abspath(getattr(h, "baseFilename", "")) == _log_file_abs
    for h in root.handlers
):
    root.addHandler(_file_handler)

if not any(
    isinstance(h, logging.StreamHandler)
    and not isinstance(h, logging.FileHandler)
    for h in root.handlers
):
    root.addHandler(_console_handler)

# ── Silence noisy third-party loggers ─────────────────────────────────────
for _noisy in ("httpx", "httpcore", "urllib3", "werkzeug"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger inheriting root-level handlers."""
    return logging.getLogger(name)
