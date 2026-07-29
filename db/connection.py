"""
db/connection.py
~~~~~~~~~~~~~~~~
Single MongoDB client shared across the entire application.

Usage:
    from db.connection import get_db
    db = get_db()
    db["chat_logs"].insert_one({...})

MongoClient is thread-safe by design — a single instance handles connection
pooling internally.  We store it as a simple module-level singleton without
any locking (locks caused deadlocks between the main request thread and
background tracking threads that both call get_db() simultaneously).
"""

from __future__ import annotations

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

from config import Config
from utils.logger import get_logger

logger = get_logger(__name__)

# Module-level singleton — MongoClient manages its own thread-safe pool
_client: MongoClient | None = None
_db:     Database | None    = None


def get_client() -> MongoClient:
    """Return the shared MongoClient, creating it on first call."""
    global _client
    if _client is None:
        logger.info(f" Connecting to MongoDB: {Config.MONGO_URI}")
        _client = MongoClient(
            Config.MONGO_URI,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=5000,
        )
        try:
            _client.admin.command("ping")
            logger.info(" MongoDB connected successfully")
        except (ConnectionFailure, ServerSelectionTimeoutError) as exc:
            logger.error(f" MongoDB connection failed: {exc}")
            # Don't raise — let the app boot; individual queries will fail gracefully
    return _client


def get_db() -> Database:
    """Return the Database object for MONGO_DB_NAME."""
    global _db
    if _db is None:
        _db = get_client()[Config.MONGO_DB_NAME]
        logger.info(f" Using database: {Config.MONGO_DB_NAME}")
    return _db


def close_connection() -> None:
    """Cleanly close the client (call on app shutdown if needed)."""
    global _client, _db
    if _client is not None:
        _client.close()
        _client = None
        _db     = None
        logger.info(" MongoDB connection closed")
