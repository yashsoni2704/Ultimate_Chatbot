# -*- coding: utf-8 -*-
"""
Admin Panel — standalone Flask app on port 5001.

Responsibilities
----------------
  GET  /admin/               Serve the admin UI
  POST /admin/load-documents Accept 1–N file uploads, enqueue each as a job
  POST /admin/load-url       Scrape / download a URL, enqueue as a job
  GET  /admin/job/<id>       Poll individual job status
  GET  /admin/queue          Poll the whole queue (all jobs, ordered)
  GET  /admin/documents      List ingested documents
  POST /admin/delete-document Delete a document
  GET  /admin/api/stats      Chat + doc stats
  GET  /admin/api/chat-logs  Recent chat logs (paginated)
  GET  /admin/api/visitors   Visitor records
  GET  /admin/api/bookings   Booking records
  GET  /admin/api/users      User records
  GET  /admin/health         Health check

Upload Queue design
-------------------
  • A single background worker thread (daemon) pulls jobs from a
    queue.Queue and processes them one at a time.
  • This guarantees the blue/green pipeline is never called concurrently
    from admin_app.py, which prevents the slot-collision bug.
  • Each job has a unique job_id.  The browser polls /admin/job/<id>
    for its individual status.  /admin/queue returns all jobs so the
    UI can render the whole queue panel.
  • Jobs are kept in memory; on restart the queue is empty (uploads
    already on disk will be re-ingested if the admin refreshes).
"""

import os
import json
import queue
import uuid
import threading
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, request, jsonify, Response
from werkzeug.utils import secure_filename

from config import Config
from utils.loader import process_document, load_url
from utils.embeddings import get_all_documents, delete_document_chunks
from utils.logger import get_logger

from db.connection import get_db
from db.models import (
    ensure_indexes,
    get_chat_stats,
    get_recent_chat_logs,
    get_all_visitors,
    get_all_bookings,
    get_all_users,
    get_dissatisfied_users,
    count_dissatisfied_users,
    update_dissatisfied_status,
    get_visitor_chat_history,
    get_llm_performance_stats,
)

logger = get_logger(__name__)

# ── Flask setup ───────────────────────────────────────────────────────────────
admin_app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
)
admin_app.config["UPLOAD_FOLDER"] = Config.UPLOAD_FOLDER

os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
os.makedirs(Config.QDRANT_PATH, exist_ok=True)


# ════════════════════════════════════════════════════════════════════════════
# Job store + serial ingestion queue
# ════════════════════════════════════════════════════════════════════════════

# job_id → {
#   "status":   "queued" | "processing" | "done" | "error",
#   "filename": str,
#   "message":  str,
#   "queued_at": ISO str,
#   "started_at": ISO str | None,
#   "finished_at": ISO str | None,
#   "documents": list   (populated on done)
# }
_jobs: dict        = {}
_jobs_lock         = threading.Lock()
_job_order: list   = []       # ordered list of job_ids for queue panel

# FIFO work queue — worker picks one item at a time
_work_queue: queue.Queue = queue.Queue()


# ── Job CRUD helpers ─────────────────────────────────────────────────────────

def _new_job(filename: str) -> str:
    job_id = uuid.uuid4().hex
    with _jobs_lock:
        _jobs[job_id] = {
            "status":      "queued",
            "filename":    filename,
            "message":     "Waiting in queue…",
            "queued_at":   datetime.now().isoformat(),
            "started_at":  None,
            "finished_at": None,
            "documents":   [],
        }
        _job_order.append(job_id)
    logger.info(f"  Job {job_id[:8]} queued: {filename}")
    return job_id


def _start_job(job_id: str) -> None:
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id]["status"]     = "processing"
            _jobs[job_id]["message"]    = "Processing…"
            _jobs[job_id]["started_at"] = datetime.now().isoformat()
    logger.info(f"  Job {job_id[:8]} processing")


def _finish_job(job_id: str, message: str) -> None:
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id].update({
                "status":      "done",
                "message":     message,
                "finished_at": datetime.now().isoformat(),
                "documents":   get_all_documents(),
            })
    logger.info(f"  Job {job_id[:8]} done: {message}")


def _fail_job(job_id: str, error: str) -> None:
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id].update({
                "status":      "error",
                "message":     error,
                "finished_at": datetime.now().isoformat(),
                "documents":   [],
            })
    logger.error(f"  Job {job_id[:8]} failed: {error}")


def _get_job(job_id: str) -> dict | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def _get_queue_snapshot() -> list:
    """Return an ordered list of all job dicts (copy, thread-safe)."""
    with _jobs_lock:
        return [dict(_jobs[jid]) | {"job_id": jid}
                for jid in _job_order if jid in _jobs]


# ── Worker thread ────────────────────────────────────────────────────────────

def _queue_worker() -> None:
    """
    Daemon thread that processes one ingestion job at a time from _work_queue.
    Guarantees the blue/green pipeline is never entered concurrently.
    """
    while True:
        job_id, task_fn = _work_queue.get()
        _start_job(job_id)
        try:
            message = task_fn()
            _finish_job(job_id, message)
        except Exception as exc:
            _fail_job(job_id, str(exc))
        finally:
            _work_queue.task_done()


_worker_thread = threading.Thread(
    target=_queue_worker, daemon=True, name="ingestion-worker"
)
_worker_thread.start()
logger.info("  Ingestion queue worker started")


# ── Enqueue helpers ──────────────────────────────────────────────────────────

def _enqueue_document(save_path: str, filename: str) -> str:
    """Save path is already on disk. Enqueue processing. Returns job_id."""
    job_id = _new_job(filename)

    def _task():
        if Config.LANGCHAIN_TRACING_V2:
            from langsmith import trace as ls_trace
            with ls_trace(
                name=f"admin_ingest:{filename}",
                run_type="chain",
                project_name=Config.LANGCHAIN_PROJECT,
                tags=["admin", "ingestion", "docmind"],
                metadata={"filename": filename, "source": "admin_panel"},
            ):
                return process_document(save_path)
        return process_document(save_path)

    _work_queue.put((job_id, _task))
    return job_id


def _enqueue_url(url: str) -> str:
    """Enqueue a URL ingestion job. Returns job_id."""
    job_id = _new_job(url)

    def _task():
        if Config.LANGCHAIN_TRACING_V2:
            from langsmith import trace as ls_trace
            with ls_trace(
                name=f"admin_ingest_url:{url}",
                run_type="chain",
                project_name=Config.LANGCHAIN_PROJECT,
                tags=["admin", "ingestion", "url", "docmind"],
                metadata={"url": url, "source": "admin_panel"},
            ):
                return load_url(url)
        return load_url(url)

    _work_queue.put((job_id, _task))
    return job_id


# ── Basic Auth ────────────────────────────────────────────────────────────────
_ADMIN_USER = os.getenv("ADMIN_USERNAME", "").strip()
_ADMIN_PASS = os.getenv("ADMIN_PASSWORD", "").strip()

if not _ADMIN_USER or not _ADMIN_PASS:
    logger.warning(
        "  ADMIN_USERNAME or ADMIN_PASSWORD is not set — "
        "admin panel is unprotected! Set both in .env for production."
    )


def _check_auth(username: str, password: str) -> bool:
    if not _ADMIN_USER or not _ADMIN_PASS:
        return True
    return username == _ADMIN_USER and password == _ADMIN_PASS


@admin_app.before_request
def _require_admin_auth():
    if request.path == "/admin/health":
        return
    auth = request.authorization
    if not _check_auth(
        auth.username if auth else "",
        auth.password if auth else "",
    ):
        return Response(
            "Admin access requires authentication.",
            401,
            {"WWW-Authenticate": 'Basic realm="DocMind Admin"'},
        )


# ── MongoDB startup ───────────────────────────────────────────────────────────
def _initialize_db_startup() -> None:
    try:
        get_db().command("ping", maxTimeMS=2000)
        ensure_indexes()
        logger.info("  MongoDB ready (admin)")
    except Exception as exc:
        logger.warning(f"  MongoDB unavailable at startup: {exc}")

threading.Thread(target=_initialize_db_startup, daemon=True).start()

logger.info("  ADMIN PANEL STARTED")
logger.info(f"  Timestamp    : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
logger.info(f"  URL          : http://localhost:5001/admin")
logger.info(f"  Upload folder: {os.path.abspath(Config.UPLOAD_FOLDER)}")
logger.info(f"  Vector store : {os.path.abspath(Config.QDRANT_PATH)}")
logger.info(f"  MongoDB DB   : {Config.MONGO_DB_NAME}")
logger.info(
    f"  LangSmith    : "
    f"{'ENABLED — project=' + Config.LANGCHAIN_PROJECT if Config.LANGCHAIN_TRACING_V2 else 'DISABLED'}"
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _allowed_file(filename: str) -> bool:
    ext = os.path.splitext(filename)[1].lstrip(".").lower()
    return ext in Config.ALLOWED_EXTENSIONS


# ════════════════════════════════════════════════════════════════════════════
# UI Route
# ════════════════════════════════════════════════════════════════════════════

@admin_app.route("/admin/")
@admin_app.route("/admin")
def admin_home():
    return render_template("admin.html")


# ════════════════════════════════════════════════════════════════════════════
# JOB POLLING
# ════════════════════════════════════════════════════════════════════════════

@admin_app.route("/admin/job/<job_id>", methods=["GET"])
def admin_job_status(job_id):
    """Poll the status of a single background ingestion job."""
    job = _get_job(job_id)
    if job is None:
        return jsonify({"status": "error", "message": "Job not found."}), 404
    return jsonify(job)


@admin_app.route("/admin/queue", methods=["GET"])
def admin_queue_status():
    """Return the full ordered queue snapshot for the queue panel UI."""
    return jsonify({
        "jobs":    _get_queue_snapshot(),
        "pending": _work_queue.qsize(),
    })


# ════════════════════════════════════════════════════════════════════════════
# DOCUMENT MANAGEMENT
# ════════════════════════════════════════════════════════════════════════════

@admin_app.route("/admin/load-documents", methods=["POST"])
def admin_load_documents():
    """
    Accept 1–N file uploads in a single request.

    Each file is saved to uploads/ immediately (synchronous, fast) and then
    a job is queued for the heavy OCR + embedding work.  The endpoint returns
    202 with a list of job_ids the browser polls individually.

    FormData field: "files" (multiple) — standard multipart/form-data.
    """
    try:
        files = request.files.getlist("files")
        if not files or all(f.filename == "" for f in files):
            return jsonify({"status": "error", "message": "No files received."}), 400

        accepted = []
        rejected = []

        for file in files:
            if not file.filename:
                continue

            filename = secure_filename(file.filename)

            if not _allowed_file(filename):
                exts = ", ".join(sorted(Config.ALLOWED_EXTENSIONS)).upper()
                rejected.append({
                    "filename": filename,
                    "reason":   f"Unsupported file type. Supported: {exts}",
                })
                continue

            save_path = os.path.join(admin_app.config["UPLOAD_FOLDER"], filename)
            try:
                file.save(save_path)
                logger.info(f"  Saved upload: {filename}")
            except OSError as save_err:
                rejected.append({
                    "filename": filename,
                    "reason":   f"Could not save file: {save_err}",
                })
                continue

            job_id = _enqueue_document(save_path, filename)
            accepted.append({"filename": filename, "job_id": job_id})

        if not accepted and rejected:
            return jsonify({
                "status":   "error",
                "message":  "All files were rejected.",
                "rejected": rejected,
            }), 400

        return jsonify({
            "status":   "accepted",
            "accepted": accepted,
            "rejected": rejected,
            "message":  (
                f"{len(accepted)} file(s) queued for processing"
                + (f", {len(rejected)} rejected" if rejected else "")
                + "."
            ),
        }), 202

    except Exception as exc:
        logger.error(f"  /admin/load-documents error: {exc}")
        return jsonify({"status": "error", "message": str(exc)}), 500


# Keep old single-file endpoint for backward compatibility
@admin_app.route("/admin/load-document", methods=["POST"])
def admin_load_document():
    """Legacy single-file endpoint — delegates to load-documents."""
    try:
        if "file" not in request.files:
            return jsonify({"status": "error", "message": "No file in request."}), 400

        file = request.files["file"]
        if file.filename == "":
            return jsonify({"status": "error", "message": "No file selected."}), 400

        filename = secure_filename(file.filename)
        if not _allowed_file(filename):
            exts = ", ".join(sorted(Config.ALLOWED_EXTENSIONS)).upper()
            return jsonify({
                "status":  "error",
                "message": f"Unsupported file type. Supported formats: {exts}",
            }), 400

        save_path = os.path.join(admin_app.config["UPLOAD_FOLDER"], filename)
        file.save(save_path)
        logger.info(f"  Admin uploaded: {filename}")

        job_id = _enqueue_document(save_path, filename)
        return jsonify({"status": "accepted", "job_id": job_id}), 202

    except Exception as exc:
        logger.error(f"  Admin upload error: {exc}")
        return jsonify({"status": "error", "message": str(exc)}), 500


@admin_app.route("/admin/load-url", methods=["POST"])
def admin_load_url():
    """Accept a URL and enqueue an ingestion job."""
    try:
        data = request.get_json()
        if not data or not data.get("url"):
            return jsonify({"status": "error", "message": "url is required."}), 400

        url = data["url"].strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            return jsonify({
                "status":  "error",
                "message": "Invalid URL. Must start with http:// or https://",
            }), 400

        logger.info(f"  Admin URL ingestion requested: {url}")
        job_id = _enqueue_url(url)
        return jsonify({"status": "accepted", "job_id": job_id}), 202

    except Exception as exc:
        logger.error(f"  Admin URL ingestion error: {exc}")
        return jsonify({"status": "error", "message": str(exc)}), 500


@admin_app.route("/admin/documents", methods=["GET"])
def admin_documents():
    try:
        docs = get_all_documents()
        return jsonify({"status": "success", "documents": docs, "total": len(docs)})
    except Exception as exc:
        logger.error(f"  Error fetching documents: {exc}")
        return jsonify({"status": "error", "message": str(exc)}), 500


@admin_app.route("/admin/delete-document", methods=["POST"])
def admin_delete_document():
    try:
        data = request.get_json()
        if not data or not data.get("filename"):
            return jsonify({"status": "error", "message": "filename is required."}), 400

        filename      = data["filename"]
        registry_path = os.path.join(Config.QDRANT_PATH, "registry.json")

        if not os.path.exists(registry_path):
            return jsonify({"status": "error", "message": "Registry not found."}), 404

        with open(registry_path, "r", encoding="utf-8") as f:
            records = json.load(f)

        matching = [r for r in records if r.get("filename") == filename]
        if not matching:
            return jsonify({
                "status":  "error",
                "message": f"'{filename}' not found in knowledge base.",
            }), 404

        record    = matching[0]
        file_path = record.get("path", "")

        # ── Step 1: Delete physical file first ───────────────────────────
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info(f"  Deleted file from disk: {file_path}")
            except PermissionError:
                return jsonify({
                    "status":  "error",
                    "message": (
                        f"'{filename}' is currently open in another application. "
                        "Please close the file and try again."
                    ),
                }), 409
            except OSError as exc:
                return jsonify({
                    "status":  "error",
                    "message": f"Could not delete file: {exc}",
                }), 500

        # ── Step 2: Delete vectors (blue/green pipeline) ─────────────────
        try:
            deleted = delete_document_chunks(filename)
            logger.info(f"  Removed {deleted} vector(s) for '{filename}' from Qdrant")
        except Exception as vec_err:
            logger.error(
                f"  Vector delete failed for '{filename}': {vec_err} "
                "— cleaning registry anyway"
            )

        # ── Step 3: Remove from registry (atomic write) ──────────────────
        from utils.embeddings import _save_registry
        remaining = [r for r in records if r.get("filename") != filename]
        _save_registry(remaining)

        logger.info(f"  '{filename}' fully removed from knowledge base")
        return jsonify({
            "status":    "success",
            "message":   f"'{filename}' removed from knowledge base.",
            "documents": get_all_documents(),
        })

    except Exception as exc:
        logger.error(f"  Error deleting document: {exc}")
        return jsonify({"status": "error", "message": str(exc)}), 500


# ════════════════════════════════════════════════════════════════════════════
# ANALYTICS API
# ════════════════════════════════════════════════════════════════════════════

@admin_app.route("/admin/api/stats", methods=["GET"])
def api_stats():
    try:
        chat         = get_chat_stats()
        docs         = get_all_documents()
        total_chunks = sum(d.get("chunks", 0) for d in docs)
        db           = get_db()

        return jsonify({
            "status": "success",
            "stats": {
                "total_chats":     chat["total"],
                "rag_chats":       chat["rag"],
                "faq_chats":       chat["faq"],
                "smalltalk_chats": chat["smalltalk"],
                "unique_visitors": chat["unique_visitors"],
                "unique_users":    chat["unique_users"],
                "total_documents": len(docs),
                "total_chunks":    total_chunks,
                "total_visitors":  db["visitors"].count_documents({}),
                "total_bookings":  db["bookings"].count_documents({}),
                "total_users":     db["users"].count_documents({}),
            },
        })
    except Exception as exc:
        logger.error(f"  /admin/api/stats error: {exc}")
        return jsonify({"status": "error", "message": str(exc)}), 500


@admin_app.route("/admin/api/llm-performance", methods=["GET"])
def api_llm_performance():
    try:
        stats = get_llm_performance_stats()
        return jsonify({
            "status": "success",
            "stats": stats
        })
    except Exception as exc:
        logger.error(f"  /admin/api/llm-performance error: {exc}")
        return jsonify({"status": "error", "message": str(exc)}), 500


@admin_app.route("/admin/api/chat-logs", methods=["GET"])
def api_chat_logs():
    try:
        page  = max(int(request.args.get("page", 1)), 1)
        limit = 10
        skip  = (page - 1) * limit
        logs  = get_recent_chat_logs(limit=limit, skip=skip)
        total = get_db()["chat_logs"].count_documents({})

        visitor_ids   = list({log.get("visitor_id", "") for log in logs if log.get("visitor_id")})
        visitor_names = {}
        if visitor_ids:
            for v in get_db()["visitors"].find(
                {"visitor_id": {"$in": visitor_ids}},
                {"visitor_id": 1, "name": 1, "_id": 0},
            ):
                if v.get("name"):
                    visitor_names[v["visitor_id"]] = v["name"]

        for log in logs:
            vid = log.get("visitor_id", "")
            if vid and vid in visitor_names:
                log["visitor_name"] = visitor_names[vid]

        return jsonify({
            "status": "success",
            "page":   page,
            "limit":  limit,
            "total":  total,
            "logs":   logs,
        })
    except Exception as exc:
        logger.error(f"  /admin/api/chat-logs error: {exc}")
        return jsonify({"status": "error", "message": str(exc)}), 500


@admin_app.route("/admin/api/visitors", methods=["GET"])
def api_visitors():
    try:
        limit    = min(int(request.args.get("limit", 100)), 500)
        visitors = get_all_visitors(limit=limit)
        return jsonify({"status": "success", "total": len(visitors), "visitors": visitors})
    except Exception as exc:
        logger.error(f"  /admin/api/visitors error: {exc}")
        return jsonify({"status": "error", "message": str(exc)}), 500


@admin_app.route("/admin/api/bookings", methods=["GET"])
def api_bookings():
    try:
        bookings = get_all_bookings()
        return jsonify({"status": "success", "total": len(bookings), "bookings": bookings})
    except Exception as exc:
        logger.error(f"  /admin/api/bookings error: {exc}")
        return jsonify({"status": "error", "message": str(exc)}), 500


@admin_app.route("/admin/api/users", methods=["GET"])
def api_users():
    try:
        users = get_all_users()
        return jsonify({"status": "success", "total": len(users), "users": users})
    except Exception as exc:
        logger.error(f"  /admin/api/users error: {exc}")
        return jsonify({"status": "error", "message": str(exc)}), 500


# ════════════════════════════════════════════════════════════════════════════
# STT PROVIDER
# ════════════════════════════════════════════════════════════════════════════

@admin_app.route("/admin/stt/provider", methods=["GET"])
def admin_stt_get():
    from utils.transcribe import read_active_provider, VALID_PROVIDERS
    provider = read_active_provider()
    return jsonify({
        "status":   "success",
        "provider": provider,
        "label":    VALID_PROVIDERS.get(provider, provider),
        "all":      [{"key": k, "label": v} for k, v in VALID_PROVIDERS.items()],
    })


@admin_app.route("/admin/stt/provider", methods=["POST"])
def admin_stt_set():
    from utils.transcribe import set_active_provider, VALID_PROVIDERS
    data     = request.get_json() or {}
    provider = (data.get("provider") or "").strip().lower()

    if not provider:
        return jsonify({"status": "error", "message": "provider is required."}), 400
    if provider not in VALID_PROVIDERS:
        return jsonify({
            "status":  "error",
            "message": f"Unknown provider '{provider}'. Valid: {list(VALID_PROVIDERS)}",
        }), 400

    try:
        set_active_provider(provider)
        logger.info(f"  [STT] Admin switched provider → {provider}")
        return jsonify({
            "status":   "success",
            "provider": provider,
            "label":    VALID_PROVIDERS[provider],
            "message":  (
                f"STT provider switched to {VALID_PROVIDERS[provider]}. "
                "Takes effect on next mic session."
            ),
        })
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


# ════════════════════════════════════════════════════════════════════════════
# HEALTH CHECK
# ════════════════════════════════════════════════════════════════════════════

@admin_app.route("/admin/health")
def admin_health():
    mongo_ok = False
    try:
        get_db().command("ping")
        mongo_ok = True
    except Exception:
        pass
    return jsonify({
        "status":        "running",
        "panel":         "admin",
        "mongodb":       "connected" if mongo_ok else "unavailable",
        "queue_pending": _work_queue.qsize(),
    })


# ════════════════════════════════════════════════════════════════════════════
# DISSATISFIED USERS  — admin panel
# ════════════════════════════════════════════════════════════════════════════

@admin_app.route("/admin/api/dissatisfied-users", methods=["GET"])
def admin_dissatisfied_users():
    """
    List dissatisfied users with optional status filter and pagination.
    Query params: status (open|solved|rejected), page, per_page
    """
    try:
        status   = request.args.get("status", "").strip() or None
        page     = max(int(request.args.get("page",     1)),  1)
        per_page = max(int(request.args.get("per_page", 20)), 1)
        skip     = (page - 1) * per_page

        users = get_dissatisfied_users(status=status, limit=per_page, skip=skip)
        total = count_dissatisfied_users(status=status)

        # Counts by status for badges
        counts = {
            "open":     count_dissatisfied_users("open"),
            "solved":   count_dissatisfied_users("solved"),
            "rejected": count_dissatisfied_users("rejected"),
            "total":    count_dissatisfied_users(),
        }

        return jsonify({
            "status": "success",
            "users":  users,
            "total":  total,
            "page":   page,
            "pages":  max(1, -(-total // per_page)),   # ceil division
            "counts": counts,
        })
    except Exception as e:
        logger.error(f" Error in /admin/api/dissatisfied-users: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@admin_app.route("/admin/api/dissatisfied-users/<record_id>/status", methods=["POST"])
def admin_update_dissatisfied_status(record_id):
    """
    Mark a dissatisfied user as solved or rejected.
    Body: { "status": "solved"|"rejected"|"open", "notes": "" }
    """
    try:
        data   = request.get_json() or {}
        status = data.get("status", "").strip().lower()
        notes  = data.get("notes", "").strip()

        if status not in ("open", "solved", "rejected"):
            return jsonify({"status": "error", "message": "status must be open, solved, or rejected"}), 400

        update_dissatisfied_status(record_id, status, notes)
        logger.info(f"  Dissatisfied user {record_id} → {status}")
        return jsonify({"status": "success", "record_id": record_id, "new_status": status})

    except Exception as e:
        logger.error(f" Error updating dissatisfied status: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@admin_app.route("/admin/api/visitor-chat-history/<visitor_id>", methods=["GET"])
def admin_visitor_chat_history(visitor_id):
    """
    Return full chat history for a visitor, with feedback flags per message.
    Used by the admin panel chat viewer when clicking a dissatisfied user row.
    """
    try:
        if not visitor_id or len(visitor_id) < 8:
            return jsonify({"status": "error", "message": "Invalid visitor_id"}), 400

        limit   = min(int(request.args.get("limit", 200)), 500)
        history = get_visitor_chat_history(visitor_id, limit=limit)

        # Also fetch visitor profile and dissatisfied record for context
        from db.models import get_visitor as _gv
        from db.connection import get_db as _db
        visitor    = _gv(visitor_id) or {}
        dis_record = _db()["dissatisfied_users"].find_one(
            {"visitor_id": visitor_id}, {"_id": 0}
        )

        return jsonify({
            "status":         "success",
            "visitor_id":     visitor_id,
            "visitor":        visitor,
            "dis_record":     dis_record,
            "history":        history,
            "total_messages": len(history),
        })

    except Exception as e:
        logger.error(f" Error fetching visitor chat history: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    admin_app.run(host="0.0.0.0", port=5001, debug=False, use_reloader=False)
