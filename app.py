import os
import json
import shutil
import tempfile
from datetime import datetime

from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename

from config import Config
from utils.loader import process_document
from utils.chatbot import get_answer
from utils.smalltalk import get_smalltalk_reply
from utils.embeddings import get_all_documents, delete_document_chunks
from utils.logger import get_logger

logger = get_logger(__name__)

app = Flask(__name__)

app.config["UPLOAD_FOLDER"] = Config.UPLOAD_FOLDER

# Create folders if they don't exist
os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
os.makedirs(Config.QDRANT_PATH, exist_ok=True)

logger.info("🚀 DOCMIND APPLICATION STARTED")
logger.info(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
logger.info(f"Upload folder: {os.path.abspath(Config.UPLOAD_FOLDER)}")
logger.info(f"Vector store path: {os.path.abspath(Config.QDRANT_PATH)}")
logger.info(f"Embedding model: {Config.EMBEDDING_MODEL}")
logger.info(f"LLM model: {Config.LLM_MODEL}")
logger.info(
    f"LangSmith tracing: {'✅ ENABLED — project=' + Config.LANGCHAIN_PROJECT if Config.LANGCHAIN_TRACING_V2 else '⏸️  DISABLED'}"
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


# ─────────────────────────────────────────────────────────────────────────────
# User-facing routes
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/")
def home():
    return render_template("index.html")


# ---------------------------------------------------------
# LOAD DOCUMENT  (called by admin panel — all file types)
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

                file_id = url.split("/d/")[1].split("/")[0]
                download_url = f"https://drive.google.com/uc?id={file_id}"
                response = req.get(download_url)

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
# DOCUMENTS — list all ingested documents
# ---------------------------------------------------------

@app.route("/documents", methods=["GET"])
def documents():
    try:
        docs = get_all_documents()
        return jsonify({"status": "success", "documents": docs, "total": len(docs)})
    except Exception as e:
        logger.error(f"❌ Error fetching documents: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ---------------------------------------------------------
# DELETE DOCUMENT  (admin only)
# ---------------------------------------------------------

@app.route("/admin/delete-document", methods=["POST"])
def delete_document():
    """
    Remove a document from the knowledge base:
      1. Delete its chunks from Qdrant (surgical — other docs untouched)
      2. Remove its entry from registry.json
      3. Delete the uploaded file from disk

    Body: { "filename": "report.pdf" }
    """
    try:
        data = request.get_json()
        if not data or not data.get("filename"):
            return jsonify({"status": "error", "message": "filename is required."}), 400

        filename = data["filename"]
        registry_path = os.path.join(Config.QDRANT_PATH, "registry.json")

        if not os.path.exists(registry_path):
            return jsonify({"status": "error", "message": "Registry not found."}), 404

        with open(registry_path, "r", encoding="utf-8") as f:
            records = json.load(f)

        matching = [r for r in records if r.get("filename") == filename]
        if not matching:
            return jsonify({
                "status": "error",
                "message": f"'{filename}' not found in knowledge base."
            }), 404

        record = matching[0]

        # ── 1. Delete chunks from Qdrant ───────────────────────────────────
        deleted = delete_document_chunks(filename)
        logger.info(f"🗑️  Removed {deleted} vector(s) for '{filename}' from Qdrant")

        # ── 2. Remove from registry ────────────────────────────────────────
        remaining = [r for r in records if r.get("filename") != filename]
        with open(registry_path, "w", encoding="utf-8") as f:
            json.dump(remaining, f, indent=2, ensure_ascii=False)

        # ── 3. Delete the uploaded file if it still exists ─────────────────
        file_path = record.get("path", "")
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"🗑️  Deleted file: {file_path}")

        logger.info(f"✅ '{filename}' fully removed from knowledge base")
        return jsonify({
            "status": "success",
            "message": f"'{filename}' removed from knowledge base.",
            "documents": get_all_documents()
        })

    except Exception as e:
        logger.error(f"❌ Error deleting document: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ---------------------------------------------------------
# CHAT
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

        # ── Small-talk intercept ──────────────────────────────
        smalltalk_reply = get_smalltalk_reply(question)
        if smalltalk_reply:
            logger.info("💬 Small-talk detected — skipping LLM")
            return jsonify({"status": "success", "answer": smalltalk_reply})

        # ── Conversation history ──────────────────────────────
        history = []
        if Config.CONVERSATION_HISTORY:
            raw_history = data.get("history", [])
            limit = Config.CONVERSATION_HISTORY_LIMIT
            history = raw_history[-limit:] if len(raw_history) > limit else raw_history
            logger.info(
                f"History: ENABLED | received={len(raw_history)} | "
                f"used={len(history)} | limit={limit}"
            )
        else:
            logger.info("Conversation history: DISABLED")

        answer = get_answer(
            question,
            history=history,
            metadata={
                "source": "user_chat",
                "endpoint": "/chat",
                "app": "main",
            } if Config.LANGCHAIN_TRACING_V2 else None,
        )
        logger.info("Answer generated successfully")
        return jsonify({"status": "success", "answer": answer})

    except Exception as e:
        logger.error(f"❌ Error in /chat endpoint: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ---------------------------------------------------------
# HEALTH CHECK
# ---------------------------------------------------------

@app.route("/health")
def health():
    return jsonify({"status": "running"})


# ---------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
