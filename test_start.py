"""Quick startup test — writes result to test_result.txt"""
import sys, os, socket, subprocess, time

result = []

# 1. Check imports
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from flask import Flask
    from config import Config
    from db.connection import get_db
    from db.models import ensure_indexes
    from utils.ip_info import get_client_ip
    result.append("IMPORTS: OK")
except Exception as e:
    result.append(f"IMPORTS: FAILED - {e}")

# 2. Check MongoDB
try:
    db = get_db()
    db.command("ping")
    result.append("MONGODB: OK")
except Exception as e:
    result.append(f"MONGODB: FAILED - {e}")

# 3. Try binding to port 5001
try:
    s = socket.socket()
    s.bind(("0.0.0.0", 5001))
    s.close()
    result.append("PORT 5001: available")
except Exception as e:
    result.append(f"PORT 5001: {e}")

# Write results
with open("test_result.txt", "w") as f:
    f.write("\n".join(result) + "\n")

print("\n".join(result))
