import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.loader import _load_pdf
from utils.chunker import chunk_documents

docs   = _load_pdf("uploads/KodiaqRS.pdf")
chunks = chunk_documents(docs)

print("Total pages :", len(docs))
print("Total chunks:", len(chunks))
print()

for i, c in enumerate(chunks):
    page = c.metadata.get("page", "?")
    orig = c.metadata.get("original_content", c.page_content)
    print(f"CHUNK {i+1}  page={page}  chars={len(c.page_content)}")
    print("  EMBEDDED:", repr(c.page_content[:160]))
    print("  ORIGINAL:", repr(orig[:120]))
    print()
