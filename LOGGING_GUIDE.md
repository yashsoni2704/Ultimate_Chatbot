# Backend Logging Guide

## Overview
Your backend now has comprehensive logging that tracks:
1. **Document uploads** - What's being processed and how many chunks
2. **Chunk retrieval** - Which chunks are selected with similarity scores
3. **Chunk content** - The actual text from each selected chunk
4. **Answer generation** - The full pipeline from question to answer

## Log Files Location
All logs are saved in: `logs/` directory
- Files are named with timestamp: `app_YYYY-MM-DD_HH-MM-SS.log`
- Logs print to console AND save to file simultaneously

## What Gets Logged

### 1️⃣ Document Upload (in `utils/loader.py`)
```
📄 DOCUMENT PROCESSING STARTED
├─ File path: [filepath]
├─ Step 1: Loading document
│  └─ ✅ Loaded X documents
├─ Step 2: Creating chunks  
│  └─ ✅ Created Y chunks
│  └─ Chunk details (size, preview)
└─ Step 3: Creating embeddings
   └─ ✅ Vector store created
```

### 2️⃣ Chunk Embedding (in `utils/embeddings.py`)
```
Step 1️⃣  Starting embeddings
├─ Total chunks to embed: X
├─ Embedding model: [model-name]
├─ Timestamp: YYYY-MM-DD HH:MM:SS
└─ Step 4: Vector store saved
```

### 3️⃣ Question Processing (in `utils/chatbot.py`)
```
🔍 QUESTION PROCESSING STARTED
├─ Question: [user's question]
├─ Loading vector database
├─ Retrieving top K chunks
│  └─ ✅ Retrieved X chunks
│
├─ 📚 RETRIEVED CHUNKS DETAILS:
│  ├─ Chunk 1 | Score: 0.85
│  │  ├─ Metadata: [metadata info]
│  │  └─ Content: [full chunk text]
│  ├─ Chunk 2 | Score: 0.78
│  │  ├─ Metadata: [metadata info]
│  │  └─ Content: [full chunk text]
│  └─ ... (all TOP_K chunks)
│
├─ Generating answer from LLM
└─ 📝 ANSWER: [full answer text]
```

## How to Read Logs

### Check Latest Activity
```bash
# View the latest log file (Windows PowerShell)
Get-Content (Get-ChildItem logs/ -Latest).FullName -Tail 50

# Or just browse logs/ folder and open the most recent .log file
```

### Key Information in Logs

**Similarity Scores (0-1 scale):**
- Scores closer to 1.0 = More relevant chunks
- Usually scores range from 0.5 to 0.95
- Lower scores = Less relevant content

**Chunk Content:**
- Full text of each selected chunk is logged
- See exactly what context the LLM used

**Timestamps:**
- Track how long each operation takes
- Identify bottlenecks if performance is slow

## Examples

### Example: Document Upload Log
```
2025-07-23 14:30:15,123 - utils.loader - INFO - ================================================================================
2025-07-23 14:30:15,124 - utils.loader - INFO - 📄 DOCUMENT PROCESSING STARTED
2025-07-23 14:30:15,125 - utils.loader - INFO - File path: uploads/MyDoc.pdf
2025-07-23 14:30:15,500 - utils.loader - INFO - ✅ Loaded 15 documents
2025-07-23 14:30:15,750 - utils.loader - INFO - ✅ Created 42 chunks
2025-07-23 14:31:10,200 - utils.loader - INFO - ✅ Vector store created successfully
```

### Example: Question Log
```
2025-07-23 14:35:22,100 - utils.chatbot - INFO - 🔍 QUESTION PROCESSING STARTED
2025-07-23 14:35:22,105 - utils.chatbot - INFO - Question: What is machine learning?
2025-07-23 14:35:22,200 - utils.chatbot - INFO - ✅ Retrieved 5 chunks
2025-07-23 14:35:22,210 - utils.chatbot - INFO - 
2025-07-23 14:35:22,211 - utils.chatbot - INFO - 📚 RETRIEVED CHUNKS DETAILS:
2025-07-23 14:35:22,212 - utils.chatbot - INFO - Chunk 1 | Score: 0.8956
2025-07-23 14:35:22,213 - utils.chatbot - INFO - Content: Machine learning is a type of...
2025-07-23 14:35:23,450 - utils.chatbot - INFO - ✅ Answer generated
```

## Configuration

Change logging in `utils/logger.py`:
- `LOG_DIR` - Where to save log files
- `logging.basicConfig()` - Logging format and level

## Tips

1. **Search logs for "❌"** to find errors
2. **Search for "Score:"** to see chunk relevance
3. **Similarity scores < 0.7** might indicate poor matches
4. **Check chunk content** to see what context LLM used
5. **Keep logs for debugging** - save them if issues occur

---

**Happy Logging! 📊**
