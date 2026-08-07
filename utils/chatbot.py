import os
import traceback
from datetime import datetime

from config import Config
from utils.logger import get_logger

logger = get_logger(__name__)


# =====================================
# LangSmith Setup
# =====================================

if Config.LANGCHAIN_TRACING_V2:
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = Config.LANGCHAIN_API_KEY
    os.environ["LANGCHAIN_PROJECT"] = Config.LANGCHAIN_PROJECT
    logger.info(f"✅ LangSmith tracing enabled — Project: {Config.LANGCHAIN_PROJECT}")
else:
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    logger.info("LangSmith tracing disabled")


# =====================================
# Lazy singletons — ALL heavy imports
# (langchain_ollama, langchain_classic)
# are deferred until the first real RAG
# call. Smalltalk/greetings return in
# milliseconds with zero Ollama overhead.
# =====================================

_embeddings = None
_llm        = None
_reranker   = None
_prompt_no_history   = None
_prompt_with_history = None
_document_prompt     = None


def _get_embeddings():
    global _embeddings
    if _embeddings is None:
        from langchain_community.embeddings import OllamaEmbeddings
        logger.info(f"Initializing embedding model: {Config.EMBEDDING_MODEL}")
        _embeddings = OllamaEmbeddings(model=Config.EMBEDDING_MODEL)
        logger.info("✅ Embedding model ready")
    return _embeddings


def _get_reranker():
    """Lazy singleton for BGE reranker. Only loaded when RERANKER_ENABLED=True."""
    global _reranker
    if _reranker is None:
        from FlagEmbedding import FlagReranker
        logger.info(f"Initializing reranker: {Config.RERANKER_MODEL}")
        _reranker = FlagReranker(Config.RERANKER_MODEL, use_fp16=True)
        logger.info("✅ Reranker ready")
    return _reranker


def _rerank(question: str, docs_with_scores: list) -> list:
    """
    Rerank retrieved chunks using BGE reranker.

    Takes the top-50 docs from Qdrant, scores each one against the question
    using the cross-encoder, and returns the top RERANKER_TOP_N docs sorted
    by reranker score descending.
    """
    reranker = _get_reranker()

    # Build (query, passage) pairs — reranker needs clean text, not enriched header
    pairs = []
    for doc, _ in docs_with_scores:
        # Use original_content if available (clean text without the context header)
        text = doc.metadata.get("original_content") or doc.page_content
        pairs.append([question, text])

    scores = reranker.compute_score(pairs, normalize=True)

    # Zip scores back with docs
    scored = sorted(
        zip(scores, docs_with_scores),
        key=lambda x: x[0],
        reverse=True,
    )

    top_n = scored[: Config.RERANKER_TOP_N]

    logger.info(f"  Reranker kept top {len(top_n)} / {len(docs_with_scores)} chunks")
    for rank, (score, (doc, _)) in enumerate(top_n, 1):
        src = doc.metadata.get("source", "N/A")
        logger.info(f"  Rank {rank:02d} | score={score:.4f} | {os.path.basename(str(src))}")

    # Return just the docs in ranked order
    return [doc for _, (doc, _) in top_n]


def _get_llm():
    global _llm
    if _llm is None:
        from langchain_ollama import ChatOllama
        logger.info(f"Initializing LLM: {Config.LLM_MODEL}")
        _llm = ChatOllama(
            model=Config.LLM_MODEL,
            temperature=Config.LLM_TEMPERATURE,
        )
        logger.info("✅ LLM ready")
    return _llm


def _get_prompts():
    """Build and cache the system/user chat prompts (also deferred)."""
    global _prompt_no_history, _prompt_with_history, _document_prompt
    if _prompt_no_history is None:
        from langchain_core.prompts import ChatPromptTemplate, PromptTemplate

        _prompt_no_history = ChatPromptTemplate.from_messages([
            ("system", PROMPT_NO_HISTORY),
            ("human", "Context:\n{context}\n\nQuestion:\n{input}\n\nAnswer:"),
        ])
        _prompt_with_history = ChatPromptTemplate.from_messages([
            ("system", PROMPT_WITH_HISTORY),
            ("human", "Context:\n{context}\n\nChat History:\n{chat_history}\n\nQuestion:\n{input}\n\nAnswer:"),
        ])
        _document_prompt = PromptTemplate.from_template(
            "Source: {source}\nRetrieved content:\n{page_content}"
        )
    return _prompt_no_history, _prompt_with_history, _document_prompt


# =====================================
# Prompts
# =====================================

# Used when CONVERSATION_HISTORY = False
PROMPT_NO_HISTORY = """
You are a helpful assistant that answers ONLY from the retrieved context.

RULES:

1. Retrieved context is the ONLY source of truth.
   Never use outside knowledge, assumptions, or guesses.

2. Keep every answer concise.
   Return only the most relevant and UNIQUE information.
   Normally provide a maximum of 4–5 useful data points unless the user explicitly asks for more.

3. Never repeat the same information in different wording.
   Do not dump or summarize all retrieved chunks.

4. If the user mentions TWO OR MORE cars/models, ALWAYS use a Markdown table.
   The table must be the FIRST thing in the answer.
   Use one column per car and only the most relevant 4–5 unique attributes.

5. For a specific question, answer only what was asked.
   Do not add unrelated specifications.

6. If information is missing from the retrieved context, use "-".
   Never invent or infer missing information.

7. EVERY answer must end with the source of the information.

For one source:
**Source:** `source`

For multiple sources:
**Sources:**
- `source 1`
- `source 2`

Only mention sources that actually contributed to the answer.
Never invent a source or URL.

GOOD EXAMPLE:

| Feature | Slavia | Virtus |
|---|---|---|
| Price | ₹... | ₹... |
| Engine | ... | ... |
| Transmission | ... | ... |
| Mileage | ... | ... |

**Sources:**
- `source 1`
- `source 2`

BAD EXAMPLE:

Slavia and Virtus are both good sedans. Slavia has a powerful engine and
Virtus also offers good performance. Both have several features and variants.
There are many other differences between them...

**Source:** `source 1`

Why this is BAD:
- Not a table despite multiple cars.
- Contains vague and repetitive information.
- Does not provide specific useful data.
- Wastes retrieved context.

IMPORTANT:
For multi-car questions, never return prose-only answers.
For normal questions, do not force a table unless the user asks for multiple cars/models.
"""

# Used when CONVERSATION_HISTORY = True
PROMPT_WITH_HISTORY = """
You are a friendly and helpful assistant. Talk like a real person — warm, clear, and easy to understand. Write in flowing, natural sentences.

Answer ONLY using information from the provided context below. Do not use your own knowledge or make anything up. Use the chat history only to understand what the user is referring to (for follow-up questions).

Important: Never mention page numbers, section numbers, document names, or any internal document structure in your answer. Just share the information naturally as if you already know it — the user does not need to know where it came from.

Understand the user's question naturally. If the retrieved context gives enough relevant information to fulfil the user's need, answer helpfully using that information. Only say "I couldn't find that — could you try rephrasing, or ask about something else?" when the retrieved context genuinely does not contain enough information to answer.

---

COMPARISON QUESTIONS - STRICT TABULAR OUTPUT REQUIRED

**MANDATORY RULE:** When the user asks to compare two or more items (cars, models, products, features, specs, variants, etc.), you MUST respond in TABULAR FORMAT ONLY.

**STRICT REQUIREMENTS:**
1. **Tables are MANDATORY** - Never use paragraphs or bullet points for comparisons
2. **Display ALL available data** from retrieved chunks - do not filter or summarize
3. **Use multiple tables if needed** - split into logical groups if data is extensive
4. **Table structure:**
   - Columns = items being compared (one column per item)
   - Rows = ALL attributes/features mentioned in retrieved chunks
   - Include every piece of information the chunks provide
5. **Missing data:** Use "-" only when information is genuinely absent from chunks
6. **No prose before/after table** - Start response directly with table(s)

**TABLE FORMAT:**
```
| Attribute | Item 1 | Item 2 | Item 3 |
|-----------|--------|--------|--------|
| Price     | ...    | ...    | ...    |
| Engine    | ...    | ...    | ...    |
| ...       | ...    | ...    | ...    |
```

**MULTIPLE TABLES EXAMPLE (if data is extensive):**
Table 1: Basic Specs
| Attribute | Car A | Car B |
|-----------|-------|-------|
| Price     | ...   | ...   |
| Engine    | ...   | ...   |

Table 2: Features
| Feature       | Car A | Car B |
|---------------|-------|-------|
| Safety        | ...   | ...   |
| Entertainment | ...   | ...   |

**DETECTION KEYWORDS:** compare, difference, vs, versus, which is better, between, A or B, and any question mentioning multiple items together.

**VIOLATION:** Any comparison answered in prose format is INCORRECT. Tables are NON-NEGOTIABLE for comparison questions.

For all other questions (not a comparison), respond in flowing natural sentences as usual.

"""

# Keep the same answer and citation rules regardless of whether chat history
# is enabled. Chat history is passed separately only to resolve follow-ups.
PROMPT_WITH_HISTORY = PROMPT_NO_HISTORY

prompt_no_history = None   # built lazily in _get_prompts()
prompt_with_history = None


# =====================================
# Load Qdrant vector store
# =====================================

def load_vector_db():
    """Load the Qdrant vector store for querying — always uses the active slot."""
    from langchain_qdrant import QdrantVectorStore
    from qdrant_client import QdrantClient
    from utils.embeddings import get_active_collection_name

    # HTTP connection — no file lock, works alongside concurrent uploads
    client = QdrantClient(
        host    = Config.QDRANT_HOST,
        port    = Config.QDRANT_PORT,
        timeout = 60,
    )

    active_collection = get_active_collection_name()
    collections = [c.name for c in client.get_collections().collections]

    if active_collection not in collections:
        raise Exception("No document has been processed yet. Please upload a document first.")

    logger.info(f"🔵 Querying active slot: {active_collection}")

    return QdrantVectorStore(
        client          = client,
        collection_name = active_collection,
        embedding       = _get_embeddings(),
    )


# =====================================
# Format history for prompt injection
# =====================================

def _format_history(history: list) -> str:
    """
    history: list of {"question": str, "answer": str}
    Returns a plain-text block ready to drop into the prompt.
    """
    if not history:
        return "No previous conversation."

    lines = []
    for i, turn in enumerate(history, 1):
        lines.append(f"Turn {i}:")
        lines.append(f"  User: {turn['question']}")
        lines.append(f"  Assistant: {turn['answer']}")
    return "\n".join(lines)


# =====================================
# Ask Question
# =====================================

def get_answer(question: str, history: list = None, metadata: dict = None) -> str:
    """
    question : current user question
    history  : list of past turns [{"question": ..., "answer": ...}]
               Honoured only when Config.CONVERSATION_HISTORY is True.
               The caller is responsible for trimming to the desired limit
               before passing.
    metadata : optional dict for LangSmith tagging (e.g. {"source": "user_chat"})
    """
    history = history or []
    metadata = metadata or {}

    # ── LangSmith run config (only built when tracing is actually on) ──────
    if Config.LANGCHAIN_TRACING_V2:
        langsmith_config = {
            "metadata": {
                "question": question,
                "llm_model": Config.LLM_MODEL,
                "embedding_model": Config.EMBEDDING_MODEL,
                "conversation_history_enabled": Config.CONVERSATION_HISTORY,
                "history_turns": len(history),
                "top_k": Config.TOP_K,
                **metadata,
            }
        }
    else:
        langsmith_config = None

    try:
        # ── Question header ────────────────────────────────────
        logger.info("=" * 100)
        logger.info("🔍  QUESTION PROCESSING STARTED")
        logger.info("=" * 100)
        logger.info(f"  Question    : {question}")
        logger.info(f"  Timestamp   : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"  History ON  : {Config.CONVERSATION_HISTORY}")
        logger.info(f"  History Len : {len(history)} turn(s)")
        logger.info("=" * 100)

        # ── Load vector store ──────────────────────────────────
        logger.info("Loading vector database...")
        vectordb = load_vector_db()
        logger.info("✅ Vector database loaded")

        # ── Retrieve chunks with scores ────────────────────────
        logger.info(f"Retrieving top {Config.TOP_K} relevant chunks...")
        try:
            docs_with_scores = vectordb.similarity_search_with_score(
                question, k=Config.TOP_K
            )
        except AttributeError:
            logger.warning("Score retrieval not available, using basic similarity search")
            docs = vectordb.similarity_search(question, k=Config.TOP_K)
            docs_with_scores = [(doc, None) for doc in docs]

        # ── Log every chunk in a readable boxed format ─────────
        logger.info(f"✅ Retrieved {len(docs_with_scores)} chunks")
        logger.info("")
        logger.info("=" * 100)
        logger.info("📚  RETRIEVED CHUNKS — FULL DEBUG VIEW")
        logger.info("=" * 100)

        for i, item in enumerate(docs_with_scores):
            doc, score = item if isinstance(item, tuple) else (item, None)
            meta  = doc.metadata if hasattr(doc, "metadata") else {}
            page  = meta.get("page", meta.get("page_number", "N/A"))
            src   = meta.get("source", meta.get("file_name", "N/A"))
            chars = len(doc.page_content)

            logger.info("")
            logger.info(f"┌─ CHUNK {i+1} of {len(docs_with_scores)} {'─' * 70}")
            if score is not None:
                logger.info(f"│  Similarity Score : {score:.6f}  (lower = more relevant)")
            else:
                logger.info(f"│  Similarity Score : N/A")
            logger.info(f"│  Page             : {page}")
            logger.info(f"│  Source           : {src}")
            logger.info(f"│  Characters       : {chars}")
            logger.info(f"│  All Metadata     : {meta}")
            logger.info(f"├─ CONTENT {'─' * 80}")
            for line in doc.page_content.splitlines():
                logger.info(f"│  {line}")
            logger.info(f"└─{'─' * 89}")

        logger.info("")
        logger.info("=" * 100)
        logger.info("📚  END OF CHUNKS")
        logger.info("=" * 100)

        # ── Rerank ─────────────────────────────────────────────
        # If enabled: score all TOP_K chunks with the cross-encoder and keep
        # only the best RERANKER_TOP_N to pass to the LLM. This gives much
        # higher precision without changing anything else in the pipeline.
        if Config.RERANKER_ENABLED:
            logger.info("")
            logger.info(f"🔀  RERANKING {len(docs_with_scores)} chunks → keeping top {Config.RERANKER_TOP_N}...")
            reranked_docs = _rerank(question, docs_with_scores)
            logger.info(f"✅ Reranking complete — {len(reranked_docs)} chunks forwarded to LLM")
        else:
            logger.info("Reranker disabled — using raw similarity order")
            reranked_docs = [doc for doc, _ in docs_with_scores]

        # ── Build retriever ────────────────────────────────────
        # We already have the final docs — use a simple lambda retriever
        # so the existing chain code needs zero changes.
        logger.info("")
        logger.info("Creating retriever and chains...")
        from langchain_core.retrievers import BaseRetriever
        from langchain_core.callbacks import CallbackManagerForRetrieverRun
        from langchain_core.documents import Document as LCDocument

        class _StaticRetriever(BaseRetriever):
            """Wraps a pre-computed list of docs so the LangChain chain works unchanged."""
            docs: list

            def _get_relevant_documents(
                self, query: str, *, run_manager: CallbackManagerForRetrieverRun
            ) -> list:
                return self.docs

        retriever = _StaticRetriever(docs=reranked_docs)

        # ── Deferred imports for chain building ────────────────
        from langchain_classic.chains import create_retrieval_chain
        from langchain_classic.chains.combine_documents import create_stuff_documents_chain

        prompt_no_hist, prompt_with_hist, document_prompt = _get_prompts()
        llm = _get_llm()

        # ── Choose prompt & build chain ────────────────────────
        if Config.CONVERSATION_HISTORY and history:
            logger.info(f"Using prompt WITH conversation history ({len(history)} turns)")
            formatted_history = _format_history(history)
            logger.info("📜  CHAT HISTORY INJECTED:")
            logger.info("-" * 60)
            for line in formatted_history.splitlines():
                logger.info(f"  {line}")
            logger.info("-" * 60)

            document_chain  = create_stuff_documents_chain(
                llm, prompt_with_hist, document_prompt=document_prompt
            )
            retrieval_chain = create_retrieval_chain(retriever, document_chain)
            logger.info("✅ Chains created (with history)")
            logger.info("")
            logger.info("Generating answer from LLM...")
            result = retrieval_chain.invoke(
                {
                    "input": question,
                    "chat_history": formatted_history,
                },
                config=langsmith_config,
            )

        else:
            if Config.CONVERSATION_HISTORY and not history:
                logger.info("History enabled but no prior turns yet — using plain prompt")
            else:
                logger.info("Conversation history DISABLED — using plain prompt")

            document_chain  = create_stuff_documents_chain(
                llm, prompt_no_hist, document_prompt=document_prompt
            )
            retrieval_chain = create_retrieval_chain(retriever, document_chain)
            logger.info("✅ Chains created (no history)")
            logger.info("")
            logger.info("Generating answer from LLM...")
            result = retrieval_chain.invoke(
                {"input": question},
                config=langsmith_config,
            )

        answer = result["answer"]

        # ── Final answer log ───────────────────────────────────
        logger.info("✅ Answer generated")
        logger.info("")
        logger.info("=" * 100)
        logger.info("📝  FINAL ANSWER")
        logger.info("=" * 100)
        for line in answer.splitlines():
            logger.info(f"  {line}")
        logger.info("=" * 100)
        logger.info("✅  QUESTION PROCESSING COMPLETED")
        logger.info("=" * 100)

        return answer

    except Exception as e:
        logger.error(f"❌ Error processing question: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        logger.error("=" * 100)
        raise
