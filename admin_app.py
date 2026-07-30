# -*- coding: utf-8 -*-
"""
Admin Panel — standalone Flask app on port 5001.

Responsibilities:
  - Serve the admin UI         (GET  /admin/)
  - Accept file uploads        (POST /admin/load-document)
  - Scrape + ingest URL        (POST /admin/load-url)
  - List ingested docs         (GET  /admin/documents)
  - Delete a document          (POST /admin/delete-document)
  - Analytics — chat stats     (GET  /admin/api/stats)
  - Analytics — recent chats   (GET  /admin/api/chat-logs)
  - Analytics — visitors       (GET  /admin/api/visitors)
  - Analytics — bookings       (GET  /admin/api/bookings)
  - Health check               (GET  /admin/health)
"""

import os
import json
from datetime import datetime
from functools import wraps
from threading import Thread

from flask import Flask, render_template, request, jsonify, Response
from werkzeug.utils import secure_filename

from config import Config
from utils.loader import process_document, load_url
from utils.embeddings import get_all_documents, delete_document_chunks
from utils.logger import get_logger

# MongoDB helpers
from db.connection import get_db
from db.models import (
    ensure_indexes,
    get_chat_stats,
    get_recent_chat_logs,
    get_all_visitors,
    get_all_bookings,
    get_all_users,
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

# ── Basic Auth ────────────────────────────────────────────────────────────────
# Credentials are read from .env.  If either is blank the panel still starts
# but logs a warning — useful for local dev, not acceptable in production.

_ADMIN_USER = os.getenv("ADMIN_USERNAME", "").strip()
_ADMIN_PASS = os.getenv("ADMIN_PASSWORD", "").strip()

if not _ADMIN_USER or not _ADMIN_PASS:
    logger.warning(
        "  ADMIN_USERNAME or ADMIN_PASSWORD is not set — "
        "admin panel is unprotected! Set both in .env for production."
    )


def _check_auth(username: str, password: str) -> bool:
    """Return True only when credentials match and are non-empty."""
    if not _ADMIN_USER or not _ADMIN_PASS:
        return True   # auth disabled — dev mode
    return username == _ADMIN_USER and password == _ADMIN_PASS


def _auth_required(f):
    """Decorator: demand HTTP Basic Auth on every admin route."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not _check_auth(auth.username, auth.password):
            return Response(
                "Admin access requires authentication.",
                401,
                {"WWW-Authenticate": 'Basic realm="DocMind Admin"'},
            )
        return f(*args, **kwargs)
    return decorated


@admin_app.before_request
def _require_admin_auth():
    """Protect every route except /admin/health."""
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
        # Quick check with timeout
        get_db().command("ping", maxTimeMS=2000)
        ensure_indexes()
        logger.info(" MongoDB ready (admin)")
    except Exception as _e:
        logger.warning(f"  MongoDB unavailable at startup: {_e}")

Thread(target=_initialize_db_startup, daemon=True).start()

logger.info("  ADMIN PANEL STARTED")
logger.info(f"Timestamp    : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
logger.info(f"URL          : http://localhost:5001/admin")
logger.info(f"Upload folder: {os.path.abspath(Config.UPLOAD_FOLDER)}")
logger.info(f"Vector store : {os.path.abspath(Config.QDRANT_PATH)}")
logger.info(f"MongoDB DB   : {Config.MONGO_DB_NAME}")
logger.info(
    f"LangSmith tracing: {' ENABLED — project=' + Config.LANGCHAIN_PROJECT if Config.LANGCHAIN_TRACING_V2 else '⏸  DISABLED'}"
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _allowed_file(filename: str) -> bool:
    ext = os.path.splitext(filename)[1].lstrip(".").lower()
    return ext in Config.ALLOWED_EXTENSIONS


# ════════════════════════════════════════════════════════════════════════════
# UI Routes
# ════════════════════════════════════════════════════════════════════════════

@admin_app.route("/admin/")
@admin_app.route("/admin")
def admin_home():
    return render_template("admin.html")


# ════════════════════════════════════════════════════════════════════════════
# DOCUMENT MANAGEMENT
# ════════════════════════════════════════════════════════════════════════════

@admin_app.route("/admin/load-document", methods=["POST"])
def admin_load_document():
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
                "status": "error",
                "message": f"Unsupported file type. Supported formats: {exts}"
            }), 400

        save_path = os.path.join(admin_app.config["UPLOAD_FOLDER"], filename)
        file.save(save_path)
        logger.info(f" Admin uploaded: {filename}")

        if Config.LANGCHAIN_TRACING_V2:
            from langsmith import trace as ls_trace
            with ls_trace(
                name=f"admin_ingest:{filename}",
                run_type="chain",
                project_name=Config.LANGCHAIN_PROJECT,
                tags=["admin", "ingestion", "docmind"],
                metadata={
                    "filename": filename,
                    "source":   "admin_panel",
                    "endpoint": "/admin/load-document",
                    "app":      "admin",
                },
            ):
                message = process_document(save_path)
        else:
            message = process_document(save_path)

        return jsonify({
            "status":    "success",
            "message":   message,
            "documents": get_all_documents()
        })

    except Exception as e:
        logger.error(f" Admin upload error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


@admin_app.route("/admin/load-url", methods=["POST"])
def admin_load_url():
    try:
        data = request.get_json()
        if not data or not data.get("url"):
            return jsonify({"status": "error", "message": "url is required."}), 400

        url = data["url"].strip()

        if not (url.startswith("http://") or url.startswith("https://")):
            return jsonify({
                "status": "error",
                "message": "Invalid URL. Must start with http:// or https://"
            }), 400

        logger.info(f" Admin URL ingestion requested: {url}")

        if Config.LANGCHAIN_TRACING_V2:
            from langsmith import trace as ls_trace
            with ls_trace(
                name=f"admin_ingest_url:{url}",
                run_type="chain",
                project_name=Config.LANGCHAIN_PROJECT,
                tags=["admin", "ingestion", "url", "docmind"],
                metadata={
                    "url":      url,
                    "source":   "admin_panel",
                    "endpoint": "/admin/load-url",
                    "app":      "admin",
                },
            ):
                message = load_url(url)
        else:
            message = load_url(url)

        return jsonify({
            "status":    "success",
            "message":   message,
            "documents": get_all_documents()
        })

    except ValueError as e:
        logger.warning(f"  URL scrape quality check failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        logger.error(f" Admin URL ingestion error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


@admin_app.route("/admin/documents", methods=["GET"])
def admin_documents():
    try:
        docs = get_all_documents()
        return jsonify({"status": "success", "documents": docs, "total": len(docs)})
    except Exception as e:
        logger.error(f" Error fetching documents: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


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
                "message": f"'{filename}' not found in knowledge base."
            }), 404

        record = matching[0]

        deleted = delete_document_chunks(filename)
        logger.info(f"  Removed {deleted} vector(s) for '{filename}' from Qdrant")

        remaining = [r for r in records if r.get("filename") != filename]
        with open(registry_path, "w", encoding="utf-8") as f:
            json.dump(remaining, f, indent=2, ensure_ascii=False)

        file_path = record.get("path", "")
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"  Deleted file: {file_path}")

        logger.info(f" '{filename}' fully removed from knowledge base")
        return jsonify({
            "status":    "success",
            "message":   f"'{filename}' removed from knowledge base.",
            "documents": get_all_documents()
        })

    except Exception as e:
        logger.error(f" Error deleting document: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ════════════════════════════════════════════════════════════════════════════
# ANALYTICS API  — all prefixed /admin/api/
# ════════════════════════════════════════════════════════════════════════════

@admin_app.route("/admin/api/stats", methods=["GET"])
def api_stats():
    """
    Combined dashboard stats:
      - chat counts by type
      - unique visitors / users
      - total documents + chunks
      - total bookings + visitors
    """
    try:
        chat   = get_chat_stats()
        docs   = get_all_documents()
        total_chunks = sum(d.get("chunks", 0) for d in docs)

        visitors_col = get_db()["visitors"]
        bookings_col = get_db()["bookings"]
        users_col    = get_db()["users"]

        return jsonify({
            "status": "success",
            "stats": {
                # Chat
                "total_chats":       chat["total"],
                "rag_chats":         chat["rag"],
                "faq_chats":         chat["faq"],
                "smalltalk_chats":   chat["smalltalk"],
                "unique_visitors":   chat["unique_visitors"],
                "unique_users":      chat["unique_users"],
                # Documents
                "total_documents":   len(docs),
                "total_chunks":      total_chunks,
                # Other
                "total_visitors":    visitors_col.count_documents({}),
                "total_bookings":    bookings_col.count_documents({}),
                "total_users":       users_col.count_documents({}),
            }
        })
    except Exception as e:
        logger.error(f" /admin/api/stats error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@admin_app.route("/admin/api/chat-logs", methods=["GET"])
def api_chat_logs():
    """
    Recent chat logs with page-based pagination.
    GET /admin/api/chat-logs?page=1
    Enriches each log with visitor name from the visitors collection.
    """
    try:
        page  = max(int(request.args.get("page", 1)), 1)
        limit = 10
        skip  = (page - 1) * limit
        logs  = get_recent_chat_logs(limit=limit, skip=skip)
        total = get_db()["chat_logs"].count_documents({})

        # Enrich logs with visitor name — bulk-fetch unique visitor_ids
        visitor_ids = list({log.get("visitor_id", "") for log in logs if log.get("visitor_id")})
        visitor_names = {}
        if visitor_ids:
            visitors = get_db()["visitors"].find(
                {"visitor_id": {"$in": visitor_ids}},
                {"visitor_id": 1, "name": 1, "_id": 0}
            )
            for v in visitors:
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
    except Exception as e:
        logger.error(f" /admin/api/chat-logs error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@admin_app.route("/admin/api/visitors", methods=["GET"])
def api_visitors():
    """
    Recent visitor records with IP + geo + device info.
    GET /admin/api/visitors?limit=100
    """
    try:
        limit    = int(request.args.get("limit", 100))
        limit    = min(limit, 500)
        visitors = get_all_visitors(limit=limit)
        return jsonify({
            "status":   "success",
            "total":    len(visitors),
            "visitors": visitors,
        })
    except Exception as e:
        logger.error(f" /admin/api/visitors error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@admin_app.route("/admin/api/bookings", methods=["GET"])
def api_bookings():
    """All bookings from old + new data."""
    try:
        bookings = get_all_bookings()
        return jsonify({
            "status":   "success",
            "total":    len(bookings),
            "bookings": bookings,
        })
    except Exception as e:
        logger.error(f" /admin/api/bookings error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@admin_app.route("/admin/api/users", methods=["GET"])
def api_users():
    """Registered users (passwords excluded)."""
    try:
        users = get_all_users()
        return jsonify({
            "status": "success",
            "total":  len(users),
            "users":  users,
        })
    except Exception as e:
        logger.error(f" /admin/api/users error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


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
        "status":  "running",
        "panel":   "admin",
        "mongodb": "connected" if mongo_ok else "unavailable",
    })


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    admin_app.run(host="0.0.0.0", port=5001, debug=False, use_reloader=False)
