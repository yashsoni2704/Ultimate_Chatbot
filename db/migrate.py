"""
db/migrate.py
~~~~~~~~~~~~~
One-time migration script — imports all data from the old Ultimate_Chatbot
MongoDB collections into the new unified schema used by this project.

SAFE TO RUN MULTIPLE TIMES:
  Every insert uses update_one(..., upsert=True) keyed on the document's
  original `id` field.  Re-running will never create duplicates.

OLD COLLECTIONS  →  NEW COLLECTIONS
  visitors        →  visitors        (kept as-is, updated_at added)
  users           →  users           (kept as-is)
  chats           →  chat_logs       (merged — old chats become chat_logs)
  chat_logs       →  chat_logs       (merged with chats, deduped by id)
  chat_sessions   →  chat_sessions   (kept as-is)
  bookings        →  bookings        (kept as-is)
  otp_codes       →  otp_codes       (kept as-is)

Run with:
  python -m db.migrate
  — or —
  python db/migrate.py
"""

from __future__ import annotations

import sys
import os

# Allow running as a standalone script from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from pymongo import MongoClient, UpdateOne
from config import Config
from utils.logger import get_logger

logger = get_logger("migrate")

# ── Connection ────────────────────────────────────────────────────────────────
# Both old and new point at the same MongoDB instance / same database.
# The migration simply normalises documents in place and ensures every
# field expected by the new schema is present.

SOURCE_URI  = "mongodb://localhost:27017/"
SOURCE_DB   = "Ultimate_Chatbot"   # OLD database (also the new one here)

client = MongoClient(SOURCE_URI, serverSelectionTimeoutMS=5000)
db     = client[SOURCE_DB]


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _bulk_upsert(collection_name: str, docs: list[dict], key: str = "id") -> tuple[int, int]:
    """
    Upsert *docs* into *collection_name* keyed on *key*.
    Returns (inserted, updated) counts.
    """
    if not docs:
        return 0, 0

    col = db[collection_name]
    ops = []
    for doc in docs:
        # Remove internal MongoDB _id so we don't conflict
        doc.pop("_id", None)
        ops.append(
            UpdateOne(
                {key: doc[key]},
                {"$setOnInsert": doc},   # only write if truly new
                upsert=True,
            )
        )

    result = col.bulk_write(ops, ordered=False)
    inserted = result.upserted_count
    # matched - upserted = docs that already existed (no-op)
    matched  = result.matched_count
    return inserted, matched


# ════════════════════════════════════════════════════════════════════════════
# STEP 1 — visitors
# ════════════════════════════════════════════════════════════════════════════

def migrate_visitors() -> None:
    logger.info("── Migrating visitors ──────────────────────────")
    docs = list(db["visitors"].find({}))
    for d in docs:
        d.pop("_id", None)
        # Ensure new schema fields exist
        d.setdefault("updated_at", d.get("created_at", _now()))

    inserted, matched = _bulk_upsert("visitors", docs, key="visitor_id")
    logger.info(f"   visitors  → new: {inserted}  already existed: {matched}")


# ════════════════════════════════════════════════════════════════════════════
# STEP 2 — users
# ════════════════════════════════════════════════════════════════════════════

def migrate_users() -> None:
    logger.info("── Migrating users ─────────────────────────────")
    docs = list(db["users"].find({}))
    for d in docs:
        d.pop("_id", None)

    inserted, matched = _bulk_upsert("users", docs, key="id")
    logger.info(f"   users     → new: {inserted}  already existed: {matched}")


# ════════════════════════════════════════════════════════════════════════════
# STEP 3 — chat_logs  (merge old 'chats' + old 'chat_logs')
# ════════════════════════════════════════════════════════════════════════════

def migrate_chat_logs() -> None:
    logger.info("── Migrating chat_logs (merging chats + chat_logs) ──")

    # ── Old 'chats' collection ─────────────────────────────────────────
    old_chats = list(db["chats"].find({}))
    normalised_chats: list[dict] = []
    for d in old_chats:
        d.pop("_id", None)
        # Map old schema → new unified schema
        normalised_chats.append({
            "id":            d.get("id", ""),
            "visitor_id":    d.get("visitor_id", ""),
            "user_id":       d.get("user_id", ""),
            "user_email":    d.get("user_email", ""),
            "user_name":     d.get("user_name", ""),
            "session_id":    d.get("session_id", ""),
            "query":         d.get("question", d.get("query", "")),
            "answer":        d.get("answer", ""),
            "response_type": d.get("response_type", "faq"),
            "source_doc":    d.get("source_doc", ""),
            "found":         d.get("found", 1),
            "created_at":    d.get("created_at", _now()),
            "migrated_from": "chats",
        })

    # ── Old 'chat_logs' collection ─────────────────────────────────────
    old_logs = list(db["chat_logs"].find({}))
    normalised_logs: list[dict] = []
    for d in old_logs:
        d.pop("_id", None)
        normalised_logs.append({
            "id":            d.get("id", ""),
            "visitor_id":    d.get("visitor_id", ""),
            "user_id":       d.get("user_id", ""),
            "user_email":    d.get("user_email", ""),
            "user_name":     d.get("user_name", ""),
            "session_id":    d.get("session_id", ""),
            "query":         d.get("query", d.get("question", "")),
            "answer":        d.get("answer", ""),
            "response_type": d.get("response_type", "faq"),
            "source_doc":    d.get("source_doc", ""),
            "found":         d.get("found", 1),
            "created_at":    d.get("created_at", _now()),
            "migrated_from": "chat_logs",
        })

    all_docs = normalised_chats + normalised_logs

    # Deduplicate by id (prefer chat_logs entry if both exist)
    seen: dict[str, dict] = {}
    for doc in all_docs:
        doc_id = doc.get("id", "")
        if doc_id and doc_id not in seen:
            seen[doc_id] = doc
        elif doc_id and doc.get("migrated_from") == "chat_logs":
            seen[doc_id] = doc   # chat_logs wins

    deduped = list(seen.values())
    inserted, matched = _bulk_upsert("chat_logs", deduped, key="id")
    logger.info(f"   chat_logs → new: {inserted}  already existed: {matched}  (from {len(old_chats)} chats + {len(old_logs)} chat_logs)")


# ════════════════════════════════════════════════════════════════════════════
# STEP 4 — chat_sessions
# ════════════════════════════════════════════════════════════════════════════

def migrate_chat_sessions() -> None:
    logger.info("── Migrating chat_sessions ─────────────────────")
    docs = list(db["chat_sessions"].find({}))
    for d in docs:
        d.pop("_id", None)
        d.setdefault("visitor_id", "")

    inserted, matched = _bulk_upsert("chat_sessions", docs, key="id")
    logger.info(f"   sessions  → new: {inserted}  already existed: {matched}")


# ════════════════════════════════════════════════════════════════════════════
# STEP 5 — bookings
# ════════════════════════════════════════════════════════════════════════════

def migrate_bookings() -> None:
    logger.info("── Migrating bookings ──────────────────────────")
    docs = list(db["bookings"].find({}))
    for d in docs:
        d.pop("_id", None)

    inserted, matched = _bulk_upsert("bookings", docs, key="id")
    logger.info(f"   bookings  → new: {inserted}  already existed: {matched}")


# ════════════════════════════════════════════════════════════════════════════
# STEP 6 — otp_codes
# ════════════════════════════════════════════════════════════════════════════

def migrate_otp_codes() -> None:
    logger.info("── Migrating otp_codes ─────────────────────────")
    docs = list(db["otp_codes"].find({}))
    for d in docs:
        d.pop("_id", None)

    inserted, matched = _bulk_upsert("otp_codes", docs, key="id")
    logger.info(f"   otp_codes → new: {inserted}  already existed: {matched}")


# ════════════════════════════════════════════════════════════════════════════
# VERIFICATION — print final counts
# ════════════════════════════════════════════════════════════════════════════

def verify() -> None:
    logger.info("")
    logger.info("════════════════════════════════════════")
    logger.info("  MIGRATION VERIFICATION — FINAL COUNTS ")
    logger.info("════════════════════════════════════════")
    collections = ["visitors", "users", "chat_logs", "chat_sessions", "bookings", "otp_codes"]
    for col in collections:
        count = db[col].count_documents({})
        logger.info(f"  {col:<20} : {count} documents")
    logger.info("════════════════════════════════════════")


# ════════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════════

def run_migration() -> None:
    logger.info("")
    logger.info("╔══════════════════════════════════════════╗")
    logger.info("║   Ultimate_Chatbot — Data Migration      ║")
    logger.info(f"║   Started: {_now()}     ║")
    logger.info("╚══════════════════════════════════════════╝")
    logger.info("")

    migrate_visitors()
    migrate_users()
    migrate_chat_logs()
    migrate_chat_sessions()
    migrate_bookings()
    migrate_otp_codes()
    verify()

    logger.info("")
    logger.info(" Migration complete — all old data preserved.")
    client.close()


if __name__ == "__main__":
    run_migration()
