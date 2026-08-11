"""
db/models.py
~~~~~~~~~~~~
All collection-level helpers for the Ultimate_Chatbot database.

Collections managed here:
  • visitors    — anonymous + identified visitor profiles (with IP data)
  • users       — registered accounts
  • chat_logs   — every Q&A turn ever recorded (merged from old chats + chat_logs)
  • chat_sessions — conversation context windows
  • bookings    — test-drive / service slot bookings
  • otp_codes   — 2-FA OTP records

Each function is intentionally thin — pure MongoDB operations with
no business logic.  All callers (app.py, admin_app.py) use these
helpers so the DB schema stays in one place.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection

from db.connection import get_db
from utils.logger import get_logger

logger = get_logger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

def _new_id() -> str:
    return str(uuid.uuid4())

def _col(name: str) -> Collection:
    return get_db()[name]


# ════════════════════════════════════════════════════════════════════════════
# INDEXES  — called once at app startup
# ════════════════════════════════════════════════════════════════════════════

def ensure_indexes() -> None:
    """
    Create all necessary indexes.  Safe to call multiple times —
    MongoDB silently ignores duplicate index definitions.
    """
    try:
        # visitors
        _col("visitors").create_index([("visitor_id", ASCENDING)], unique=True)
        _col("visitors").create_index([("ip_address", ASCENDING)])
        _col("visitors").create_index([("email", ASCENDING)])

        # users
        _col("users").create_index([("id", ASCENDING)], unique=True)
        _col("users").create_index([("email", ASCENDING)], unique=True)

        # chat_logs
        _col("chat_logs").create_index([("id", ASCENDING)], unique=True)
        _col("chat_logs").create_index([("visitor_id", ASCENDING)])
        _col("chat_logs").create_index([("user_id", ASCENDING)])
        _col("chat_logs").create_index([("session_id", ASCENDING)])
        _col("chat_logs").create_index([("created_at", DESCENDING)])

        # chat_sessions
        _col("chat_sessions").create_index([("id", ASCENDING)], unique=True)
        _col("chat_sessions").create_index([("visitor_id", ASCENDING)])
        _col("chat_sessions").create_index([("user_id", ASCENDING)])

        # bookings
        _col("bookings").create_index([("id", ASCENDING)], unique=True)
        _col("bookings").create_index([("user_id", ASCENDING)])

        # otp_codes
        _col("otp_codes").create_index([("id", ASCENDING)], unique=True)
        _col("otp_codes").create_index([("email", ASCENDING)])
        _col("otp_codes").create_index([("expires_at", ASCENDING)])

        # chat_feedback
        _col("chat_feedback").create_index([("id", ASCENDING)], unique=True)
        _col("chat_feedback").create_index([("visitor_id", ASCENDING)])
        _col("chat_feedback").create_index([("chat_log_id", ASCENDING)])
        _col("chat_feedback").create_index([("feedback", ASCENDING)])
        _col("chat_feedback").create_index([("created_at", DESCENDING)])

        # dissatisfied_users
        _col("dissatisfied_users").create_index([("id", ASCENDING)], unique=True)
        _col("dissatisfied_users").create_index([("visitor_id", ASCENDING)], unique=True)
        _col("dissatisfied_users").create_index([("status", ASCENDING)])
        _col("dissatisfied_users").create_index([("created_at", DESCENDING)])

        logger.info(" MongoDB indexes ensured")
    except Exception as exc:
        logger.error(f" Index creation failed: {exc}")


# ════════════════════════════════════════════════════════════════════════════
# VISITORS
# ════════════════════════════════════════════════════════════════════════════

def upsert_visitor(
    visitor_id:  str,
    ip_address:  str  = "",
    country:     str  = "",
    region:      str  = "",
    city:        str  = "",
    isp:         str  = "",
    timezone:    str  = "",
    browser:     str  = "",
    os:          str  = "",
    device_type: str  = "",
    user_agent:  str  = "",
    name:        str | None = None,
    email:       str | None = None,
    phone:       str | None = None,
) -> dict:
    """
    Insert a new visitor or update last_visit + geo/device fields on revisit.
    Returns the full visitor document.
    """
    now = _now()
    col = _col("visitors")

    existing = col.find_one({"visitor_id": visitor_id})

    if existing:
        update: dict[str, Any] = {
            "last_visit": now,
            "updated_at": now,
        }
        # Only overwrite geo/device if we have real data
        if ip_address:  update["ip_address"]  = ip_address
        if country:     update["country"]      = country
        if region:      update["region"]       = region
        if city:        update["city"]         = city
        if isp:         update["isp"]          = isp
        if timezone:    update["timezone"]     = timezone
        if browser:     update["browser"]      = browser
        if os:          update["os"]           = os
        if device_type: update["device_type"]  = device_type
        if user_agent:  update["user_agent"]   = user_agent
        if name:        update["name"]         = name
        if email:       update["email"]        = email
        if phone:       update["phone"]        = phone

        col.update_one({"visitor_id": visitor_id}, {"$set": update})
        logger.debug(f" Visitor updated: {visitor_id}")
        return col.find_one({"visitor_id": visitor_id})

    else:
        doc = {
            "visitor_id":  visitor_id,
            "name":        name,
            "email":       email,
            "phone":       phone,
            "ip_address":  ip_address,
            "country":     country,
            "region":      region,
            "city":        city,
            "isp":         isp,
            "timezone":    timezone,
            "browser":     browser,
            "os":          os,
            "device_type": device_type,
            "user_agent":  user_agent,
            "first_visit": now,
            "last_visit":  now,
            "created_at":  now,
            "updated_at":  now,
        }
        col.insert_one(doc)
        logger.debug(f" New visitor created: {visitor_id}")
        return doc


def get_visitor(visitor_id: str) -> dict | None:
    return _col("visitors").find_one({"visitor_id": visitor_id}, {"_id": 0})


def get_all_visitors(limit: int = 200) -> list[dict]:
    return list(
        _col("visitors")
        .find({}, {"_id": 0})
        .sort("last_visit", DESCENDING)
        .limit(limit)
    )


# ════════════════════════════════════════════════════════════════════════════
# USERS
# ════════════════════════════════════════════════════════════════════════════

def get_user_by_email(email: str) -> dict | None:
    return _col("users").find_one({"email": email}, {"_id": 0})


def get_user_by_id(user_id: str) -> dict | None:
    return _col("users").find_one({"id": user_id}, {"_id": 0})


def get_all_users() -> list[dict]:
    return list(_col("users").find({}, {"_id": 0, "password_hash": 0}))


def create_user(email: str, password_hash: str, full_name: str = "") -> dict:
    doc = {
        "id":            _new_id(),
        "email":         email,
        "password_hash": password_hash,
        "full_name":     full_name,
        "created_at":    _now(),
    }
    _col("users").insert_one(doc)
    logger.info(f" New user created: {email}")
    return {k: v for k, v in doc.items() if k != "password_hash"}


# ════════════════════════════════════════════════════════════════════════════
# CHAT LOGS
# ════════════════════════════════════════════════════════════════════════════

def save_chat_log(
    question:      str,
    answer:        str,
    visitor_id:    str  = "",
    user_id:       str  = "",
    user_email:    str  = "",
    user_name:     str  = "",
    session_id:    str  = "",
    response_type: str  = "rag",       # "rag" | "faq" | "smalltalk"
    source_doc:    str  = "",          # which document answered this
    found:         int  = 1,
) -> str:
    """Persist one Q&A turn. Returns the new document id."""
    doc_id = _new_id()
    doc = {
        "id":            doc_id,
        "visitor_id":    visitor_id,
        "user_id":       user_id,
        "user_email":    user_email,
        "user_name":     user_name,
        "session_id":    session_id,
        "query":         question,
        "answer":        answer,
        "response_type": response_type,
        "source_doc":    source_doc,
        "found":         found,
        "created_at":    _now(),
    }
    _col("chat_logs").insert_one(doc)
    logger.debug(f" Chat log saved: {doc_id}")
    return doc_id


def get_chat_logs(
    visitor_id: str = "",
    user_id:    str = "",
    limit:      int = 100,
) -> list[dict]:
    query: dict = {}
    if visitor_id: query["visitor_id"] = visitor_id
    if user_id:    query["user_id"]    = user_id
    return list(
        _col("chat_logs")
        .find(query, {"_id": 0})
        .sort("created_at", DESCENDING)
        .limit(limit)
    )


def get_recent_chat_logs(limit: int = 50, skip: int = 0) -> list[dict]:
    return list(
        _col("chat_logs")
        .find({}, {"_id": 0})
        .sort("created_at", DESCENDING)
        .skip(max(skip, 0))
        .limit(limit)
    )


def get_chat_stats() -> dict:
    """Return aggregate counts for admin dashboard."""
    col = _col("chat_logs")
    total        = col.count_documents({})
    rag_count    = col.count_documents({"response_type": "rag"})
    faq_count    = col.count_documents({"response_type": "faq"})
    small_count  = col.count_documents({"response_type": "smalltalk"})
    unique_vis   = len(col.distinct("visitor_id"))
    unique_users = len(col.distinct("user_id"))
    return {
        "total":          total,
        "rag":            rag_count,
        "faq":            faq_count,
        "smalltalk":      small_count,
        "unique_visitors": unique_vis,
        "unique_users":   unique_users,
    }


# ════════════════════════════════════════════════════════════════════════════
# CHAT SESSIONS
# ════════════════════════════════════════════════════════════════════════════

def create_session(visitor_id: str = "", user_id: str = "") -> str:
    """Open a new chat session. Returns the session_id."""
    session_id = _new_id()
    doc = {
        "id":           session_id,
        "visitor_id":   visitor_id,
        "user_id":      user_id,
        "context_json": "{}",
        "is_active":    1,
        "created_at":   _now(),
        "ended_at":     None,
        # Satisfaction tracking fields
        "llm_mode":     "primary",  # "primary" | "secondary"
        "question_count": 0,
        "last_satisfaction_asked": 0,
        "user_info":    None,  # {"name": "", "email": "", "phone": ""}
    }
    _col("chat_sessions").insert_one(doc)
    return session_id


def get_active_session(visitor_id: str) -> dict | None:
    return _col("chat_sessions").find_one(
        {"visitor_id": visitor_id, "is_active": 1},
        {"_id": 0},
        sort=[("created_at", DESCENDING)],
    )


def end_session(session_id: str) -> None:
    _col("chat_sessions").update_one(
        {"id": session_id},
        {"$set": {"is_active": 0, "ended_at": _now()}},
    )


def update_session_context(session_id: str, context_json: str) -> None:
    _col("chat_sessions").update_one(
        {"id": session_id},
        {"$set": {"context_json": context_json}},
    )


# ════════════════════════════════════════════════════════════════════════════
# SESSION SATISFACTION TRACKING
# ════════════════════════════════════════════════════════════════════════════

def increment_session_question_count(session_id: str) -> dict:
    """Increment question count and return updated session."""
    _col("chat_sessions").update_one(
        {"id": session_id},
        {"$inc": {"question_count": 1}},
    )
    return _col("chat_sessions").find_one({"id": session_id}, {"_id": 0})


def update_session_llm_mode(session_id: str, mode: str) -> None:
    """Switch LLM mode for this session. mode = 'primary' | 'secondary'."""
    _col("chat_sessions").update_one(
        {"id": session_id},
        {"$set": {
            "llm_mode": mode,
            "last_satisfaction_asked": 0,  # reset counter after switch
        }},
    )


def mark_satisfaction_asked(session_id: str, question_count: int) -> None:
    """Record the question count at which satisfaction was last asked."""
    _col("chat_sessions").update_one(
        {"id": session_id},
        {"$set": {"last_satisfaction_asked": question_count}},
    )


def save_session_user_info(session_id: str, name: str, email: str, phone: str) -> None:
    """Save contact form data to the session."""
    _col("chat_sessions").update_one(
        {"id": session_id},
        {"$set": {
            "user_info": {
                "name":  name,
                "email": email,
                "phone": phone,
            }
        }},
    )


def get_session_user_info(session_id: str) -> dict | None:
    """Return user_info dict if already filled, else None."""
    doc = _col("chat_sessions").find_one({"id": session_id}, {"_id": 0, "user_info": 1})
    if doc:
        return doc.get("user_info")
    return None


# ════════════════════════════════════════════════════════════════════════════
# BOOKINGS
# ════════════════════════════════════════════════════════════════════════════

def get_all_bookings() -> list[dict]:
    return list(_col("bookings").find({}, {"_id": 0}).sort("created_at", DESCENDING))


def get_bookings_by_user(user_id: str) -> list[dict]:
    return list(
        _col("bookings")
        .find({"user_id": user_id}, {"_id": 0})
        .sort("created_at", DESCENDING)
    )


def create_booking(
    user_id:       str,
    booking_date:  str,
    time_slot:     str,
    vehicle_model: str,
    status:        str = "confirmed",
) -> str:
    booking_id = _new_id()
    doc = {
        "id":            booking_id,
        "user_id":       user_id,
        "booking_date":  booking_date,
        "time_slot":     time_slot,
        "vehicle_model": vehicle_model,
        "status":        status,
        "created_at":    _now(),
    }
    _col("bookings").insert_one(doc)
    return booking_id


def update_booking_status(booking_id: str, status: str) -> None:
    _col("bookings").update_one(
        {"id": booking_id},
        {"$set": {"status": status}},
    )


# ════════════════════════════════════════════════════════════════════════════
# OTP CODES
# ════════════════════════════════════════════════════════════════════════════

def get_otp(email: str, purpose: str = "login_2fa") -> dict | None:
    return _col("otp_codes").find_one(
        {"email": email, "purpose": purpose, "used": 0},
        {"_id": 0},
        sort=[("created_at", DESCENDING)],
    )


def mark_otp_used(otp_id: str) -> None:
    _col("otp_codes").update_one({"id": otp_id}, {"$set": {"used": 1}})


# ════════════════════════════════════════════════════════════════════════════
# CHAT FEEDBACK  (like / dislike per message)
# ════════════════════════════════════════════════════════════════════════════

def save_chat_feedback(
    visitor_id:  str,
    session_id:  str,
    chat_log_id: str,
    feedback:    str,   # "like" | "dislike"
    question:    str = "",
    answer:      str = "",
) -> str:
    """
    Upsert feedback for a specific chat message.
    A visitor can change like→dislike or vice versa — only one record per
    (visitor_id, chat_log_id) pair is kept.
    Returns the feedback document id.
    """
    now = _now()
    col = _col("chat_feedback")

    existing = col.find_one({"visitor_id": visitor_id, "chat_log_id": chat_log_id})
    if existing:
        col.update_one(
            {"_id": existing["_id"]},
            {"$set": {"feedback": feedback, "updated_at": now}},
        )
        return existing["id"]

    doc_id = _new_id()
    col.insert_one({
        "id":          doc_id,
        "visitor_id":  visitor_id,
        "session_id":  session_id,
        "chat_log_id": chat_log_id,
        "feedback":    feedback,
        "question":    question,
        "answer":      answer,
        "created_at":  now,
        "updated_at":  now,
    })
    return doc_id


def get_session_dislike_count(visitor_id: str, session_id: str) -> int:
    """Return how many dislikes this visitor has given in the current session."""
    return _col("chat_feedback").count_documents({
        "visitor_id": visitor_id,
        "session_id": session_id,
        "feedback":   "dislike",
    })


def get_visitor_total_dislike_count(visitor_id: str) -> int:
    """Return lifetime dislike count for a visitor (across all sessions)."""
    return _col("chat_feedback").count_documents({
        "visitor_id": visitor_id,
        "feedback":   "dislike",
    })


# ════════════════════════════════════════════════════════════════════════════
# DISSATISFIED USERS
# ════════════════════════════════════════════════════════════════════════════

def upsert_dissatisfied_user(
    visitor_id: str,
    session_id: str,
    dislike_count: int,
    user_info: dict | None = None,
) -> dict:
    """
    Insert or update a dissatisfied user record.
    Status stays 'open' unless admin explicitly changes it.
    Returns the full document.
    """
    now = _now()
    col = _col("dissatisfied_users")
    existing = col.find_one({"visitor_id": visitor_id})

    if existing:
        update: dict = {
            "dislike_count": dislike_count,
            "updated_at":    now,
        }
        # Only overwrite session_id if it changed (new session = new activity)
        if session_id and session_id != existing.get("session_id"):
            update["session_id"] = session_id
            update["status"] = "open"  # re-open if they're back complaining
        if user_info:
            update["user_info"] = user_info
        col.update_one({"visitor_id": visitor_id}, {"$set": update})
        return col.find_one({"visitor_id": visitor_id}, {"_id": 0})

    doc = {
        "id":            _new_id(),
        "visitor_id":    visitor_id,
        "session_id":    session_id,
        "dislike_count": dislike_count,
        "status":        "open",   # "open" | "solved" | "rejected"
        "user_info":     user_info,
        "admin_notes":   "",
        "created_at":    now,
        "updated_at":    now,
        "resolved_at":   None,
    }
    col.insert_one(doc)
    logger.info(f"  New dissatisfied user: {visitor_id}")
    return {k: v for k, v in doc.items() if k != "_id"}


def update_dissatisfied_user_info(visitor_id: str, user_info: dict) -> None:
    """Keep user_info fresh whenever the visitor fills/updates the contact form."""
    _col("dissatisfied_users").update_one(
        {"visitor_id": visitor_id},
        {"$set": {"user_info": user_info, "updated_at": _now()}},
    )


def update_dissatisfied_status(record_id: str, status: str, notes: str = "") -> None:
    """Admin marks a dissatisfied user as solved or rejected."""
    update: dict = {
        "status":     status,
        "updated_at": _now(),
    }
    if status in ("solved", "rejected"):
        update["resolved_at"] = _now()
    if notes:
        update["admin_notes"] = notes
    _col("dissatisfied_users").update_one({"id": record_id}, {"$set": update})


def get_dissatisfied_users(
    status: str | None = None,
    limit: int = 100,
    skip:  int = 0,
) -> list[dict]:
    """Return dissatisfied users, optionally filtered by status."""
    query: dict = {}
    if status:
        query["status"] = status
    return list(
        _col("dissatisfied_users")
        .find(query, {"_id": 0})
        .sort("updated_at", DESCENDING)
        .skip(skip)
        .limit(limit)
    )


def count_dissatisfied_users(status: str | None = None) -> int:
    query: dict = {} if not status else {"status": status}
    return _col("dissatisfied_users").count_documents(query)


def get_visitor_chat_history(visitor_id: str, limit: int = 200) -> list[dict]:
    """
    Return full chat history for a visitor, enriched with their feedback.
    Each turn is a chat_log doc; a 'feedback' field is injected if found.
    """
    logs = list(
        _col("chat_logs")
        .find({"visitor_id": visitor_id}, {"_id": 0})
        .sort("created_at", ASCENDING)
        .limit(limit)
    )
    # Build a lookup of chat_log_id → feedback
    log_ids = [l["id"] for l in logs]
    feedbacks = {
        f["chat_log_id"]: f["feedback"]
        for f in _col("chat_feedback").find(
            {"visitor_id": visitor_id, "chat_log_id": {"$in": log_ids}},
            {"_id": 0, "chat_log_id": 1, "feedback": 1},
        )
    }
    for log in logs:
        log["feedback"] = feedbacks.get(log["id"])   # "like" | "dislike" | None
    return logs
