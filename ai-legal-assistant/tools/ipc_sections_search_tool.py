# ipc_sections_search_tool.py

import os
import logging
from dotenv import load_dotenv
from crewai.tools import tool
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

# =============================
# ENVIRONMENT & LOGGING SETUP
# =============================
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PERSIST_DIR = os.getenv("PERSIST_DIRECTORY_PATH")
COLLECTION_NAME = os.getenv("IPC_COLLECTION_NAME")

if not PERSIST_DIR or not COLLECTION_NAME:
    raise EnvironmentError("❌ PERSIST_DIRECTORY_PATH or IPC_COLLECTION_NAME not set in .env")

# =============================
# EMBEDDING FUNCTION
# =============================
embedding_function = HuggingFaceEmbeddings()

# =============================
# LOAD VECTOR STORE
# =============================
try:
    vector_db = Chroma(
        collection_name=COLLECTION_NAME,
        persist_directory=PERSIST_DIR,
        embedding_function=embedding_function
    )
    logger.info("✅ Vector DB loaded successfully.")
except Exception as e:
    logger.error(f"❌ Failed to load vector DB: {e}")
    vector_db = None

# =============================
# IPC SECTIONS SEARCH TOOL
# =============================
@tool("IPC Sections Search Tool")
def search_ipc_sections(query: str, top_k: int = 3) -> list[dict]:
    """
    Search IPC vector database for sections relevant to the input query.

    Args:
        query (str): User query in natural language.
        top_k (int): Number of top relevant sections to return (default: 3)

    Returns:
        list[dict]: List of matching IPC sections with metadata and content.
    """
    if not vector_db:
        logger.error("❌ Vector DB is not initialized.")
        return []

    if not query.strip():
        logger.warning("⚠ Empty query received.")
        return []

    try:
        docs = vector_db.similarity_search(query, k=top_k)
        results = [
            {
                "section": doc.metadata.get("section"),
                "section_title": doc.metadata.get("section_title"),
                "chapter": doc.metadata.get("chapter"),
                "chapter_title": doc.metadata.get("chapter_title"),
                "content": doc.page_content
            }
            for doc in docs
        ]
        logger.info(f"✅ Found {len(results)} sections for query: {query}")
        return results
    except Exception as e:
        logger.error(f"❌ Error during similarity search: {e}")
        return []

# =============================
# OPTIONAL: Standalone test
# =============================
if __name__ == "__main__":
    test_query = "Theft and property disputes"
    results = search_ipc_sections.func(test_query)
    for i, r in enumerate(results, start=1):
        print(f"\n--- Result {i} ---")
        print(f"Section: {r['section']}")
        print(f"Title: {r['section_title']}")
        print(f"Chapter: {r['chapter']}")
        print(f"Chapter Title: {r['chapter_title']}")
        print(f"Content: {r['content'][:200]}...")  # show first 200 chars
