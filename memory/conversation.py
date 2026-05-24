"""多轮对话记忆：持久化历次需求与交付结果，注入各 Agent Prompt。"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import config as cfg

logger = logging.getLogger("multi-agent.memory")


def _thread_path(thread_id: str) -> Path:
    tid = (thread_id or "default").strip() or "default"
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in tid)[:64]
    cfg.CONVERSATION_PERSIST_DIR.mkdir(parents=True, exist_ok=True)
    return cfg.CONVERSATION_PERSIST_DIR / f"{safe}.jsonl"


def load_turns(thread_id: str = "default", *, limit: int | None = None) -> list[dict[str, Any]]:
    """读取会话线程的历史轮次（时间正序）。"""
    if not cfg.CONVERSATION_MEMORY_ENABLED:
        return []
    path = _thread_path(thread_id)
    if not path.is_file():
        return []
    turns: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            turns.append(json.loads(line))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("读取对话记忆失败 %s: %s", path, e)
        return []
    max_n = limit or cfg.CONVERSATION_MAX_TURNS * 2
    return turns[-max_n:]


def append_turn(thread_id: str, turn: dict[str, Any]) -> None:
    """追加一轮对话到 JSONL。"""
    if not cfg.CONVERSATION_MEMORY_ENABLED:
        return
    path = _thread_path(thread_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(turn, ensure_ascii=False) + "\n")
    logger.info("对话记忆已写入: %s turn=%s", path.name, turn.get("turn_id"))


def clear_thread(thread_id: str = "default") -> None:
    path = _thread_path(thread_id)
    if path.is_file():
        path.unlink()


def build_turn_summary(state: dict[str, Any]) -> str:
    """从流水线终态生成一轮摘要。"""
    req = (state.get("requirement") or "")[:120]
    scope = state.get("dev_scope") or "?"
    test_ok = "通过" if state.get("test_passed") else "未通过"
    fix_r = state.get("fix_round") or 0
    out = state.get("output_dir") or ""
    be = list((state.get("backend_files") or {}).keys())[:5]
    fe = list((state.get("frontend_files") or {}).keys())[:5]
    files = ", ".join(be + fe) or "无"
    return (
        f"scope={scope} · 测试{test_ok} · BugFix{fix_r}轮 · "
        f"产出文件: {files} · 输出: {Path(out).name if out else '-'}"
    )


def build_turn_from_state(state: dict[str, Any], thread_id: str = "default") -> dict[str, Any]:
    """交付后构造可持久化的一轮记录。"""
    ts = datetime.now().isoformat(timespec="seconds")
    run_name = ""
    if state.get("output_dir"):
        run_name = Path(str(state["output_dir"])).name
    return {
        "turn_id": f"{ts.replace(':', '').replace('-', '')}_{run_name or 'run'}",
        "thread_id": thread_id,
        "timestamp": ts,
        "requirement": (state.get("requirement") or "").strip(),
        "legacy_path": state.get("legacy_path") or "",
        "dev_scope": state.get("dev_scope") or "",
        "delivered": bool(state.get("delivered")),
        "test_passed": bool(state.get("test_passed")),
        "fix_round": state.get("fix_round") or 0,
        "review_score": (state.get("review_result") or {}).get("score"),
        "output_dir": state.get("output_dir") or "",
        "backend_files": list((state.get("backend_files") or {}).keys())[:30],
        "frontend_files": list((state.get("frontend_files") or {}).keys())[:30],
        "summary": build_turn_summary(state),
    }


def format_for_prompt(
    turns: list[dict[str, Any]],
    *,
    current_requirement: str = "",
    max_turns: int | None = None,
    max_chars: int | None = None,
) -> str:
    """格式化为 Prompt 段落；默认不含与当前需求完全相同的最后一轮（避免重复）。"""
    if not turns:
        return "（无历史对话，这是本会话第一次需求）"

    max_turns = max_turns or cfg.CONVERSATION_MAX_TURNS
    max_chars = max_chars or cfg.CONVERSATION_MAX_CHARS
    cur = (current_requirement or "").strip()
    hist = turns
    if cur and hist and (hist[-1].get("requirement") or "").strip() == cur:
        hist = hist[:-1]
    hist = hist[-max_turns:]

    lines = [
        "## 多轮对话记忆（前序需求与结果，请结合理解；**以本次「业务需求」为准**）",
    ]
    for i, t in enumerate(hist, 1):
        lines.append(f"\n### 历史第 {i} 轮 ({t.get('timestamp', '')})")
        lines.append(f"- 用户: {t.get('requirement', '')}")
        lines.append(f"- 结果: {t.get('summary', '')}")
        if t.get("output_dir"):
            lines.append(f"- 输出目录: {t.get('output_dir')}")
    text = "\n".join(lines)
    return text[:max_chars]
