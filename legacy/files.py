"""从老项目快照加载待修改源文件，供 Dev Agent 在原文件上改动。"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger("multi-agent.legacy")

# 需求关键词 → 相对路径（相对 backend/ 或 frontend/）
_KEYWORD_PATHS: list[tuple[str, str, str]] = [
    (r"登录|login", "frontend", "src/views/LoginView.vue"),
    (r"注销|登出|logout", "frontend", "src/views/LoginView.vue"),
    (r"注销|登出|logout", "frontend", "src/api/auth.js"),
    (r"注册|register", "frontend", "src/views/LoginView.vue"),
    (r"笔记|notes", "frontend", "src/views/NotesView.vue"),
    (r"路由|router", "frontend", "src/router/index.js"),
    (r"auth|认证", "backend", "api/routes.py"),
    (r"注销|登出|logout", "backend", "api/routes.py"),
    (r"用户|user", "backend", "models/user.py"),
]


def wants_modify_existing(requirement: str) -> bool:
    """用户是否表达在原有代码/页面上改。"""
    req = requirement or ""
    patterns = (
        r"原有|现有|原来|当前",
        r"改|修改|调整|加上|增加|补充|扩展",
        r"在.{0,12}页面",
        r"页面.{0,8}(加|改)",
    )
    return any(re.search(p, req) for p in patterns)


def _normalize_rel(path: str, side: str) -> str:
    p = path.strip().replace("\\", "/").lstrip("/")
    while p.startswith(f"{side}/"):
        p = p[len(side) + 1 :]
    if p.startswith("frontend/"):
        p = p[len("frontend") + 1 :]
    if p.startswith("backend/"):
        p = p[len("backend") + 1 :]
    return p


def infer_touch_paths(
    requirement: str,
    report: dict[str, Any] | None = None,
    index: dict[str, Any] | None = None,
    side: str = "frontend",
) -> list[str]:
    """推断本次应修改的文件（相对 backend/ 或 frontend/）。"""
    paths: list[str] = []
    seen: set[str] = set()

    def add(p: str) -> None:
        norm = _normalize_rel(p, side)
        if norm and norm not in seen:
            seen.add(norm)
            paths.append(norm)

    report = report or {}
    for raw in report.get("suggested_touch_paths") or []:
        s = str(raw)
        if side == "frontend" and ("frontend" in s or s.endswith(".vue") or "src/" in s):
            add(s)
        elif side == "backend" and ("backend" in s or s.endswith(".py") or "api/" in s):
            add(s)

    req = requirement or ""
    for pattern, path_side, rel in _KEYWORD_PATHS:
        if path_side != side:
            continue
        if re.search(pattern, req, re.I):
            add(rel)

    index = index or {}
    for f in index.get("files_sample") or []:
        p = f.get("path", "")
        if not p.startswith(f"{side}/"):
            continue
        rel = _normalize_rel(p, side)
        name = Path(rel).name.lower()
        if any(k in req for k in ("登录", "login")) and "login" in name:
            add(rel)
        if any(k in req for k in ("笔记", "note")) and "note" in name:
            add(rel)

    return paths[:12]


def load_source_files(
    workspace: dict[str, Any],
    rel_paths: list[str],
    side: str,
    *,
    max_file_chars: int = 6000,
) -> dict[str, str]:
    """从 snapshot 读取源文件全文。"""
    if not workspace.get("ok") or not rel_paths:
        return {}
    snapshot = Path(workspace["snapshot_path"])
    if not snapshot.is_dir():
        return {}

    out: dict[str, str] = {}
    for rel in rel_paths:
        norm = _normalize_rel(rel, side)
        full = snapshot / side / norm
        if not full.is_file():
            # 兼容索引里 frontend/src/... 写法
            alt = snapshot / norm
            full = alt if alt.is_file() else full
        if not full.is_file():
            logger.warning("快照中无文件: %s/%s", side, norm)
            continue
        try:
            text = full.read_text(encoding="utf-8", errors="ignore")
        except OSError as e:
            logger.warning("读取失败 %s: %s", full, e)
            continue
        out[norm] = text[:max_file_chars]
    return out


def format_existing_files_block(files: dict[str, str], side: str) -> str:
    if not files:
        return "（无：未匹配到需修改的已有文件，请根据项目上下文选择正确路径）"
    lines = [
        f"## 必须在以下已有 {side} 文件上修改（禁止新建替代页面）",
        "输出 JSON 的 files 键必须使用下列路径；内容为修改后的**完整文件**，保留原有功能。",
    ]
    for path, content in files.items():
        lines.append(f"\n### 文件: {path}\n```\n{content}\n```")
    return "\n".join(lines)[:14000]
