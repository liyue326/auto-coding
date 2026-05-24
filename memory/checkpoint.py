"""LangGraph Checkpoint：按 thread_id 持久化流水线状态与多轮对话。"""
from __future__ import annotations

import logging
from typing import Any

import config as cfg

logger = logging.getLogger("multi-agent.memory")

_checkpointer: Any = None


def get_checkpointer():
    """单例 Checkpointer（优先 SQLite 持久化）。"""
    global _checkpointer
    if _checkpointer is not None:
        return _checkpointer

    if cfg.LANGGRAPH_CHECKPOINT_SQLITE:
        try:
            import sqlite3

            from langgraph.checkpoint.sqlite import SqliteSaver

            cfg.LANGGRAPH_CHECKPOINT_DB.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(
                str(cfg.LANGGRAPH_CHECKPOINT_DB.resolve()),
                check_same_thread=False,
            )
            _checkpointer = SqliteSaver(conn)
            logger.info("LangGraph Checkpoint: SqliteSaver %s", cfg.LANGGRAPH_CHECKPOINT_DB)
            return _checkpointer
        except ImportError:
            logger.warning(
                "未安装 langgraph-checkpoint-sqlite，回退内存 Checkpoint。"
                "请执行: pip install langgraph-checkpoint-sqlite"
            )

    from langgraph.checkpoint.memory import InMemorySaver

    _checkpointer = InMemorySaver()
    logger.info("LangGraph Checkpoint: InMemorySaver（进程内，重启丢失）")
    return _checkpointer


def thread_config(thread_id: str) -> dict:
    """invoke / stream 使用的 configurable（LangGraph 标准 thread_id）。"""
    tid = (thread_id or cfg.CONVERSATION_DEFAULT_THREAD).strip() or "default"
    return {"configurable": {"thread_id": tid}}


def load_conversation_turns(graph: Any, thread_id: str) -> list[dict[str, Any]]:
    """从 Checkpoint 读取该线程已保存的 conversation_turns。"""
    if not cfg.CONVERSATION_MEMORY_ENABLED or not cfg.CONVERSATION_USE_CHECKPOINT:
        return []
    try:
        snap = graph.get_state(thread_config(thread_id))
        if snap and getattr(snap, "values", None):
            return list(snap.values.get("conversation_turns") or [])
    except Exception as e:
        logger.warning("读取 Checkpoint 对话记忆失败: %s", e)
    return []


def clear_thread_checkpoint(graph: Any, thread_id: str) -> bool:
    """删除某对话线程的 Checkpoint（不可恢复）。"""
    try:
        checkpointer = get_checkpointer()
        if hasattr(checkpointer, "delete_thread"):
            checkpointer.delete_thread(thread_id)
            return True
        # 兼容：无 delete_thread 时仅打日志
        logger.warning("当前 Checkpointer 不支持 delete_thread: %s", thread_id)
        return False
    except Exception as e:
        logger.error("清空 Checkpoint 失败: %s", e)
        return False
