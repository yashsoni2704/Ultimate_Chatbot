from langchain_text_splitters.character import RecursiveCharacterTextSplitter
from config import Config


def chunk_documents(documents):
    """
    Split documents into smaller chunks.
    """

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=Config.CHUNK_SIZE,
        chunk_overlap=Config.CHUNK_OVERLAP,
        separators=[
            "\n\n",
            "\n",
            ". ",
            " ",
            ""
        ]
    )

    chunks = text_splitter.split_documents(documents)
    print(f"Created {len(chunks)} chunks from {len(documents)} documents.")
    return chunks


def get_chunk_count(chunks):
    """
    Returns number of chunks.
    """

    return len(chunks)


def preview_chunks(chunks, count=3):
    """
    Optional function for debugging.
    """

    previews = []

    for chunk in chunks[:count]:

        previews.append({
            "length": len(chunk.page_content),
            "text": chunk.page_content[:200]
        })

    return previews