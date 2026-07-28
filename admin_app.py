"""
Admin Panel — standalone Flask app on port 5001.

Responsibilities:
  - Serve the admin UI  (GET  /admin/)
  - Accept file uploads (POST /admin/load-document)
  - List ingested docs  (GET  /admin/documents)
  - Delete a document   (POST /admin/delete-document)

All document processing is delegated to the same shared utilities
(utils/loader.py, utils/embeddings.py) that the main chat app uses,
so both apps share a single FAISS vector store and registry.
"""

import os
import json
import shutil
from datetime import datetime

from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename

from config import Config
from utils.loader import process_document
from utils.embeddings import get_all_documents, delete_document_chunks
from utils.logger import get_logger

logger = get_logger(__name__)

# ── Flask setup ───────────────────────────────────────────────────────────────
admin_app = Flask(
    __name__,
    template_folder="templates",   # shared templates/
    static_folder="static",        # shared static/
)

admin_app.config["UPLOAD_FOLDER"] = Config.UPLOAD_FOLDER

os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
os.makedirs(Config.QDRANT_PATH, exist_ok=True)

logger.info("🛡️  ADMIN PANEL STARTED")
logger.info(f"Timestamp    : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
logger.info(f"Upload folder: {os.path.abspath(Config.UPLOAD_FOLDER)}")
logger.info(f"Vector store : {os.path.abspath(Config.QDRANT_PATH)}")
logger.info(
    f"LangSmith tracing: {'✅ ENABLED — project=' + Config.LANGCHAIN_PROJECT if Config.LANGCHAIN_TRACING_V2 else '⏸️  DISABLED'}"
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _allowed_file(filename: str) -> bool:
    ext = os.path.splitext(filename)[1].lstrip(".").lower()
    return ext in Config.ALLOWED_EXTENSIONS


# ── Routes ────────────────────────────────────────────────────────────────────

@admin_app.route("/admin/")
@admin_app.route("/admin")
def admin_home():
    return render_template("admin.html")


# ---------------------------------------------------------
# LOAD DOCUMENT  (multipart upload)
# ---------------------------------------------------------

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
        logger.info(f"📥 Admin uploaded: {filename}")

        if Config.LANGCHAIN_TRACING_V2:
            # Wrap in a LangSmith traceable context so this upload
            # appears as a named top-level run in the dashboard
            from langsmith import trace as ls_trace
            with ls_trace(
                name=f"admin_ingest:{filename}",
                run_type="chain",
                project_name=Config.LANGCHAIN_PROJECT,
                tags=["admin", "ingestion", "docmind"],
                metadata={
                    "filename": filename,
                    "source": "admin_panel",
                    "endpoint": "/admin/load-document",
                    "app": "admin",
                },
            ):
                message = process_document(save_path)
        else:
            message = process_document(save_path)

        return jsonify({
            "status": "success",
            "message": message,
            "documents": get_all_documents()
        })

    except Exception as e:
        logger.error(f"❌ Admin upload error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ---------------------------------------------------------
# DOCUMENTS — list all ingested documents
# ---------------------------------------------------------

@admin_app.route("/admin/documents", methods=["GET"])
def admin_documents():
    try:
        docs = get_all_documents()
        return jsonify({"status": "success", "documents": docs, "total": len(docs)})
    except Exception as e:
        logger.error(f"❌ Error fetching documents: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ---------------------------------------------------------
# DELETE DOCUMENT
# ---------------------------------------------------------

@admin_app.route("/admin/delete-document", methods=["POST"])
def admin_delete_document():
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
# HEALTH CHECK
# ---------------------------------------------------------

@admin_app.route("/admin/health")
def admin_health():
    return jsonify({"status": "running", "panel": "admin"})


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    admin_app.run(host="0.0.0.0", port=5001, debug=True)
