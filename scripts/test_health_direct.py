import sys
from pathlib import Path
import time

sys.path.append(str(Path(__file__).resolve().parent.parent))

from app import app

print('IMPORTED')
start = time.time()
try:
    resp = app.view_functions['health']()
    elapsed = time.time() - start
    print('HEALTH_ELAPSED', elapsed)
    try:
        data = resp.get_data(as_text=True)
        print('DATA', data)
    except Exception as e:
        print('RESP_NOT_WSGI', resp, e)
except Exception as e:
    print('HEALTH_EXCEPTION', e)
    import traceback; traceback.print_exc()
