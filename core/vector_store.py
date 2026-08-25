"""
core/vector_store.py

Thin wrapper around a local Chroma vector store used by core/rag_engine.py
to power the optional "chat with the video" (RAG) feature.

Kept intentionally simple: one collection per process, persisted to
VECTOR_DB_DIR so it survives restarts if you want to re-ask questions later.
"""

import os
from langchain_community.vectorstores import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter

VECTOR_DB_DIR = os.getenv("VECTOR_DB_DIR", "vector_db")

os.makedirs(VECTOR_DB_DIR, exist_ok=True)

_embeddings = None


def get_embeddings():
    global _embeddings
    if _embeddings is None:
        api_key = os.getenv("MISTRAL_API_KEY")
        if api_key:
            from langchain_mistralai import MistralAIEmbeddings
            _embeddings = MistralAIEmbeddings(mistral_api_key=api_key)
        else:
            from langchain_huggingface import HuggingFaceEmbeddings
            embedding_model = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
            _embeddings = HuggingFaceEmbeddings(model_name=embedding_model)
    return _embeddings


def build_vector_store(transcript: str):
    """Split the transcript and build a fresh in-memory-backed Chroma store."""
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    docs = splitter.create_documents([transcript])

    vector_store = Chroma.from_documents(
        documents=docs,
        embedding=get_embeddings(),
        persist_directory=VECTOR_DB_DIR,
    )
    return vector_store


def load_vector_store():
    """Reload a previously persisted store from disk."""
    return Chroma(
        persist_directory=VECTOR_DB_DIR,
        embedding_function=get_embeddings(),
    )


def get_retriever(vector_store=None, k: int = 4):
    """Return a retriever. If no store is passed, load the persisted one."""
    store = vector_store if vector_store is not None else load_vector_store()
    return store.as_retriever(search_kwargs={"k": k})
