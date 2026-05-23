"""Chroma 持久化存储。"""
from __future__ import annotations

import logging
from typing import Any

import config as cfg
from memory.embedder import get_embedding_function

logger = logging.getLogger("multi-agent.memory")

_client = None
_collection = None


def _persist_dir() -> str:
    cfg.CHROMA_PERSIST_DIR.mkdir(parents=True, exist_ok=True)
    return str(cfg.CHROMA_PERSIST_DIR)


def get_collection():
    """单例获取 fix_experiences 集合。"""
    global _client, _collection
    if not cfg.MEMORY_ENABLED:
        return None
    if _collection is not None:
        return _collection
    try:
        import chromadb

        ef = get_embedding_function()
        _client = chromadb.PersistentClient(path=_persist_dir())
        _collection = _client.get_or_create_collection(
            name=cfg.CHROMA_COLLECTION,
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("Chroma 已加载: %s", _persist_dir())
        return _collection
    except Exception as e:
        logger.error("Chroma 初始化失败: %s", e)
        return None


def collection_count() -> int:
    col = get_collection()
    if col is None:
        return 0
    try:
        return col.count()
    except Exception:
        return 0
