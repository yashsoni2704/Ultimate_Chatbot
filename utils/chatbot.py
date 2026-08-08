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
    """Build and cache the PromptTemplate objects (also deferred)."""
    global _prompt_no_history, _prompt_with_history
    if _prompt_no_history is None:
        from langchain_core.prompts import PromptTemplate
        _prompt_no_history = PromptTemplate(
            template=PROMPT_NO_HISTORY,
            input_variables=["context", "input"],
        )
        _prompt_with_history = PromptTemplate(
            template=PROMPT_WITH_HISTORY,
            input_variables=["context", "chat_history", "input"],
        )
    return _prompt_no_history, _prompt_with_history


# =====================================
# Prompts
# =====================================

SYSTEM_PROMPT = """You are a knowledgeable and helpful assistant. Answer only using the information provided in the context below. Do not use outside knowledge or invent details.

TONE AND FORMAT FOR NORMAL ANSWERS:
Write in plain, natural sentences. Match the format to the question — use flowing prose for explanations and opinions, and use a simple list only when the answer is genuinely enumerable (e.g. "what features does X have?"). Never use bold text, headers, or nested structure. Never mention page numbers, section names, or document structure. If the context does not contain enough information to fully answer, share what is available and note what is missing — do not refuse entirely unless the context has nothing relevant at all.

COMPARISON QUESTIONS — TABLE FORMAT:
When the user asks to compare, contrast, or evaluate two or more things side by side — including phrasings like "compare X and Y", "X vs Y", "X or Y", "difference between X and Y", "which is better", "how does X compare to Y", "tell me about both X and Y", or any question asking about the same attribute across multiple items — respond with one or more Markdown tables.

How many tables to use is your decision based on the question and the available data. Use one table when all attributes fit cleanly together. Use multiple tables when grouping by category (e.g. one table for engine specs, another for pricing) makes the answer clearer. The goal is clarity, not a fixed number.

Table rules:
- One column per item being compared, one row per attribute or feature
- Fill cells using only information from the context; use "-" for any value not present in the context
- If an entire column would be all "-" entries, exclude that item from the table and add a note below: "I don't have enough information about [item] to include it in the comparison."
- After the table(s), add 2–3 sentences in plain language summarising the key differences

For all other questions, answer in natural sentences without tables.
"""

# Both prompts share the same system instructions.
# The only difference is that the history variant receives an extra {chat_history} slot.
PROMPT_NO_HISTORY = SYSTEM_PROMPT + """
Context:
{context}

Question:
{input}

Answer:
"""

PROMPT_WITH_HISTORY = SYSTEM_PROMPT + """
Context:
{context}

Chat History:
{chat_history}

Question:
{input}

Answer:
"""

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

        prompt_no_hist, prompt_with_hist = _get_prompts()
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

            document_chain  = create_stuff_documents_chain(llm, prompt_with_hist)
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

            document_chain  = create_stuff_documents_chain(llm, prompt_no_hist)
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
