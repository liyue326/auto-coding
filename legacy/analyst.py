"""Project Analyst：项目结构、代码风格、可复用组件、上下文报告。"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any

import config as cfg
from legacy.indexer import IGNORE_DIRS, _detect_layout, _should_skip

logger = logging.getLogger("multi-agent.legacy")


def _read_sample(root: Path, rel_prefix: str, limit: int = 8) -> list[dict[str, str]]:
    """读取少量代表性源码用于风格推断。"""
    samples: list[dict[str, str]] = []
    if not root or not root.is_dir():
        return samples
    for fp in sorted(root.rglob("*")):
        if not fp.is_file() or _should_skip(fp):
            continue
        if fp.suffix not in (".py", ".vue", ".js", ".ts"):
            continue
        if fp.stat().st_size > 8000:
            continue
        rel = f"{rel_prefix}/{fp.relative_to(root)}".replace("\\", "/")
        try:
            text = fp.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        samples.append({"path": rel, "content": text[:4000]})
        if len(samples) >= limit:
            break
    return samples


def _infer_python_style(samples: list[dict]) -> dict[str, Any]:
    text = "\n".join(s["content"] for s in samples if s["path"].endswith(".py"))
    style: dict[str, Any] = {
        "framework": "fastapi" if "fastapi" in text.lower() or "APIRouter" in text else "python",
        "uses_type_hints": "->" in text or ": str" in text,
        "uses_pydantic": "BaseModel" in text,
        "uses_dataclass": "@dataclass" in text or "dataclass" in text,
        "error_handling": "HTTPException" in text,
        "router_pattern": "APIRouter" in text,
        "naming": "snake_case",
    }
    if re.search(r"class\s+[A-Z]\w+Service", text):
        style["service_layer"] = True
    if "models/" in "\n".join(s["path"] for s in samples):
        style["layout"] = "models + services + api/routes"
    return style


def _infer_frontend_style(samples: list[dict]) -> dict[str, Any]:
    text = "\n".join(s["content"] for s in samples if s["path"].endswith((".vue", ".js")))
    return {
        "framework": "vue3",
        "script_setup": "<script setup>" in text,
        "composition_api": "ref(" in text or "computed(" in text,
        "api_client_dir": "src/api/" if "src/api/" in "\n".join(s["path"] for s in samples) else "unknown",
        "views_dir": "src/views/" if any("src/views/" in s["path"] for s in samples) else "unknown",
        "fetch_style": "fetch(" in text or "axios" in text.lower(),
    }


def _identify_reusable_components(index: dict[str, Any]) -> list[dict[str, str]]:
    """从索引提取可复用模块/组件清单。"""
    items: list[dict[str, str]] = []
    for mod in index.get("python_modules") or []:
        path = mod.get("path", "")
        classes = [s["name"] for s in mod.get("symbols", []) if s.get("kind") == "class"]
        funcs = [s["name"] for s in mod.get("symbols", []) if s.get("kind") in ("function", "async_function")]
        if classes or funcs:
            items.append(
                {
                    "type": "python_module",
                    "path": path,
                    "symbols": ", ".join((classes + funcs)[:12]),
                    "hint": "可扩展或复用",
                }
            )
    for f in index.get("files_sample") or []:
        p = f.get("path", "")
        if "/src/api/" in p and p.endswith(".js"):
            items.append({"type": "api_client", "path": p, "hint": "前端请求封装"})
        elif "/src/views/" in p and p.endswith(".vue"):
            name = Path(p).stem
            items.append({"type": "vue_page", "path": p, "hint": f"页面组件 {name}"})
    return items[:40]


def build_analyst_report(workspace: dict[str, Any], requirement: str = "") -> dict[str, Any]:
    """
    生成项目上下文报告（确定性分析 + 索引数据）。
    供 Project Analyst Agent 落盘，并注入 Planner / Dev。
    """
    if not workspace.get("ok"):
        return {"ok": False, "error": workspace.get("error", "未准备工作区")}

    snapshot = Path(workspace["snapshot_path"])
    index = workspace.get("index") or {}
    be_root, fe_root = _detect_layout(snapshot)

    py_samples = _read_sample(be_root, "backend", 10) if be_root else []
    fe_samples = _read_sample(fe_root, "frontend", 10) if fe_root else []

    structure = {
        "root": workspace.get("source_path"),
        "stack": index.get("stack"),
        "layout": index.get("layout"),
        "file_count": index.get("file_count"),
        "backend_paths": sorted({f["path"] for f in index.get("files_sample", []) if f["path"].startswith("backend/")})[:30],
        "frontend_paths": sorted({f["path"] for f in index.get("files_sample", []) if f["path"].startswith("frontend/")})[:30],
    }
    code_style = {
        "backend": _infer_python_style(py_samples),
        "frontend": _infer_frontend_style(fe_samples),
    }
    reusable = _identify_reusable_components(index)
    constraints = [
        "原项目目录只读，所有改动写入 output/run_xxx 后须经人工确认再导出",
        "新增代码应延续现有目录约定（backend/、frontend/）",
        "优先扩展已有模块，避免重复造轮子",
    ]
    if index.get("api_routes"):
        constraints.append("已有 API 需保持兼容或显式版本前缀")
    if requirement:
        constraints.append(f"本次需求聚焦: {requirement[:200]}")

    report: dict[str, Any] = {
        "ok": True,
        "agent": "ProjectAnalyst",
        "source_path": workspace.get("source_path"),
        "workspace_id": workspace.get("workspace_id"),
        "structure": structure,
        "code_style": code_style,
        "reusable_components": reusable,
        "api_routes": index.get("api_routes", []),
        "vue_routes": index.get("vue_routes", []),
        "dependencies": index.get("dependencies", {}),
        "constraints": constraints,
        "summary": (
            f"老项目 {index.get('stack')}，约 {index.get('file_count')} 个源码文件；"
            f"后端路由 {len(index.get('api_routes', []))} 条，可复用组件 {len(reusable)} 项。"
        ),
        "recommendations_for_planner": [],
    }

    report_path = Path(workspace.get("index_path", "")).parent / "analyst_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path)
    logger.info("Project Analyst 报告: %s", report_path)
    return report


def merge_llm_analysis(report: dict[str, Any], llm_data: dict[str, Any]) -> dict[str, Any]:
    """合并 LLM 补充的摘要与建议。"""
    if not llm_data:
        return report
    out = dict(report)
    if llm_data.get("summary"):
        out["summary"] = llm_data["summary"]
    if llm_data.get("recommendations_for_planner"):
        out["recommendations_for_planner"] = llm_data["recommendations_for_planner"]
    if llm_data.get("risks"):
        out["risks"] = llm_data["risks"]
    if llm_data.get("touch_paths"):
        out["suggested_touch_paths"] = llm_data["touch_paths"]
    out["llm_enriched"] = True
    return out


def collect_code_samples(workspace: dict[str, Any], max_chars: int = 5000) -> str:
    """从快照收集代码样本文本，供 Analyst LLM 使用。"""
    if not workspace.get("ok"):
        return "（无工作区）"
    snapshot = Path(workspace["snapshot_path"])
    be_root, fe_root = _detect_layout(snapshot)
    parts: list[str] = []
    for label, root, prefix in (
        ("backend", be_root, "backend"),
        ("frontend", fe_root, "frontend"),
    ):
        if not root:
            continue
        for s in _read_sample(root, prefix, 5):
            parts.append(f"### {label}: {s['path']}\n```\n{s['content'][:1200]}\n```")
    text = "\n\n".join(parts)
    return text[:max_chars] if text else "（无代码样本）"


def format_report_for_planner(report: dict[str, Any], requirement: str = "", max_chars: int = 4500) -> str:
    """压缩为 Supervisor / Dev 可用的 Prompt 文本。"""
    if not report.get("ok"):
        return json.dumps({"error": report.get("error")}, ensure_ascii=False)[:500]

    lines = [
        f"# 项目上下文报告（Project Analyst）",
        f"来源: {report.get('source_path')}",
        f"摘要: {report.get('summary', '')}",
        f"技术栈: {(report.get('structure') or {}).get('stack')}",
    ]
    st = report.get("code_style") or {}
    if st.get("backend"):
        lines.append(f"后端风格: {json.dumps(st['backend'], ensure_ascii=False)}")
    if st.get("frontend"):
        lines.append(f"前端风格: {json.dumps(st['frontend'], ensure_ascii=False)}")
    routes = report.get("api_routes") or []
    if routes:
        lines.append("已有 API: " + ", ".join(routes[:20]))
    reuse = report.get("reusable_components") or []
    if reuse:
        lines.append("可复用组件（节选）:")
        for r in reuse[:15]:
            lines.append(f"  - [{r.get('type')}] {r.get('path')}: {r.get('symbols', r.get('hint', ''))}")
    for c in report.get("constraints") or []:
        lines.append(f"约束: {c}")
    for rec in report.get("recommendations_for_planner") or []:
        lines.append(f"Planner 建议: {rec}")
    if requirement:
        lines.append(f"\n## 本次需求\n{requirement}")
    return "\n".join(lines)[:max_chars]
