# -*- coding: utf-8 -*-
import os
import uuid
import shutil
import tempfile
import time
from datetime import datetime
from threading import Thread

from flask import Flask, render_template, request, jsonify, session
from flask_socketio import SocketIO, emit
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
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading", logger=False, engineio_logger=False)

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


def _get_visitor_id() -> str:
    """Return visitor_id from Flask session, or empty string if none set.
    Never auto-generates — UUID creation is owned exclusively by /init-session
    so that localStorage is always the single source of truth."""
    return session.get("visitor_id", "")



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
    # "visitor_tracked" is set after the first successful geo-lookup + DB write.
    # We ONLY track if the session already has a visitor_id set by /init-session.
    # We never auto-generate a UUID here — that is owned by /init-session alone.
    if session.get("visitor_tracked"):
        return

    visitor_id = session.get("visitor_id", "")
    if not visitor_id:
        # No UUID yet — /init-session hasn't been called, nothing to track
        return

    try:
        ip = get_client_ip(request)
        ua = request.headers.get("User-Agent", "")
        browser, os_name, device_type = get_browser_os(ua)

        # Mark tracked immediately so geo-lookup never runs twice
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
        visitor_id = session.get("visitor_id", "")        # ── Small-talk intercept ──────────────────────────────
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

        with _chat_in_flight_lock:
            _chat_in_flight = True
        _t_start = time.time()
        try:
            answer = get_answer(
                question,
                history  = history,
                metadata = {
                    "source":   "user_chat",
                    "endpoint": "/chat",
                    "app":      "main",
                } if Config.LANGCHAIN_TRACING_V2 else None,
            )
        finally:
            with _chat_in_flight_lock:
                _chat_in_flight = False
        elapsed_ms = int((time.time() - _t_start) * 1000)

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
        return jsonify({"status": "success", "answer": answer, "elapsed_ms": elapsed_ms})

    except Exception as e:
        logger.error(f" Error in /chat endpoint: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ---------------------------------------------------------
# INIT SESSION — called by frontend on every page load
# Accepts an optional visitor_id from localStorage.
# Returns the visitor_id and any stored name so the UI
# can greet returning users immediately.
# ---------------------------------------------------------

@app.route("/init-session", methods=["POST"])
def init_session():
    try:
        data = request.get_json() or {}
        client_uuid = data.get("visitor_id", "").strip()

        if client_uuid:
            # Returning visitor — localStorage had a UUID, trust it
            visitor_id = client_uuid
        else:
            # Brand-new visitor — generate a fresh UUID
            visitor_id = str(uuid.uuid4())
            # Clear tracked flag so geo-lookup runs for this new identity
            session.pop("visitor_tracked", None)

        # Always write the authoritative UUID into the Flask session
        # so /chat and other endpoints can read it without the client
        # having to send it every time.
        session["visitor_id"] = visitor_id

        # Fetch any existing profile (name, email, phone)
        from db.models import get_visitor
        visitor = get_visitor(visitor_id) or {}

        return jsonify({
            "status":     "success",
            "visitor_id": visitor_id,
            "name":       visitor.get("name") or "",
            "email":      visitor.get("email") or "",
        })
    except Exception as e:
        logger.error(f" /init-session error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ---------------------------------------------------------
# UPDATE VISITOR — saves name / email / phone from the
# optional lead-capture form shown after 2-3 questions.
# ---------------------------------------------------------

@app.route("/update-visitor", methods=["POST"])
def update_visitor():
    try:
        data = request.get_json() or {}
        visitor_id = data.get("visitor_id", "").strip() or session.get("visitor_id", "")

        if not visitor_id:
            return jsonify({"status": "error", "message": "visitor_id is required."}), 400

        name  = (data.get("name",  "") or "").strip()
        email = (data.get("email", "") or "").strip()
        phone = (data.get("phone", "") or "").strip()

        if not name and not email and not phone:
            return jsonify({"status": "error", "message": "At least one field is required."}), 400

        upsert_visitor(
            visitor_id = visitor_id,
            name       = name  or None,
            email      = email or None,
            phone      = phone or None,
        )
        logger.info(f" Visitor profile updated: {visitor_id} name={name!r}")
        return jsonify({"status": "success", "name": name, "email": email})
    except Exception as e:
        logger.error(f" /update-visitor error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ---------------------------------------------------------
# VISITOR INFO — lightweight GET for returning users
# ---------------------------------------------------------

@app.route("/visitor-info", methods=["GET"])
def visitor_info():
    try:
        visitor_id = request.args.get("visitor_id", "").strip() or session.get("visitor_id", "")
        if not visitor_id:
            return jsonify({"status": "error", "message": "visitor_id is required."}), 400

        from db.models import get_visitor
        visitor = get_visitor(visitor_id) or {}
        return jsonify({
            "status":     "success",
            "visitor_id": visitor_id,
            "name":       visitor.get("name")  or "",
            "email":      visitor.get("email") or "",
        })
    except Exception as e:
        logger.error(f" /visitor-info error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ---------------------------------------------------------

# ---------------------------------------------------------
# CLIENT CONFIG — exposes safe frontend settings
# ---------------------------------------------------------

@app.route("/client-config")
def client_config():
    from utils.transcribe import read_active_provider, VALID_PROVIDERS
    provider = read_active_provider()
    return jsonify({
        "mic_silence_timeout": Config.MIC_SILENCE_TIMEOUT,
        "stt_provider":        provider,
        "stt_provider_label":  VALID_PROVIDERS.get(provider, provider),
    })


# ---------------------------------------------------------
# STT PROVIDER — read active / switch (idle-safe)
# ---------------------------------------------------------

# Track whether a /chat request is currently in-flight.
# Set to True when /chat starts, False when it returns.
# The admin switch endpoint waits for this to be False.
_chat_in_flight = False
_chat_in_flight_lock = threading.Lock()


@app.route("/stt/provider", methods=["GET"])
def stt_get_provider():
    """Return the currently active STT provider."""
    from utils.transcribe import read_active_provider, VALID_PROVIDERS
    provider = read_active_provider()
    return jsonify({
        "status":   "success",
        "provider": provider,
        "label":    VALID_PROVIDERS.get(provider, provider),
        "all":      [{"key": k, "label": v} for k, v in VALID_PROVIDERS.items()],
    })


@app.route("/stt/provider", methods=["POST"])
def stt_set_provider():
    """
    Switch STT provider.  Waits up to 10 s for any in-flight /chat
    request to finish before writing the new provider, so the switch
    is always idle-safe.
    """
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

    # Wait for idle (max 10 s)
    deadline = time.time() + 10
    while time.time() < deadline:
        with _chat_in_flight_lock:
            if not _chat_in_flight:
                break
        time.sleep(0.2)

    set_active_provider(provider)
    logger.info(f"[STT] Switched to {provider} via /stt/provider")
    return jsonify({
        "status":   "success",
        "provider": provider,
        "label":    VALID_PROVIDERS[provider],
        "message":  f"STT provider switched to {VALID_PROVIDERS[provider]}.",
    })


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
# LOG VOICE INPUT — called by frontend after mic stops
# ---------------------------------------------------------

@app.route("/log-voice", methods=["POST"])
def log_voice():
    try:
        data = request.get_json() or {}
        text = (data.get("text") or "").strip()
        if not text:
            return jsonify({"status": "ok"})

        visitor_id = session.get("visitor_id", "")
        session_id = session.get("session_id", "")
        logger.info(f" [MIC] {text!r}")

        def _save(visitor_id, session_id, text):
            try:
                save_chat_log(
                    question      = text,
                    answer        = "",
                    visitor_id    = visitor_id,
                    session_id    = session_id,
                    response_type = "voice_input",
                    found         = 0,
                )
            except Exception as exc:
                logger.warning(f"  Voice log save failed: {exc}")

        Thread(target=_save, args=(visitor_id, session_id, text), daemon=True).start()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ---------------------------------------------------------
# SOCKET.IO — real-time mic transcription via AssemblyAI
# ---------------------------------------------------------

# One TranscribeSession per socket connection (keyed by sid)
_transcribe_sessions = {}

@socketio.on("connect", namespace="/transcribe")
def on_transcribe_connect():
    logger.info(f" Transcribe WS connected: {request.sid}")

@socketio.on("disconnect", namespace="/transcribe")
def on_transcribe_disconnect():
    sid = request.sid
    sess = _transcribe_sessions.pop(sid, None)
    if sess:
        try:
            sess.stop()
        except Exception:
            pass
    logger.info(f" Transcribe WS disconnected: {sid}")

@socketio.on("start_transcription", namespace="/transcribe")
def on_start_transcription():
    from utils.transcribe import get_session, read_active_provider, VALID_PROVIDERS
    sid = request.sid

    # Clean up any stale session for this socket
    old = _transcribe_sessions.pop(sid, None)
    if old:
        try:
            old.stop()
        except Exception:
            pass

    provider = read_active_provider()
    logger.info(f" STT session starting: provider={provider} ({VALID_PROVIDERS.get(provider)}) sid={sid}")

    session_transcript = []

    def _on_transcript(text):
        session_transcript.append(text)
        socketio.emit("transcript", {"text": text}, namespace="/transcribe", to=sid)
        logger.info(f" [MIC] [{sid[:8]}] {text}")

    def _on_error(msg):
        logger.error(f" Transcription error [{sid[:8]}]: {msg}")
        socketio.emit("transcribe_error", {"message": msg}, namespace="/transcribe", to=sid)

    sess = get_session(on_transcript=_on_transcript, on_error=_on_error)
    sess._session_transcript = session_transcript
    sess.start()
    _transcribe_sessions[sid] = sess
    emit("transcription_started", {"status": "ok", "provider": provider, "label": VALID_PROVIDERS.get(provider, provider)})
    logger.info(f" STT session opened: {provider} for {sid}")

@socketio.on("audio_chunk", namespace="/transcribe")
def on_audio_chunk(data):
    sid  = request.sid
    sess = _transcribe_sessions.get(sid)
    if not sess:
        return
    # Socket.IO may deliver binary as bytes, bytearray, or a list of ints
    if isinstance(data, (bytes, bytearray)):
        raw = bytes(data)
    elif isinstance(data, list):
        raw = bytes(data)
    else:
        raw = data
    sess.send_audio(raw)

@socketio.on("stop_transcription", namespace="/transcribe")
def on_stop_transcription():
    sid  = request.sid
    sess = _transcribe_sessions.pop(sid, None)
    if sess:
        # Log the full voice transcript to MongoDB in background
        full_text = " ".join(getattr(sess, "_session_transcript", []))
        if full_text:
            logger.info(f" [MIC FULL] [{sid[:8]}] {full_text}")
            visitor_id = session.get("visitor_id", "")
            session_id = session.get("session_id", "")
            def _save_voice_log(visitor_id, session_id, full_text):
                try:
                    save_chat_log(
                        question      = full_text,
                        answer        = "",
                        visitor_id    = visitor_id,
                        session_id    = session_id,
                        response_type = "voice_input",
                        found         = 0,
                    )
                    logger.debug(f" Voice input logged to MongoDB for {visitor_id}")
                except Exception as exc:
                    logger.warning(f"  Voice log save failed (non-fatal): {exc}")
            Thread(target=_save_voice_log,
                   args=(visitor_id, session_id, full_text),
                   daemon=True).start()
        try:
            sess.stop()
        except Exception:
            pass
    emit("transcription_stopped", {"status": "ok"})
    logger.info(f" Transcription stopped for {sid}")


# ---------------------------------------------------------

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=False,
                 use_reloader=False, allow_unsafe_werkzeug=True)
