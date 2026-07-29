import glob, os, re
logs = sorted(glob.glob(os.path.join('logs','app_*.log')), key=os.path.getmtime, reverse=True)
if not logs:
    print('NO_LOGS')
    exit(0)
pattern = re.compile(r"Serving Flask app 'app'|DOCMIND APPLICATION STARTED|ADMIN PANEL STARTED")
found=False
for p in logs:
    with open(p, encoding='utf-8', errors='replace') as f:
        text = f.read()
    if pattern.search(text):
        print('MATCH in', p)
        for m in re.finditer(pattern, text):
            start = max(0, m.start()-200)
            end = min(len(text), m.end()+200)
            print('--- CONTEXT ---')
            print(text[start:end])
            print('--- END ---')
        found=True
if not found:
    print('NO_MATCH_IN_ALL')
