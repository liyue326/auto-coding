"""对比生成代码与老项目快照，产出变更摘要与 unified diff。"""
from __future__ import annotations

import difflib
import logging
from pathlib import Path
from typing import Any

from legacy.files import _normalize_rel

logger = logging.getLogger("multi-agent.legacy")


def _read_snapshot_text(workspace: dict[str, Any], side: str, rel: str) -> str | None:
    if not workspace.get("ok"):
        return None
    snapshot = Path(workspace["snapshot_path"])
    if not snapshot.is_dir():
        return None
    norm = _normalize_rel(rel, side)
    full = snapshot / side / norm
    if not full.is_file():
        alt = snapshot / norm
        full = alt if alt.is_file() else full
    if not full.is_file():
        return None
    try:
        return full.read_text(encoding="utf-8", errors="ignore")
    except OSError as e:
        logger.warning("读取快照失败 %s: %s", full, e)
        return None


def _count_diff_lines(unified: list[str]) -> tuple[int, int]:
    added = removed = 0
    for line in unified:
        if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return added, removed


def _diff_one(
    side: str,
    path: str,
    new_content: str,
    old_content: str | None,
    *,
    context_lines: int = 3,
    max_diff_chars: int = 48000,
) -> dict[str, Any]:
    norm = _normalize_rel(path, side)
    if old_content is None:
        lines = (new_content or "").splitlines()
        return {
            "side": side,
            "path": norm,
            "status": "new",
            "lines_added": len(lines),
            "lines_removed": 0,
            "summary": f"新建（{len(lines)} 行）",
            "unified_diff": "",
            "truncated": False,
        }

    if old_content == new_content:
        return {
            "side": side,
            "path": norm,
            "status": "unchanged",
            "lines_added": 0,
            "lines_removed": 0,
            "summary": "无变化",
            "unified_diff": "",
            "truncated": False,
        }

    old_lines = old_content.splitlines(keepends=True)
    new_lines = (new_content or "").splitlines(keepends=True)
    unified = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{side}/{norm}",
            tofile=f"b/{side}/{norm}",
            n=context_lines,
        )
    )
    added, removed = _count_diff_lines(unified)
    diff_text = "".join(unified)
    truncated = False
    if len(diff_text) > max_diff_chars:
        diff_text = diff_text[:max_diff_chars] + "\n... (diff 已截断)\n"
        truncated = True

    return {
        "side": side,
        "path": norm,
        "status": "modified",
        "lines_added": added,
        "lines_removed": removed,
        "summary": f"修改 +{added} / -{removed} 行",
        "unified_diff": diff_text,
        "truncated": truncated,
    }


def compute_code_changes(
    workspace: dict[str, Any],
    backend_files: dict[str, str],
    frontend_files: dict[str, str],
    *,
    context_lines: int = 3,
    max_diff_chars: int = 48000,
) -> dict[str, Any]:
    """将生成文件与老项目快照对比，返回结构化变更报告。"""
    files: list[dict[str, Any]] = []

    for side, file_map in (("backend", backend_files), ("frontend", frontend_files)):
        for rel, content in (file_map or {}).items():
            if not rel or content is None:
                continue
            # 测试文件通常不在快照中，单独标记
            norm = _normalize_rel(rel, side)
            if norm.startswith("tests/") or "/tests/" in norm:
                files.append(
                    {
                        "side": side,
                        "path": norm,
                        "status": "generated",
                        "lines_added": len(str(content).splitlines()),
                        "lines_removed": 0,
                        "summary": f"新生成测试（{len(str(content).splitlines())} 行）",
                        "unified_diff": "",
                        "truncated": False,
                    }
                )
                continue
            old = _read_snapshot_text(workspace, side, rel)
            files.append(
                _diff_one(
                    side,
                    rel,
                    str(content),
                    old,
                    context_lines=context_lines,
                    max_diff_chars=max_diff_chars,
                )
            )

    files.sort(key=lambda x: (x["side"], x["path"]))
    modified = sum(1 for f in files if f["status"] == "modified")
    added = sum(1 for f in files if f["status"] == "new")
    generated = sum(1 for f in files if f["status"] == "generated")
    unchanged = sum(1 for f in files if f["status"] == "unchanged")

    parts: list[str] = []
    if modified:
        parts.append(f"修改 {modified} 个")
    if added:
        parts.append(f"新增 {added} 个")
    if generated:
        parts.append(f"测试 {generated} 个")
    if unchanged:
        parts.append(f"未变 {unchanged} 个")
    text_summary = " · ".join(parts) if parts else "无生成文件"

    return {
        "files": files,
        "summary": {
            "modified": modified,
            "added": added,
            "generated": generated,
            "unchanged": unchanged,
            "total": len(files),
        },
        "text_summary": text_summary,
        "has_baseline": bool(workspace.get("ok")),
    }


def format_changes_log_line(report: dict[str, Any]) -> str:
    if not report.get("has_baseline"):
        return "代码变更: 无老项目快照，仅列出新生成文件"
    s = report.get("summary") or {}
    interesting = (s.get("modified") or 0) + (s.get("added") or 0) + (s.get("generated") or 0)
    if not interesting:
        return f"代码变更: {report.get('text_summary', '无')}"
    names: list[str] = []
    for f in report.get("files") or []:
        if f.get("status") in ("modified", "new", "generated"):
            names.append(f"{f.get('side')}/{f.get('path')}: {f.get('summary')}")
    preview = "; ".join(names[:6])
    if len(names) > 6:
        preview += f" … 等 {len(names)} 个"
    return f"代码变更: {report.get('text_summary')} — {preview}"
