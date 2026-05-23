"""交付后写入成功修复经验（仅 test 通过且经历过 BugFix 的 run）。"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import config as cfg
from memory.store import get_collection

logger = logging.getLogger("multi-agent.memory")


def _slug(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", (text or "")[:80]).strip("_")
    return s[:max_len] or "case"


def _document_for_case(
    requirement: str,
    dev_scope: str,
    experience: dict[str, Any],
) -> str:
    defects = experience.get("defects") or []
    lines = [
        f"需求: {requirement[:400]}",
        f"开发范围: {dev_scope}",
        f"修复轮次: {experience.get('round', '')}",
    ]
    for d in defects:
        if isinstance(d, dict):
            lines.append(
                f"缺陷 [{d.get('module', '')}] {d.get('id', '')}: {d.get('desc', '')}"
            )
    patched = experience.get("patched_files") or []
    if patched:
        lines.append(f"修改文件: {', '.join(patched)}")
    action = experience.get("fix_action") or ""
    if action:
        lines.append(f"修复方式: {action}")
    return "\n".join(lines)


def _metadata_for_case(
    run_id: str,
    requirement: str,
    dev_scope: str,
    experience: dict[str, Any],
) -> dict[str, str]:
    defects = experience.get("defects") or []
    defect_summary = "; ".join(
        f"{d.get('id', '')}:{d.get('desc', '')[:80]}"
        for d in defects
        if isinstance(d, dict)
    )[:500]
    patched = experience.get("patched_files") or []
    return {
        "outcome": "success",
        "run_id": run_id,
        "dev_scope": dev_scope or "fullstack",
        "round": str(experience.get("round", "")),
        "requirement_summary": requirement[:200],
        "defect_summary": defect_summary,
        "fix_action": str(experience.get("fix_action", ""))[:200],
        "patched_files": ",".join(patched)[:500],
        "defects_json": json.dumps(defects, ensure_ascii=False)[:2000],
    }


def should_ingest_run(state: dict[str, Any]) -> bool:
    """仅：测试通过 + 至少一轮 BugFix 记录。"""
    if not state.get("test_passed"):
        return False
    experiences = state.get("fix_experiences") or []
    return len(experiences) > 0


def ingest_successful_run(state: dict[str, Any], run_id: str = "") -> int:
    """
    将 fix_experiences 中每轮成功修复写入 Chroma。
    返回写入条数。
    """
    if not cfg.MEMORY_ENABLED or not should_ingest_run(state):
        return 0

    col = get_collection()
    if col is None:
        return 0

    requirement = (state.get("requirement") or "").strip()
    dev_scope = state.get("dev_scope") or "fullstack"
    run_id = run_id or _slug(requirement)
    if state.get("output_dir"):
        from pathlib import Path

        run_id = Path(str(state["output_dir"])).name

    experiences = state.get("fix_experiences") or []
    if not experiences:
        return 0

    added = 0
    seen_ids: set[str] = set()
    for exp in experiences:
        if not isinstance(exp, dict):
            continue
        round_n = exp.get("round", 0)
        case_id = f"{run_id}_r{round_n}"
        if case_id in seen_ids:
            continue
        seen_ids.add(case_id)
        doc = _document_for_case(requirement, dev_scope, exp)
        meta = _metadata_for_case(run_id, requirement, dev_scope, exp)
        try:
            col.upsert(
                ids=[case_id],
                documents=[doc],
                metadatas=[meta],
            )
            added += 1
            logger.info("已入库修复经验: %s", case_id)
        except Exception as e:
            logger.error("入库失败 %s: %s", case_id, e)

    return added
