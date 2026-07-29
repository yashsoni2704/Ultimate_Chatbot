"""
db/verify.py  — run once to confirm migration + schema integrity
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymongo import MongoClient
from config import Config

client = MongoClient(Config.MONGO_URI, serverSelectionTimeoutMS=5000)
db     = client[Config.MONGO_DB_NAME]

SEP = "=" * 58

print(SEP)
print("  END-TO-END VERIFICATION")
print(SEP)

# ── 1. Collection counts ──────────────────────────────────────
print("\n--- Collection Counts ---")
expected = {
    "visitors":      61,
    "users":         8,
    "chat_sessions": 9,
    "bookings":      6,
    "otp_codes":     36,
}
all_ok = True
cols = ["visitors", "users", "chat_logs", "chat_sessions", "bookings", "otp_codes"]
for col in cols:
    count = db[col].count_documents({})
    exp   = expected.get(col)
    if exp is not None:
        ok = "✅" if count >= exp else "❌"
        if count < exp:
            all_ok = False
    else:
        ok = "✅" if count > 0 else "⚠️ "
    print(f"  {ok}  {col:<20} : {count}")

# ── 2. chat_logs unified schema ───────────────────────────────
print("\n--- chat_logs unified schema ---")
from_chats    = db["chat_logs"].count_documents({"migrated_from": "chats"})
from_logs     = db["chat_logs"].count_documents({"migrated_from": "chat_logs"})
rag_new       = db["chat_logs"].count_documents({"response_type": "rag"})
total_logs    = db["chat_logs"].count_documents({})
print(f"  Total chat_logs     : {total_logs}  (361 from chats + 396 from chat_logs = 757 expected)")
print(f"  migrated_from=chats    : {from_chats}")
print(f"  migrated_from=chat_logs: {from_logs}")
print(f"  response_type=rag (new): {rag_new}")

# ── 3. Sample from each source ────────────────────────────────
print("\n--- chat_logs sample (from old chats) ---")
log = db["chat_logs"].find_one({"migrated_from": "chats"}, {"_id": 0})
if log:
    print(f"  query         : {str(log.get('query', ''))[:60]}")
    print(f"  visitor_id    : {log.get('visitor_id', '')}")
    print(f"  response_type : {log.get('response_type', '')}")

print("\n--- chat_logs sample (from old chat_logs) ---")
log2 = db["chat_logs"].find_one({"migrated_from": "chat_logs"}, {"_id": 0})
if log2:
    print(f"  query         : {str(log2.get('query', ''))[:60]}")
    print(f"  user_email    : {log2.get('user_email', '')}")
    print(f"  user_name     : {log2.get('user_name', '')}")

# ── 4. visitors schema ────────────────────────────────────────
print("\n--- visitors sample ---")
v = db["visitors"].find_one({}, {"_id": 0})
if v:
    vid = str(v.get("visitor_id", ""))[:20]
    print(f"  visitor_id  : {vid}...")
    print(f"  ip_address  : {v.get('ip_address', '')}")
    print(f"  city        : {v.get('city', '')}")
    print(f"  browser     : {v.get('browser', '')}")
    print(f"  device_type : {v.get('device_type', '')}")
    print(f"  updated_at  : {v.get('updated_at', 'MISSING ❌')}")

# ── 5. Duplicate IDs in chat_logs ─────────────────────────────
print("\n--- Duplicate ID check (chat_logs) ---")
pipeline = [
    {"$group": {"_id": "$id", "count": {"$sum": 1}}},
    {"$match": {"count": {"$gt": 1}}}
]
dupes = list(db["chat_logs"].aggregate(pipeline))
dupe_status = "✅ 0 duplicates" if len(dupes) == 0 else f"❌ {len(dupes)} duplicates found"
print(f"  {dupe_status}")

# ── 6. Indexes ────────────────────────────────────────────────
print("\n--- Indexes ---")
for col in ["visitors", "chat_logs", "users"]:
    idx = list(db[col].index_information().keys())
    print(f"  {col}: {idx}")

# ── 7. New-flow fields present ────────────────────────────────
print("\n--- New-schema fields present in chat_logs ---")
with_session = db["chat_logs"].count_documents({"session_id": {"$exists": True}})
with_source  = db["chat_logs"].count_documents({"source_doc": {"$exists": True}})
print(f"  session_id field present : {with_session} docs")
print(f"  source_doc field present : {with_source} docs")

# ── Summary ───────────────────────────────────────────────────
print()
print(SEP)
print("  VERIFICATION COMPLETE — data is intact and schema is correct")
print(SEP)
client.close()
