"""隔离工作区：复制快照、索引、导出包、人工确认后写回老项目。"""
from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import config as cfg
from legacy.indexer import build_project_index

logger = logging.getLogger("multi-agent.legacy")


def _workspace_id_for(path: Path) -> str:
    name = path.name or "legacy"
    return re.sub(r"[^\w\u4e00-\u9fff-]+", "_", name).strip("_") or "legacy"


def _ignore_copy(dir: str, names: list[str]) -> set[str]:
    from legacy.indexer import IGNORE_DIRS

    return {n for n in names if n in IGNORE_DIRS or n.startswith(".")}


def prepare_legacy_workspace(legacy_path: str) -> dict[str, Any]:
    """
    从老项目路径准备隔离工作区（复制到 data/workspaces/<id>/，不修改原目录）。
    返回 workspace 元数据供 state / Prompt 使用。
    """
    source = Path(legacy_path).expanduser().resolve()
    if not source.is_dir():
        return {"ok": False, "error": f"目录不存在: {source}"}

    wid = _workspace_id_for(source)
    ws_root = cfg.WORKSPACES_DIR / wid
    snapshot = ws_root / "source"
    sandbox = ws_root / "sandbox"
    index_file = ws_root / "index" / "project_map.json"

    ws_root.mkdir(parents=True, exist_ok=True)
    skipped_copy = False
    if (
        snapshot.is_dir()
        and index_file.is_file()
        and (snapshot / "frontend").is_dir()
    ):
        try:
            index = json.loads(index_file.read_text(encoding="utf-8"))
            skipped_copy = True
            logger.info("工作区快照已存在，跳过重复复制: %s", snapshot)
        except (json.JSONDecodeError, OSError):
            index = build_project_index(snapshot, index_file)
    else:
        if snapshot.exists():
            shutil.rmtree(snapshot)
        shutil.copytree(source, snapshot, ignore=_ignore_copy, dirs_exist_ok=True)
        logger.info("已复制老项目快照 → %s（原目录只读）", snapshot)
        index = build_project_index(snapshot, index_file)

    if sandbox.exists():
        shutil.rmtree(sandbox)
    shutil.copytree(snapshot, sandbox, ignore=_ignore_copy, dirs_exist_ok=True)
    (sandbox / "backend").mkdir(parents=True, exist_ok=True)
    (sandbox / "frontend").mkdir(parents=True, exist_ok=True)

    if not skipped_copy and index_file.is_file():
        index = json.loads(index_file.read_text(encoding="utf-8"))

    return {
        "ok": True,
        "workspace_id": wid,
        "source_path": str(source),
        "snapshot_path": str(snapshot),
        "sandbox_path": str(sandbox),
        "index_path": str(index_file),
        "index": index,
        "prepared_at": datetime.now().isoformat(timespec="seconds"),
        "skipped_copy": skipped_copy,
    }


def format_legacy_context(workspace: dict[str, Any], requirement: str = "", max_chars: int = 3500) -> str:
    """将索引压缩为 Prompt 可读文本。"""
    if not workspace.get("ok"):
        return json.dumps(workspace, ensure_ascii=False)[:500]
    idx = workspace.get("index") or {}
    lines = [
        f"老项目根目录（只读）: {workspace.get('source_path')}",
        f"工作区 sandbox: {workspace.get('sandbox_path')}",
        f"技术栈: {idx.get('stack', 'unknown')}",
        f"已索引文件数: {idx.get('file_count', 0)}",
    ]
    routes = idx.get("api_routes") or []
    if routes:
        lines.append("已有后端路由/前缀: " + ", ".join(routes[:25]))
    vr = idx.get("vue_routes") or []
    if vr:
        lines.append("已有前端路由: " + ", ".join(vr[:20]))
    mods = idx.get("python_modules") or []
    if mods:
        lines.append("Python 模块摘要:")
        for m in mods[:12]:
            syms = [s["name"] for s in m.get("symbols", [])[:6]]
            lines.append(f"  - {m.get('path')}: {', '.join(syms)}")
    if requirement:
        req_lower = requirement.lower()
        for f in idx.get("files_sample") or []:
            p = f.get("path", "")
            if any(k in p.lower() or k in req_lower for k in ("auth", "login", "api", "view", "route")):
                lines.append(f"相关文件: {p}")
                if len(lines) > 40:
                    break
    text = "\n".join(lines)
    return text[:max_chars]


def build_export_package(
    run_dir: Path,
    workspace: dict[str, Any],
    requirement: str,
    merge_result: dict | None = None,
) -> dict[str, Any]:
    """将 output/run_xxx 生成为可审阅的导出包（仍不写老项目原路径）。"""
    run_dir = Path(run_dir).resolve()
    wid = workspace.get("workspace_id") or "legacy"
    export_root = cfg.WORKSPACES_DIR / wid / "export" / run_dir.name
    files_dir = export_root / "files"
    if export_root.exists():
        shutil.rmtree(export_root)
    files_dir.mkdir(parents=True, exist_ok=True)

    for label in ("backend", "frontend"):
        src = run_dir / label
        if src.is_dir():
            shutil.copytree(src, files_dir / label, dirs_exist_ok=True)

    manifest = {
        "run": run_dir.name,
        "requirement": requirement,
        "source_path": workspace.get("source_path"),
        "sandbox_path": workspace.get("sandbox_path"),
        "export_dir": str(export_root),
        "files_dir": str(files_dir),
        "merge_preview": merge_result or {},
        "status": "pending_approval",
        "how_to_apply": (
            "在 Streamlit 点击「确认写入老项目」，或 CLI: "
            f"python3 -m legacy.export_cli {export_root}"
        ),
    }
    (export_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("导出包已生成: %s", export_root)
    return {"ok": True, "export_dir": str(export_root), "manifest": manifest}


def export_to_legacy(
    run_dir: Path,
    legacy_path: str,
    *,
    approved: bool = True,
    backend_subdir: str | None = None,
    frontend_subdir: str | None = None,
    conflict_mode: str | None = None,
) -> dict:
    """人工确认后，将 run 产出合并到老项目路径。"""
    if not approved:
        return {"ok": False, "error": "未确认导出，已拒绝写入老项目"}
    from pipeline import merge_to_project

    target = Path(legacy_path).expanduser().resolve()
    return merge_to_project(
        Path(run_dir),
        target,
        backend_subdir=backend_subdir,
        frontend_subdir=frontend_subdir,
        conflict_mode=conflict_mode or cfg.MERGE_CONFLICT_MODE,
    )
