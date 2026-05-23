"""检索相似成功修复案例。"""
from __future__ import annotations

import json
import logging
from typing import Any

import config as cfg
from memory.store import get_collection

logger = logging.getLogger("multi-agent.memory")


def _build_query_text(requirement: str, dev_scope: str, defects: list[dict]) -> str:
    parts = [
        f"需求: {(requirement or '')[:300]}",
        f"scope: {dev_scope or 'fullstack'}",
    ]
    for d in defects[:8]:
        if isinstance(d, dict):
            parts.append(
                f"缺陷 {d.get('id', '')} [{d.get('module', '')}] {d.get('desc', '')}"
            )
    return "\n".join(parts)


def retrieve_similar_fixes(
    requirement: str,
    dev_scope: str,
    defects: list[dict],
    *,
    top_k: int | None = None,
) -> list[dict[str, Any]]:
    """
    返回 Top-K 成功修复案例（仅 outcome=success 的文档在库中）。
    每项: case_id, distance, document, metadata
    """
    if not cfg.MEMORY_ENABLED or not defects:
        return []

    col = get_collection()
    if col is None or col.count() == 0:
        return []

    k = top_k or cfg.MEMORY_TOP_K
    query = _build_query_text(requirement, dev_scope, defects)
    where: dict[str, Any] | None = None
    if dev_scope:
        where = {"dev_scope": dev_scope}

    try:
        res = col.query(
            query_texts=[query],
            n_results=min(k, col.count()),
            where=where,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as e:
        logger.warning("向量检索失败(忽略 where 重试): %s", e)
        try:
            res = col.query(
                query_texts=[query],
                n_results=min(k, col.count()),
                include=["documents", "metadatas", "distances"],
            )
        except Exception as e2:
            logger.error("向量检索失败: %s", e2)
            return []

    out: list[dict[str, Any]] = []
    ids = (res.get("ids") or [[]])[0]
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    for i, case_id in enumerate(ids):
        out.append(
            {
                "case_id": case_id,
                "distance": dists[i] if i < len(dists) else None,
                "document": docs[i] if i < len(docs) else "",
                "metadata": metas[i] if i < len(metas) else {},
            }
        )
    logger.info("修复经验检索 %d 条 (scope=%s)", len(out), dev_scope)
    return out


def format_hints_for_prompt(cases: list[dict[str, Any]]) -> str:
    if not cases:
        return ""
    blocks = [
        "## 历史成功修复参考（仅借鉴修复手法，勿改变当前用户需求与业务）",
    ]
    for i, c in enumerate(cases, 1):
        meta = c.get("metadata") or {}
        blocks.append(f"### 案例 {i} (id={c.get('case_id', '')})")
        blocks.append(f"- 需求摘要: {meta.get('requirement_summary', '')}")
        blocks.append(f"- 缺陷: {meta.get('defect_summary', '')}")
        blocks.append(f"- 修法: {meta.get('fix_action', '')}")
        blocks.append(f"- 涉及文件: {meta.get('patched_files', '')}")
        doc = (c.get("document") or "").strip()
        if doc:
            blocks.append(doc[:1200])
    return "\n".join(blocks)
