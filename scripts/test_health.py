import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from app import app

c = app.test_client()
r = c.get('/health')
print('STATUS', r.status_code)
print(r.get_data(as_text=True))
