# -*- coding: utf-8 -*-
"""
watcher.py
~~~~~~~~~~
Auto-restarting process supervisor for DocMind.

Uses pure os.stat() polling — catches file changes from ANY source:
  • Kiro IDE edits          • VS Code saves
  • git checkouts           • Manual edits
  • Atomic writes (rename)  • Any other tool

Behaviour:
  • Polls watched files every POLL_INTERVAL seconds.
  • Restarts the target server immediately on any mtime change.
  • If the server crashes it waits RESTART_DELAY seconds then restarts.
  • Runs forever — Ctrl+C shuts everything down cleanly.

Usage (run from project root):
    python watcher.py app           → watch + run app.py        (port 5000)
    python watcher.py admin         → watch + run admin_app.py  (port 5001)
    python watcher.py all           → launch both in sub-processes
"""

import os
import sys
import time
import subprocess
import threading
import signal
import logging
from pathlib import Path

# ── Config ─────────────────────────────────────────────────────────────────
ROOT           = Path(__file__).parent.resolve()
PYTHON         = sys.executable
POLL_INTERVAL  = 1.0    # seconds between mtime checks
RESTART_DELAY  = 2.0    # seconds to wait after a crash before relaunch
DEBOUNCE       = 1.5    # ignore duplicate triggers within this window (s)

WATCH_EXTENSIONS = {".py", ".html", ".css", ".js", ".env", ".json"}
# Runtime data changes during uploads and ingestion.  They must never trigger a
# Flask restart; Qdrant writes metadata JSON files under both data directories.
IGNORE_DIRS      = {"__pycache__", ".git", "logs", "uploads", "Yash",
                    ".kiro", "vector_store", "storage", "snapshots",
                    "node_modules"}

SERVERS = {
    "app":   {"script": "app.py",       "label": "Chat  (5000)"},
    "admin": {"script": "admin_app.py", "label": "Admin (5001)"},
}

# ── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s [WATCHER] %(message)s",
    datefmt = "%H:%M:%S",
)
log = logging.getLogger("watcher")


# ── Process wrapper ────────────────────────────────────────────────────────

class ManagedServer:
    """Wraps a subprocess — restarts on crash or external trigger."""

    def __init__(self, script: str, label: str):
        self.script = ROOT / script
        self.label  = label
        self._proc: subprocess.Popen | None = None
        self._lock  = threading.Lock()
        self._stop  = threading.Event()
        self._last_restart = 0.0

    def start(self):
        self._stop.clear()
        self._launch()
        t = threading.Thread(target=self._monitor, daemon=True,
                             name=f"mon-{self.script.name}")
        t.start()

    def stop(self):
        self._stop.set()
        self._kill()

    def trigger_restart(self, reason: str = "file change"):
        now = time.monotonic()
        if now - self._last_restart < DEBOUNCE:
            return
        self._last_restart = now
        log.info(f"[{self.label}]  Restarting — {reason}")
        self._kill()
        # _monitor will relaunch automatically after kill

    def _launch(self):
        with self._lock:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUNBUFFERED"] = "1"
            log.info(f"[{self.label}]  Starting {self.script.name} …")

            # Open a per-restart stderr log so crashes are never silent
            crash_log = open(
                str(ROOT / "logs" / f"crash_{self.script.stem}.log"),
                "a", encoding="utf-8"
            )
            self._proc = subprocess.Popen(
                [PYTHON, str(self.script)],
                cwd    = str(ROOT),
                env    = env,
                stderr = crash_log,
            )

    def _kill(self):
        with self._lock:
            if self._proc and self._proc.poll() is None:
                try:
                    self._proc.terminate()
                    try:
                        self._proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self._proc.kill()
                except Exception:
                    pass
            self._proc = None

    def _monitor(self):
        """Keep-alive: relaunch whenever the process exits unexpectedly."""
        while not self._stop.is_set():
            with self._lock:
                proc = self._proc

            if proc is None:
                # Just killed for a restart — relaunch shortly
                time.sleep(0.4)
                if not self._stop.is_set():
                    self._launch()
                continue

            ret = proc.poll()
            if ret is not None:
                log.warning(
                    f"[{self.label}]  Crashed (exit {ret}). "
                    f"Restarting in {RESTART_DELAY}s …"
                )
                time.sleep(RESTART_DELAY)
                if not self._stop.is_set():
                    self._launch()
            else:
                time.sleep(0.5)


# ── mtime-based file poller ────────────────────────────────────────────────

def _collect_watched_files(root: Path) -> dict[str, float]:
    """Walk root and return {path_str: mtime} for all watched files."""
    result: dict[str, float] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune ignored directories in-place so os.walk skips them
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        for fname in filenames:
            if Path(fname).suffix.lower() in WATCH_EXTENSIONS:
                full = os.path.join(dirpath, fname)
                try:
                    result[full] = os.stat(full).st_mtime
                except OSError:
                    pass
    return result


def _poll_loop(servers: list[ManagedServer], stop_event: threading.Event):
    """Runs in a background thread. Polls mtimes and triggers restarts."""
    snapshot = _collect_watched_files(ROOT)
    log.info(f"Watching {len(snapshot)} files under {ROOT}")

    while not stop_event.is_set():
        time.sleep(POLL_INTERVAL)
        current = _collect_watched_files(ROOT)

        changed: list[str] = []

        # Modified or new files
        for path, mtime in current.items():
            if snapshot.get(path) != mtime:
                changed.append(path)

        if changed:
            snapshot = current
            for path in changed:
                rel = os.path.relpath(path, ROOT)
                for srv in servers:
                    srv.trigger_restart(f"{rel} changed")
        else:
            snapshot = current  # pick up any new files for next round


# ── Entry point ───────────────────────────────────────────────────────────

def main():
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "all"

    if mode not in ("app", "admin", "all"):
        print("Usage: python watcher.py [app | admin | all]")
        sys.exit(1)

    targets = list(SERVERS.values()) if mode == "all" else [SERVERS[mode]]

    servers = [
        ManagedServer(script=cfg["script"], label=cfg["label"])
        for cfg in targets
    ]

    # Start all servers
    for srv in servers:
        srv.start()

    labels    = " + ".join(s.label for s in servers)
    stop_flag = threading.Event()

    # Start pure-Python mtime poller
    poller = threading.Thread(
        target=_poll_loop,
        args=(servers, stop_flag),
        daemon=True,
        name="mtime-poller",
    )
    poller.start()

    log.info(f"Managing: {labels}  |  poll every {POLL_INTERVAL}s")
    log.info("Press Ctrl+C to stop all servers.")

    def _shutdown(sig=None, frame=None):
        log.info("Shutting down …")
        stop_flag.set()
        for srv in servers:
            srv.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        _shutdown()


if __name__ == "__main__":
    main()
