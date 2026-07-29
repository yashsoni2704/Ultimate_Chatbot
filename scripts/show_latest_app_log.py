import glob, os, sys
files = glob.glob(os.path.join('logs', 'app_*.log'))
if not files:
    print('NO_LOG')
    sys.exit(0)
latest = max(files, key=os.path.getmtime)
print('LATEST:', latest)
with open(latest, 'r', encoding='utf-8', errors='replace') as f:
    lines = f.readlines()
    tail = lines[-300:]
    print(''.join(tail))
