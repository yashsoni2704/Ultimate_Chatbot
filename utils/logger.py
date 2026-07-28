import logging
import os
import sys
from datetime import datetime

# ── UTF-8 stdout (Windows fix) ────────────────────────────────────────────
# Must be done BEFORE creating any StreamHandler so the handler
# captures the patched stream, not the original one.
if sys.platform == "win32":
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass  # already wrapped or running in an environment that doesn't need it

# ── Log directory & file ──────────────────────────────────────────────────
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
log_file  = os.path.join(LOG_DIR, f"app_{timestamp}.log")

# ── Formatters ────────────────────────────────────────────────────────────
_fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")

# ── Handlers ──────────────────────────────────────────────────────────────
_file_handler = logging.FileHandler(log_file, encoding="utf-8")
_file_handler.setFormatter(_fmt)
_file_handler.setLevel(logging.DEBUG)

_console_handler = logging.StreamHandler(sys.stdout)   # uses the patched stdout
_console_handler.setFormatter(_fmt)
_console_handler.setLevel(logging.DEBUG)

# ── Root logger ───────────────────────────────────────────────────────────
# Get the root logger directly instead of using basicConfig
# (basicConfig is a no-op when Flask/Werkzeug has already added handlers).
root = logging.getLogger()
root.setLevel(logging.INFO)

# Avoid duplicate handlers if this module is imported multiple times
if not any(isinstance(h, logging.FileHandler) and h.baseFilename == os.path.abspath(log_file)
           for h in root.handlers):
    root.addHandler(_file_handler)

if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
           for h in root.handlers):
    root.addHandler(_console_handler)

# ── Silence noisy third-party loggers ─────────────────────────────────────
for _noisy in ("httpx", "httpcore", "urllib3", "werkzeug"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger. Always inherits root-level handlers."""
    return logging.getLogger(name)
