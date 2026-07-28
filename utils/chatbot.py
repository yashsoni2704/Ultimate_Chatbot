import os
import traceback
from datetime import datetime

from config import Config

from langchain_community.embeddings import OllamaEmbeddings
from langchain_ollama import ChatOllama
from langchain_core.prompts import PromptTemplate
from langchain_classic.chains import create_retrieval_chain
from langchain_classic.chains.combine_documents import create_stuff_documents_chain

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
# Embeddings (Ollama)
# =====================================

embeddings = OllamaEmbeddings(
    model=Config.EMBEDDING_MODEL
)


# =====================================
# LLM (Ollama)
# =====================================

llm = ChatOllama(
    model=Config.LLM_MODEL,
    temperature=Config.LLM_TEMPERATURE,
)


# =====================================
# Prompts
# =====================================

# Used when CONVERSATION_HISTORY = False
PROMPT_NO_HISTORY = """
You are a friendly and helpful assistant. Talk like a real person — warm, clear, and easy to understand. Avoid bullet points, technical jargon, or overly formal language unless the user specifically asks for it. Write in flowing, natural sentences.

Answer ONLY using information from the provided context below. Do not use your own knowledge or make anything up.

If the answer is not in the context, say something like: "I couldn't find that in the document — could you try rephrasing, or check if it's covered in a different section?"

Context:
{context}

Question:
{input}

Answer:
"""

# Used when CONVERSATION_HISTORY = True
PROMPT_WITH_HISTORY = """
You are a friendly and helpful assistant. Talk like a real person — warm, clear, and easy to understand. Avoid bullet points, technical jargon, or overly formal language unless the user specifically asks for it. Write in flowing, natural sentences.

Answer ONLY using information from the provided context below. Do not use your own knowledge or make anything up. Use the chat history only to understand what the user is referring to (for follow-up questions).

If the answer is not in the context, say something like: "I couldn't find that in the document — could you try rephrasing, or check if it's covered in a different section?"

Context:
{context}

Chat History:
{chat_history}

Question:
{input}

Answer:
"""

prompt_no_history = PromptTemplate(
    template=PROMPT_NO_HISTORY,
    input_variables=["context", "input"],
)

prompt_with_history = PromptTemplate(
    template=PROMPT_WITH_HISTORY,
    input_variables=["context", "chat_history", "input"],
)


# =====================================
# Load Qdrant vector store
# =====================================

def load_vector_db():
    """Load the Qdrant vector store for querying."""
    from langchain_qdrant import QdrantVectorStore
    from qdrant_client import QdrantClient

    os.makedirs(Config.QDRANT_PATH, exist_ok=True)
    client = QdrantClient(path=Config.QDRANT_PATH)

    collections = [c.name for c in client.get_collections().collections]
    if Config.QDRANT_COLLECTION_NAME not in collections:
        raise Exception("No document has been processed yet. Please upload a document first.")

    return QdrantVectorStore(
        client=client,
        collection_name=Config.QDRANT_COLLECTION_NAME,
        embedding=embeddings,
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

    # ── LangSmith run metadata ─────────────────────────────────
    run_metadata = {
        "question": question,
        "llm_model": Config.LLM_MODEL,
        "embedding_model": Config.EMBEDDING_MODEL,
        "conversation_history_enabled": Config.CONVERSATION_HISTORY,
        "history_turns": len(history),
        "top_k": Config.TOP_K,
        **metadata,  # merge caller-provided tags
    }

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

        # ── Build retriever ────────────────────────────────────
        logger.info("")
        logger.info("Creating retriever and chains...")
        retriever = vectordb.as_retriever(
            search_type="similarity",
            search_kwargs={"k": Config.TOP_K},
        )

        # ── Choose prompt & build chain ────────────────────────
        if Config.CONVERSATION_HISTORY and history:
            logger.info(f"Using prompt WITH conversation history ({len(history)} turns)")
            formatted_history = _format_history(history)
            logger.info("📜  CHAT HISTORY INJECTED:")
            logger.info("-" * 60)
            for line in formatted_history.splitlines():
                logger.info(f"  {line}")
            logger.info("-" * 60)

            document_chain = create_stuff_documents_chain(llm, prompt_with_history)
            retrieval_chain = create_retrieval_chain(retriever, document_chain)
            logger.info("✅ Chains created (with history)")
            logger.info("")
            logger.info("Generating answer from LLM...")
            result = retrieval_chain.invoke(
                {
                    "input": question,
                    "chat_history": formatted_history,
                },
                config={"metadata": run_metadata} if Config.LANGCHAIN_TRACING_V2 else None,
            )

        else:
            if Config.CONVERSATION_HISTORY and not history:
                logger.info("History enabled but no prior turns yet — using plain prompt")
            else:
                logger.info("Conversation history DISABLED — using plain prompt")

            document_chain = create_stuff_documents_chain(llm, prompt_no_history)
            retrieval_chain = create_retrieval_chain(retriever, document_chain)
            logger.info("✅ Chains created (no history)")
            logger.info("")
            logger.info("Generating answer from LLM...")
            result = retrieval_chain.invoke(
                {"input": question},
                config={"metadata": run_metadata} if Config.LANGCHAIN_TRACING_V2 else None,
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
