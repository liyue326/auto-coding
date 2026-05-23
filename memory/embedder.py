"""Embedding：OpenAI 兼容 API（DashScope 等）或 Chroma 默认本地模型。"""
from __future__ import annotations

import logging
from typing import Any

import config as cfg

logger = logging.getLogger("multi-agent.memory")


class OpenAICompatibleEmbeddingFunction:
    """兼容 openai>=1.0 与 DashScope compatible-mode/v1。"""

    def __init__(self, api_key: str, model_name: str, api_base: str = "") -> None:
        self._api_key = api_key
        self._model = model_name
        self._api_base = api_base or None

    def __call__(self, input: list[str]) -> list[list[float]]:
        from openai import OpenAI

        client = OpenAI(api_key=self._api_key, base_url=self._api_base)
        texts = [t.replace("\n", " ") for t in input]
        resp = client.embeddings.create(model=self._model, input=texts)
        return [item.embedding for item in resp.data]

    def name(self) -> str:
        return f"openai_compatible_{self._model}"


def get_embedding_function() -> Any | None:
    if not cfg.MEMORY_ENABLED:
        return None

    if cfg.OPENAI_API_KEY:
        try:
            return OpenAICompatibleEmbeddingFunction(
                api_key=cfg.OPENAI_API_KEY,
                model_name=cfg.EMBEDDING_MODEL,
                api_base=cfg.OPENAI_BASE_URL,
            )
        except Exception as e:
            logger.warning("OpenAI 兼容 Embedding 创建失败: %s", e)

    try:
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

        logger.info("使用 Chroma 默认本地 Embedding 模型")
        return DefaultEmbeddingFunction()
    except Exception as e:
        logger.error("无法创建 Embedding: %s", e)
        return None
