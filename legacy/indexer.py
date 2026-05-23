"""老项目静态索引：文件树、Python 符号、API 路径、依赖。"""
from __future__ import annotations

import ast
import json
import logging
import re
from pathlib import Path
from typing import Any

import config as cfg

logger = logging.getLogger("multi-agent.legacy")

IGNORE_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".merge_conflicts",
    ".venv",
    "venv",
    "dist",
    "build",
    ".cursor",
}
IGNORE_FILES = {".DS_Store", "Thumbs.db"}


def _should_skip(path: Path) -> bool:
    return any(part in IGNORE_DIRS for part in path.parts)


def _detect_layout(root: Path) -> tuple[Path | None, Path | None]:
    be = root / cfg.MERGE_BACKEND_SUBDIR
    fe = root / cfg.MERGE_FRONTEND_SUBDIR
    return (be if be.is_dir() else None, fe if fe.is_dir() else None)


def _parse_python_file(path: Path, text: str) -> dict[str, Any]:
    symbols: list[dict] = []
    routes: list[str] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {"symbols": [], "routes": []}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            methods = [n.name for n in node.body if isinstance(n, ast.FunctionDef)]
            symbols.append({"kind": "class", "name": node.name, "methods": methods[:20]})
        elif isinstance(node, ast.FunctionDef):
            symbols.append({"kind": "function", "name": node.name})
        elif isinstance(node, ast.AsyncFunctionDef):
            symbols.append({"kind": "async_function", "name": node.name})
    for m in re.finditer(r'@router\.(get|post|put|patch|delete)\(["\']([^"\']+)', text, re.I):
        routes.append(f"{m.group(1).upper()} {m.group(2)}")
    for m in re.finditer(r'APIRouter\s*\([^)]*prefix\s*=\s*["\']([^"\']+)', text):
        routes.append(f"PREFIX {m.group(1)}")
    return {"symbols": symbols[:40], "routes": routes[:30]}


def _parse_vue_routes(text: str) -> list[str]:
    routes: list[str] = []
    for m in re.finditer(r"""path:\s*['"]([^'"]+)['"]""", text):
        routes.append(m.group(1))
    return routes[:30]


def _collect_deps(root: Path, be: Path | None, fe: Path | None) -> dict[str, list[str]]:
    deps: dict[str, list[str]] = {"python": [], "node": []}
    if be:
        req = be / "requirements.txt"
        if not req.exists():
            for p in be.rglob("requirements.txt"):
                req = p
                break
        if req.exists():
            deps["python"] = [
                ln.strip()
                for ln in req.read_text(encoding="utf-8", errors="ignore").splitlines()
                if ln.strip() and not ln.startswith("#")
            ][:40]
    if fe:
        pkg = fe / "package.json"
        if not pkg.exists():
            for p in fe.rglob("package.json"):
                if "node_modules" not in p.parts:
                    pkg = p
                    break
        if pkg.exists():
            try:
                data = json.loads(pkg.read_text(encoding="utf-8"))
                deps["node"] = list((data.get("dependencies") or {}).keys())[:30]
            except json.JSONDecodeError:
                pass
    return deps


def build_project_index(root: Path, index_path: Path | None = None) -> dict[str, Any]:
    """扫描老项目目录（只读），生成 project_map.json。"""
    root = root.expanduser().resolve()
    be_root, fe_root = _detect_layout(root)
    files: list[dict] = []
    py_modules: list[dict] = []
    api_routes: list[str] = []
    vue_routes: list[str] = []

    def walk(base: Path | None, label: str) -> None:
        if not base:
            return
        for fp in base.rglob("*"):
            if not fp.is_file() or _should_skip(fp):
                continue
            if fp.suffix.lower() not in cfg.LEGACY_EXTENSIONS:
                continue
            if fp.stat().st_size > cfg.LEGACY_MAX_FILE_BYTES:
                continue
            rel = f"{label}/{fp.relative_to(base)}"
            files.append({"path": rel.replace("\\", "/"), "ext": fp.suffix, "size": fp.stat().st_size})
            if fp.suffix == ".py":
                text = fp.read_text(encoding="utf-8", errors="ignore")
                parsed = _parse_python_file(fp, text)
                if parsed["symbols"] or parsed["routes"]:
                    py_modules.append({"path": rel, **parsed})
                api_routes.extend(parsed["routes"])
            if fp.name == "index.js" and "router" in str(fp):
                vue_routes.extend(_parse_vue_routes(fp.read_text(encoding="utf-8", errors="ignore")))

    walk(be_root, "backend")
    walk(fe_root, "frontend")

    stack = "unknown"
    if fe_root and be_root:
        stack = "python+vue"
    elif fe_root:
        stack = "vue"
    elif be_root:
        stack = "python"

    index: dict[str, Any] = {
        "root": str(root),
        "stack": stack,
        "layout": {
            "backend": str(be_root) if be_root else None,
            "frontend": str(fe_root) if fe_root else None,
        },
        "file_count": len(files),
        "files_sample": files[:80],
        "python_modules": py_modules[:50],
        "api_routes": sorted(set(api_routes))[:60],
        "vue_routes": sorted(set(vue_routes))[:40],
        "dependencies": _collect_deps(root, be_root, fe_root),
    }
    if index_path:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("项目索引已写入 %s (%d 文件)", index_path, len(files))
    return index
