"""修复合并后产生的 backend/backend、frontend/frontend 嵌套目录。"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

import config as cfg

logger = logging.getLogger("multi-agent.legacy")


def repair_nested_merge_dirs(
    target_root: Path,
    *,
    backend_subdir: str | None = None,
    frontend_subdir: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    若存在 target/backend/backend 或 target/frontend/frontend，
    将内层文件上移到外层并删除空壳内层目录。
    """
    target_root = Path(target_root).expanduser().resolve()
    be_name = backend_subdir or cfg.MERGE_BACKEND_SUBDIR
    fe_name = frontend_subdir or cfg.MERGE_FRONTEND_SUBDIR
    result: dict[str, Any] = {
        "ok": True,
        "target_root": str(target_root),
        "moved": [],
        "removed_dirs": [],
        "dry_run": dry_run,
    }

    for label, sub in (("backend", be_name), ("frontend", fe_name)):
        outer = target_root / sub
        inner = outer / sub
        if not inner.is_dir():
            continue
        for fp in sorted(inner.rglob("*")):
            if not fp.is_file():
                continue
            rel = fp.relative_to(inner)
            dest = outer / rel
            result["moved"].append(f"{label}/{rel}")
            if dry_run:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                logger.warning("跳过已存在: %s", dest)
                continue
            shutil.copy2(fp, dest)
        if not dry_run:
            shutil.rmtree(inner)
            result["removed_dirs"].append(str(inner))
            logger.info("已移除嵌套目录: %s", inner)

    return result
