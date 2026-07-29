# -*- coding: utf-8 -*-
import os
import uuid
import shutil
import tempfile
from datetime import datetime
from threading import Thread

from flask import Flask, render_template, request, jsonify, session
from werkzeug.utils import secure_filename

from config import Config
from utils.loader import process_document, load_url
from utils.chatbot import get_answer
from utils.smalltalk import get_smalltalk_reply
from utils.embeddings import get_all_documents, delete_document_chunks
from utils.logger import get_logger
from utils.ip_info import get_client_ip, get_ip_info, get_browser_os

# MongoDB helpers
from db.connection import get_db
from db.models import (
    ensure_indexes,
    upsert_visitor,
    save_chat_log,
    get_active_session,
    create_session,
)

logger = get_logger(__name__)

app = Flask(__name__)

# Secret key for server-side session (visitor_id cookie)
_secret_key = os.getenv("SECRET_KEY", "")
if not _secret_key:
    logger.warning(
        "  SECRET_KEY is not set in .env — using an insecure fallback. "
        "Set a strong random SECRET_KEY in production."
    )
    _secret_key = "docmind-secret-change-in-prod"
app.secret_key = _secret_key

app.config["UPLOAD_FOLDER"] = Config.UPLOAD_FOLDER

# Create folders if they don't exist
os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
os.makedirs(Config.QDRANT_PATH, exist_ok=True)

# ── MongoDB startup ───────────────────────────────────────────────────────────
def _initialize_db_startup() -> None:
    try:
        from db.connection import get_db
        # Quick check with timeout
        get_db().command("ping", maxTimeMS=2000)
        ensure_indexes()
        logger.info(" MongoDB ready")
    except Exception as _e:
        logger.warning(f"  MongoDB unavailable at startup — will retry on first request: {_e}")

Thread(target=_initialize_db_startup, daemon=True).start()

logger.info(" DOCMIND APPLICATION STARTED")
logger.info(f"Timestamp      : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
logger.info(f"URL            : http://localhost:5000")
logger.info(f"Upload folder  : {os.path.abspath(Config.UPLOAD_FOLDER)}")
logger.info(f"Vector store   : {os.path.abspath(Config.QDRANT_PATH)}")
logger.info(f"Embedding model: {Config.EMBEDDING_MODEL}")
logger.info(f"LLM model      : {Config.LLM_MODEL}")
logger.info(f"MongoDB DB     : {Config.MONGO_DB_NAME}")
logger.info(
    f"LangSmith tracing: {' ENABLED — project=' + Config.LANGCHAIN_PROJECT if Config.LANGCHAIN_TRACING_V2 else '⏸  DISABLED'}"
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _allowed_file(filename: str) -> bool:
    """Return True if the file extension is in the supported set."""
    ext = os.path.splitext(filename)[1].lstrip(".").lower()
    return ext in Config.ALLOWED_EXTENSIONS


def _validate_file_path(path_value: str) -> None:
    """Raise ValueError if path is empty or has an unsupported extension."""
    if not path_value:
        raise ValueError("No file path provided.")
    if not _allowed_file(path_value):
        exts = ", ".join(sorted(Config.ALLOWED_EXTENSIONS)).upper()
        raise ValueError(f"Unsupported file type. Supported formats: {exts}")


def _get_or_create_visitor_id() -> str:
    """Return visitor_id from Flask session, creating one if absent."""
    if "visitor_id" not in session:
        session["visitor_id"] = str(uuid.uuid4())
    return session["visitor_id"]



def _get_or_create_session(visitor_id: str) -> str:
    """Return existing active session_id or create a new one.
    Returns empty string on any failure so callers never block."""
    try:
        existing = get_active_session(visitor_id)
        if existing:
            return existing["id"]
        return create_session(visitor_id=visitor_id)
    except Exception as exc:
        logger.warning(f"  Session management failed (non-fatal): {exc}")
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# Before-request hook — track every visitor silently
# ─────────────────────────────────────────────────────────────────────────────

@app.before_request
def before_request():
    # Skip static files and health check endpoint
    if request.path.startswith("/static") or request.path == "/health":
        return

    # ── Only track once per browser session ──────────────────────────────────
    # "visitor_tracked" is set in the Flask session cookie after the first
    # successful track, so geo-lookup + DB write only happens on the very
    # first request from each browser tab/session.
    if session.get("visitor_tracked"):
        return

    try:
        visitor_id = _get_or_create_visitor_id()
        ip = get_client_ip(request)
        ua = request.headers.get("User-Agent", "")
        browser, os_name, device_type = get_browser_os(ua)

        # Mark as tracked immediately so even if the async write fails we
        # don't retry on every subsequent request.
        session["visitor_tracked"] = True

        def _track_async(visitor_id, ip, ua, browser, os_name, device_type):
            try:
                geo = get_ip_info(ip)
                upsert_visitor(
                    visitor_id  = visitor_id,
                    ip_address  = ip,
                    country     = geo.get("country",  ""),
                    region      = geo.get("region",   ""),
                    city        = geo.get("city",     ""),
                    isp         = geo.get("isp",      ""),
                    timezone    = geo.get("timezone", ""),
                    browser     = browser,
                    os          = os_name,
                    device_type = device_type,
                    user_agent  = ua,
                )
                logger.debug(f" First-visit tracking done for visitor {visitor_id} ({ip})")
            except Exception as exc:
                logger.warning(f"  Async visitor tracking failed (non-fatal): {exc}")

        Thread(
            target=_track_async,
            args=(visitor_id, ip, ua, browser, os_name, device_type),
            daemon=True,
        ).start()
    except Exception as exc:
        logger.debug(f"before_request tracking skipped: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# User-facing routes
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/")
def home():
    return render_template("index.html")


# ---------------------------------------------------------
# LOAD DOCUMENT
# ---------------------------------------------------------

@app.route("/load-document", methods=["POST"])
def load_document():
    try:

        # ── Option 1: multipart file upload ──────────────────
        if "file" in request.files:
            file = request.files["file"]

            if file.filename == "":
                return jsonify({"status": "error", "message": "No file selected."}), 400

            filename = secure_filename(file.filename)

            if not _allowed_file(filename):
                exts = ", ".join(sorted(Config.ALLOWED_EXTENSIONS)).upper()
                return jsonify({
                    "status": "error",
                    "message": f"Unsupported file type. Supported: {exts}"
                }), 400

            save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(save_path)

            message = process_document(save_path)

            return jsonify({
                "status": "success",
                "message": message,
                "documents": get_all_documents()
            })

        # ── JSON body ─────────────────────────────────────────
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "No input received."}), 400

        # ── Option 2: absolute path ───────────────────────────
        if "path" in data:
            path = data["path"]
            try:
                _validate_file_path(path)
            except ValueError as exc:
                return jsonify({"status": "error", "message": str(exc)}), 400

            if not os.path.exists(path):
                return jsonify({"status": "error", "message": "Path not found."}), 400

            message = process_document(path)
            return jsonify({"status": "success", "message": message})

        # ── Option 3: Google Drive URL (PDF only) ─────────────
        if "url" in data:
            url = data["url"]
            if "drive.google.com" not in url:
                return jsonify({"status": "error", "message": "Invalid Google Drive URL."}), 400

            import requests as req
            try:
                if "/d/" not in url:
                    return jsonify({"status": "error", "message": "Invalid Google Drive URL."})

                file_id      = url.split("/d/")[1].split("/")[0]
                download_url = f"https://drive.google.com/uc?id={file_id}"
                response     = req.get(download_url)

                if response.status_code != 200:
                    return jsonify({
                        "status": "error",
                        "message": "The given URL is restricted."
                    }), 400

                temp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
                temp.write(response.content)
                temp.close()

                message = process_document(temp.name)
                return jsonify({"status": "success", "message": message})

            except Exception:
                return jsonify({
                    "status": "error",
                    "message": "Unable to access Google Drive file."
                }), 400

        return jsonify({
            "status": "error",
            "message": "Please provide a file upload, path, or URL."
        }), 400

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ---------------------------------------------------------
# LOAD URL
# ---------------------------------------------------------

@app.route("/load-url", methods=["POST"])
def load_url_route():
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

        logger.info(f" URL ingestion requested: {url}")
        message = load_url(url)

        return jsonify({
            "status": "success",
            "message": message,
            "documents": get_all_documents()
        })

    except ValueError as e:
        logger.warning(f"  URL scrape quality check failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        logger.error(f" URL ingestion error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ---------------------------------------------------------
# DOCUMENTS — list all ingested documents
# ---------------------------------------------------------

@app.route("/documents", methods=["GET"])
def documents():
    try:
        docs = get_all_documents()
        return jsonify({"status": "success", "documents": docs, "total": len(docs)})
    except Exception as e:
        logger.error(f" Error fetching documents: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ---------------------------------------------------------
# DELETE DOCUMENT  (admin only — delegates to shared helpers)
# ---------------------------------------------------------

@app.route("/admin/delete-document", methods=["POST"])
def delete_document():
    try:
        data = request.get_json()
        if not data or not data.get("filename"):
            return jsonify({"status": "error", "message": "filename is required."}), 400

        filename = data["filename"]

        # Check it exists in the registry first
        from utils.embeddings import _load_registry, _save_registry
        records  = _load_registry()
        matching = [r for r in records if r.get("filename") == filename]

        if not matching:
            return jsonify({
                "status":  "error",
                "message": f"'{filename}' not found in knowledge base."
            }), 404

        record = matching[0]

        # Remove vectors from Qdrant
        deleted = delete_document_chunks(filename)
        logger.info(f"  Removed {deleted} vector(s) for '{filename}' from Qdrant")

        # Remove from registry
        _save_registry([r for r in records if r.get("filename") != filename])

        # Remove physical file if it still exists
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


# ---------------------------------------------------------
# CHAT  — core endpoint with MongoDB persistence
# ---------------------------------------------------------

@app.route("/chat", methods=["POST"])
def chat():
    try:
        logger.info("Incoming request to /chat endpoint")
        data = request.get_json()

        if not data:
            logger.warning("No data received in /chat request")
            return jsonify({"status": "error", "message": "Question is required."}), 400

        question = data.get("question")
        if not question:
            logger.warning("Empty question received")
            return jsonify({"status": "error", "message": "Question cannot be empty."}), 400

        # ── Visitor + session tracking ────────────────────────
        visitor_id = session.get("visitor_id", "")

        # ── Small-talk intercept ──────────────────────────────
        # Checked BEFORE any DB/LLM work so greetings return instantly.
        smalltalk_reply = get_smalltalk_reply(question)
        if smalltalk_reply:
            logger.info(" Small-talk detected — skipping LLM")

            # Persist to MongoDB in background — never block the response
            def _save_smalltalk(visitor_id, session_id, question, answer):
                try:
                    save_chat_log(
                        question      = question,
                        answer        = answer,
                        visitor_id    = visitor_id,
                        session_id    = session_id,
                        response_type = "smalltalk",
                        found         = 1,
                    )
                except Exception as exc:
                    logger.warning(f"  Chat log save failed (non-fatal): {exc}")

            session_id = session.get("session_id", "")
            Thread(
                target=_save_smalltalk,
                args=(visitor_id, session_id, question, smalltalk_reply),
                daemon=True,
            ).start()

            return jsonify({"status": "success", "answer": smalltalk_reply})

        # ── Session tracking (only needed for RAG path) ───────
        session_id = _get_or_create_session(visitor_id) if visitor_id else ""

        # ── Conversation history ──────────────────────────────
        history = []
        if Config.CONVERSATION_HISTORY:
            raw_history = data.get("history", [])
            limit   = Config.CONVERSATION_HISTORY_LIMIT
            history = raw_history[-limit:] if len(raw_history) > limit else raw_history
            logger.info(
                f"History: ENABLED | received={len(raw_history)} | "
                f"used={len(history)} | limit={limit}"
            )
        else:
            logger.info("Conversation history: DISABLED")

        answer = get_answer(
            question,
            history  = history,
            metadata = {
                "source":   "user_chat",
                "endpoint": "/chat",
                "app":      "main",
            } if Config.LANGCHAIN_TRACING_V2 else None,
        )

        # ── Persist to MongoDB (background — never block the response) ──
        def _save_rag_log(visitor_id, session_id, question, answer):
            try:
                save_chat_log(
                    question      = question,
                    answer        = answer,
                    visitor_id    = visitor_id,
                    session_id    = session_id,
                    response_type = "rag",
                    found         = 1,
                )
                logger.debug(" Chat log saved to MongoDB")
            except Exception as exc:
                logger.warning(f"  Chat log save failed (non-fatal): {exc}")

        Thread(
            target=_save_rag_log,
            args=(visitor_id, session_id, question, answer),
            daemon=True,
        ).start()

        logger.info("Answer generated successfully")
        return jsonify({"status": "success", "answer": answer})

    except Exception as e:
        logger.error(f" Error in /chat endpoint: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ---------------------------------------------------------
# HEALTH CHECK
# ---------------------------------------------------------

@app.route("/health")
def health():
    mongo_ok = False
    try:
        get_db().command("ping")
        mongo_ok = True
    except Exception:
        pass
    return jsonify({
        "status":  "running",
        "mongodb": "connected" if mongo_ok else "unavailable",
    })


# ---------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
