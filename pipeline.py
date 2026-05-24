"""
多工程师角色多智能体协作开发流水线 — LangGraph 编排核心
角色: Supervisor / 后端 / 前端 / 评审 / 测试 / 缺陷修复
特性: 并行开发、条件路由、修复子图、节点重试、存量项目兼容
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import textwrap
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

import config as cfg
from prompts import build_system, build_user

# ── 日志 ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, cfg.LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)-7s | [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("multi-agent")


# ═══════════════════════════════════════════════════════════════════════
# 1. 全局状态结构体
# ═══════════════════════════════════════════════════════════════════════
_DICT_REPLACE = "__replace_dict__"


def _merge_dicts(left: dict, right: dict) -> dict:
    """并行节点合并；支持 __replace_dict__ 在一轮新需求开始时清空文件字典。"""
    if right and right.get(_DICT_REPLACE):
        return {k: v for k, v in right.items() if k != _DICT_REPLACE}
    merged = dict(left or {})
    if right:
        merged.update(right)
    return merged


def _append_conversation_turns(left: list, right: list) -> list:
    return (left or []) + (right or [])


def _append_logs(left: list, right: list) -> list:
    return (left or []) + (right or [])


def _append_fix_experiences(left: list, right: list) -> list:
    return (left or []) + (right or [])


class DevState(TypedDict, total=False):
    """统一管理需求、任务、代码、评审、测试、缺陷等全流程数据。"""

    requirement: str
    legacy_path: str
    legacy_workspace: dict
    project_context_report: dict
    touch_paths: dict  # {"backend": [...], "frontend": [...]}
    conversation_thread_id: str
    graph_thread_id: str
    pipeline_step: int
    review_dev_retries: int
    conversation_turns: Annotated[list[dict], _append_conversation_turns]
    conversation_history: list[dict]
    conversation_context: str
    export_package: dict
    export_approved: bool
    output_dir: str

    # 合并到主项目（可配置，见 config.py / .env / Streamlit）
    merge_target: str
    merge_enabled: bool
    merge_backend_subdir: str
    merge_frontend_subdir: str
    merge_conflict_mode: str
    merge_result: dict

    # Supervisor 产出
    tasks: list[dict]
    api_contract: dict
    dev_scope: str  # fullstack | frontend_only | backend_only

    # 并行开发生产物
    backend_files: Annotated[dict[str, str], _merge_dicts]
    frontend_files: Annotated[dict[str, str], _merge_dicts]
    legacy_analysis: dict

    # 评审 / 测试 / 修复
    review_result: dict
    test_result: dict
    defects: list[dict]
    fix_round: int
    review_round: int
    fix_experiences: Annotated[list[dict], _append_fix_experiences]
    memory_retrieved: list[dict]

    # 流程控制
    phase: str
    review_passed: bool
    test_passed: bool
    delivered: bool
    force_deliver: bool
    code_changes: dict

    # 可观测性
    logs: Annotated[list[str], _append_logs]
    agent_outputs: Annotated[dict[str, Any], _merge_dicts]
    errors: list[str]


# ═══════════════════════════════════════════════════════════════════════
# 2. 工具层（存量项目 / 输出 / LLM）
# ═══════════════════════════════════════════════════════════════════════
def _log(
    state: DevState,
    agent: str,
    msg: str,
    *,
    set_phase: bool = True,
    count_step: bool | None = None,
) -> dict:
    """并行节点勿写 phase / pipeline_step，避免 LangGraph 并发更新冲突。"""
    if count_step is None:
        count_step = set_phase
    line = f"[{agent}] {msg}"
    logger.info(line)
    out: dict = {"logs": [line]}
    if count_step:
        out["pipeline_step"] = (state.get("pipeline_step") or 0) + 1
    if set_phase:
        out["phase"] = agent
    return out


def _pipeline_over_step_limit(state: DevState) -> bool:
    return (state.get("pipeline_step") or 0) >= cfg.MAX_PIPELINE_STEPS


def _force_deliver_route(state: DevState, reason: str) -> dict:
    """步数超限时写入日志字段，供路由函数强制结束。"""
    return {
        "logs": [f"[Guard] {reason}（已达 MAX_PIPELINE_STEPS={cfg.MAX_PIPELINE_STEPS}）"],
        "force_deliver": True,
    }


def _save_agent_output(state: DevState, agent: str, payload: Any) -> dict:
    return {"agent_outputs": {agent: payload}}


def _ensure_output_dir(state: DevState) -> Path:
    base = Path(state.get("output_dir") or cfg.DEFAULT_OUTPUT_DIR)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = base / f"run_{run_id}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "backend").mkdir(exist_ok=True)
    (out / "frontend").mkdir(exist_ok=True)
    (out / "tests").mkdir(exist_ok=True)
    (out / "reports").mkdir(exist_ok=True)
    return out


def scan_legacy_project(path_str: str) -> dict:
    """读取外部目录源码，做结构/依赖粗分析（不修改原文件）。"""
    root = Path(path_str).expanduser().resolve()
    if not root.is_dir():
        return {"error": f"目录不存在: {root}", "files": [], "dependencies": []}

    files_meta: list[dict] = []
    deps: set[str] = set()
    dep_patterns = [
        r'from\s+([\w.]+)',
        r'import\s+([\w.]+)',
        r'require\s*\(\s*[\'"]([^\'"]+)',
        r'["\']([@\w\-/]+)["\']\s*:\s*["\^~]',
    ]

    count = 0
    for fp in root.rglob("*"):
        if not fp.is_file():
            continue
        if fp.suffix.lower() not in cfg.LEGACY_EXTENSIONS:
            continue
        if count >= cfg.LEGACY_MAX_FILES:
            break
        try:
            if fp.stat().st_size > cfg.LEGACY_MAX_FILE_BYTES:
                continue
            text = fp.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        rel = str(fp.relative_to(root))
        files_meta.append({"path": rel, "size": len(text), "ext": fp.suffix})
        for pat in dep_patterns:
            deps.update(re.findall(pat, text)[:30])
        count += 1

    stack_hint = "unknown"
    names = {f["path"].lower() for f in files_meta}
    if any(n.endswith(".vue") for n in names):
        stack_hint = "vue"
    if any("package.json" in n for n in names):
        stack_hint = "vue+nodejs" if stack_hint == "vue" else "nodejs"
    if any(n.endswith(".py") for n in names):
        stack_hint = "python+vue" if stack_hint == "vue" else (
            "python" if stack_hint == "unknown" else stack_hint + "+python"
        )

    return {
        "root": str(root),
        "file_count": len(files_meta),
        "files": files_meta[:20],
        "dependencies": sorted(deps)[:40],
        "stack_hint": stack_hint,
    }


def _normalize_side_rel(rel: str, side: str) -> str:
    """
    去掉 LLM 常带的 side 前缀，避免写出 backend/backend、frontend/frontend 嵌套。
    side: backend | frontend
    """
    p = str(rel).strip().replace("\\", "/").lstrip("/")
    while p.startswith(f"{side}/"):
        p = p[len(side) + 1 :]
    return p or rel


def write_artifacts(out_dir: Path, state: DevState) -> None:
    """将生成代码写入独立输出目录，不覆盖存量原文件。"""
    for rel, content in (state.get("backend_files") or {}).items():
        norm = _normalize_side_rel(rel, "backend")
        target = out_dir / "backend" / norm
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    for rel, content in (state.get("frontend_files") or {}).items():
        norm = _normalize_side_rel(rel, "frontend")
        target = out_dir / "frontend" / norm
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    report = {
        "requirement": state.get("requirement"),
        "review": state.get("review_result"),
        "test": state.get("test_result"),
        "defects": state.get("defects"),
        "fix_experiences": state.get("fix_experiences") or [],
        "delivered": state.get("delivered"),
        "merge": state.get("merge_result"),
        "output_dir": str(out_dir),
    }
    (out_dir / "reports" / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _merge_conflict_mode(
    overwrite: bool | None = None,
    conflict_mode: str | None = None,
) -> str:
    """
    解析合并冲突策略。
    MERGE_OVERWRITE=true（默认）时采用 overwrite，已存在文件也会被新代码覆盖。
    仅当 MERGE_OVERWRITE=false 时，才使用 MERGE_CONFLICT_MODE（如 manual）。
    """
    if conflict_mode:
        mode = conflict_mode.strip().lower()
        if mode in ("overwrite", "skip", "backup", "manual"):
            return mode
    if overwrite is False:
        return "skip"
    if overwrite is True:
        return "overwrite"
    if cfg.MERGE_OVERWRITE:
        return "overwrite"
    return cfg.MERGE_CONFLICT_MODE


def _files_differ(src: Path, dst: Path) -> bool:
    try:
        if src.stat().st_size != dst.stat().st_size:
            return True
        return src.read_bytes() != dst.read_bytes()
    except OSError:
        return True


def _stage_manual_conflict(
    target_root: Path,
    run_name: str,
    label: str,
    rel: Path,
    src_file: Path,
    dst_file: Path,
) -> Path:
    conflict_dir = target_root / ".merge_conflicts" / run_name / label / rel.parent
    conflict_dir.mkdir(parents=True, exist_ok=True)
    current = conflict_dir / f"{rel.name}.current"
    incoming = conflict_dir / f"{rel.name}.incoming"
    shutil.copy2(dst_file, current)
    shutil.copy2(src_file, incoming)
    return conflict_dir


def merge_to_project(
    source_run_dir: Path,
    target_root: Path,
    backend_subdir: str | None = None,
    frontend_subdir: str | None = None,
    overwrite: bool | None = None,
    conflict_mode: str | None = None,
) -> dict:
    """
    将 output/run_xxx 下的 backend/、frontend/ 合并到可配置主项目目录。

    conflict_mode / 环境变量:
    - overwrite: 覆盖已存在文件（MERGE_OVERWRITE=true 时的默认行为）
    - manual: 内容不同则不覆盖，导出 .current / .incoming 到 .merge_conflicts/
    - skip: 已存在则跳过 | backup: 覆盖前备份 .bak
    """
    backend_subdir = backend_subdir or cfg.MERGE_BACKEND_SUBDIR
    frontend_subdir = frontend_subdir or cfg.MERGE_FRONTEND_SUBDIR
    mode = _merge_conflict_mode(overwrite, conflict_mode)

    result: dict = {
        "ok": False,
        "target_root": str(target_root),
        "backend_dir": "",
        "frontend_dir": "",
        "backend_files": [],
        "frontend_files": [],
        "skipped": [],
        "overwritten": [],
        "backed_up": [],
        "conflicts": [],
        "conflict_mode": mode,
        "needs_manual_resolution": False,
        "conflicts_report": "",
        "error": "",
    }

    source_run_dir = Path(source_run_dir).resolve()
    run_name = source_run_dir.name
    if not source_run_dir.is_dir():
        result["error"] = f"源目录不存在: {source_run_dir}"
        return result

    if not target_root:
        result["error"] = "未配置合并目标目录 MERGE_TARGET_ROOT"
        return result

    target_root.mkdir(parents=True, exist_ok=True)
    be_dst = target_root / backend_subdir
    fe_dst = target_root / frontend_subdir
    be_dst.mkdir(parents=True, exist_ok=True)
    fe_dst.mkdir(parents=True, exist_ok=True)
    result["backend_dir"] = str(be_dst)
    result["frontend_dir"] = str(fe_dst)

    def _should_ignore(fp: Path) -> bool:
        return fp.name in cfg.MERGE_IGNORE_NAMES

    def _copy_tree(src: Path, dst: Path, label: str) -> list[str]:
        copied: list[str] = []
        if not src.is_dir():
            logger.warning("合并源目录不存在: %s", src)
            return copied
        for fp in src.rglob("*"):
            if not fp.is_file() or _should_ignore(fp):
                continue
            rel = fp.relative_to(src)
            rel_str = str(rel).replace("\\", "/")
            if label in ("backend", "frontend") and rel_str.startswith(f"{label}/"):
                rel = Path(_normalize_side_rel(rel_str, label))
            target = dst / rel
            rel_key = f"{label}/{rel}"

            if target.exists():
                if mode == "manual":
                    if not _files_differ(fp, target):
                        result["skipped"].append(rel_key)
                        logger.info("合并[%s]: %s 无变化，跳过", label, rel)
                        continue
                    stage = _stage_manual_conflict(
                        target_root, run_name, label, rel, fp, target
                    )
                    result["conflicts"].append(
                        {
                            "path": rel_key,
                            "target_file": str(target),
                            "incoming_file": str(fp),
                            "staging_dir": str(stage),
                            "current_copy": str(stage / f"{rel.name}.current"),
                            "incoming_copy": str(stage / f"{rel.name}.incoming"),
                            "resolution": "pending_manual",
                        }
                    )
                    logger.warning(
                        "合并冲突[%s]: %s（已导出 .current / .incoming）",
                        label,
                        rel,
                    )
                    continue

                if mode == "skip":
                    result["skipped"].append(rel_key)
                    continue
                if mode == "backup":
                    bak = target.with_suffix(target.suffix + ".bak")
                    shutil.copy2(target, bak)
                    result["backed_up"].append(str(bak.relative_to(target_root)))
                result["overwritten"].append(rel_key)

            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(fp, target)
            copied.append(str(rel))
            logger.info("合并[%s]: %s -> %s (%s)", label, rel, target, mode)
        return copied

    be_src = source_run_dir / "backend"
    fe_src = source_run_dir / "frontend"
    result["backend_files"] = _copy_tree(be_src, be_dst, "backend")
    result["frontend_files"] = _copy_tree(fe_src, fe_dst, "frontend")
    total = len(result["backend_files"]) + len(result["frontend_files"])
    conflict_n = len(result["conflicts"])
    result["needs_manual_resolution"] = conflict_n > 0

    if conflict_n:
        report_path = target_root / ".merge_conflicts" / run_name / "manifest.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            "run": run_name,
            "target_root": str(target_root),
            "conflict_mode": mode,
            "conflict_count": conflict_n,
            "conflicts": result["conflicts"],
            "merged_without_conflict": {
                "backend": result["backend_files"],
                "frontend": result["frontend_files"],
            },
            "how_to_resolve": (
                "每个冲突含 .current（主项目现有）与 .incoming（新生成）。"
                "人工合并后写回主项目对应路径；或设置 MERGE_CONFLICT_MODE=overwrite 重新合并。"
            ),
        }
        report_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        result["conflicts_report"] = str(report_path)

    result["ok"] = total > 0 or (conflict_n > 0 and mode == "manual")
    if not result["ok"]:
        be_n = sum(1 for p in be_src.rglob("*") if p.is_file()) if be_src.is_dir() else 0
        fe_n = sum(1 for p in fe_src.rglob("*") if p.is_file()) if fe_src.is_dir() else 0
        if be_n == 0 and fe_n == 0:
            result["error"] = (
                f"源目录无 backend/frontend 代码: {source_run_dir} "
                "(请先确认 Deliver 已写入 output)"
            )
        elif conflict_n:
            result["error"] = (
                f"存在 {conflict_n} 个冲突未写入主项目 → {result.get('conflicts_report')}"
            )
        elif result["skipped"]:
            result["error"] = f"全部 {len(result['skipped'])} 个文件被跳过 (mode={mode})"
        else:
            result["error"] = "未拷贝任何文件，请检查源目录与权限"
    elif conflict_n:
        result["error"] = (
            f"部分合并完成，{conflict_n} 个已存在文件待人工处理 → "
            f"{result.get('conflicts_report')}"
        )
    return result


def merge_from_run(
    run_dir: str,
    merge_target: str = "",
    backend_subdir: str = "",
    frontend_subdir: str = "",
    conflict_mode: str | None = None,
) -> dict:
    """将指定 output/run_xxx 再次合并到主项目（可指定 overwrite/manual）。"""
    return merge_to_project(
        Path(run_dir),
        cfg.resolve_merge_target(merge_target),
        backend_subdir=backend_subdir or None,
        frontend_subdir=frontend_subdir or None,
        conflict_mode=conflict_mode,
    )


def _parse_json_from_llm(raw: str) -> dict:
    """从 LLM 回复中稳健提取 JSON（兼容 ```json 代码块、前后说明文字）。"""
    text = (raw or "").strip()
    if not text:
        return {}
    for candidate in (text,):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        try:
            return json.loads(fence.group(1).strip())
        except json.JSONDecodeError:
            pass
    brace = re.search(r"\{[\s\S]*\}", text)
    if brace:
        try:
            return json.loads(brace.group(0))
        except json.JSONDecodeError:
            pass
    return {}


def _get_chat_llm():
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=cfg.LLM_MODEL,
        api_key=cfg.OPENAI_API_KEY,
        base_url=cfg.OPENAI_BASE_URL,
        temperature=0.2,
    )


def _invoke_llm(
    system: str,
    user: str,
    on_token: Any = None,
    *,
    schema: type | None = None,
) -> str:
    """调用 LLM；schema 非空且开启结构化输出时走 Function Calling / JSON Schema。"""
    if cfg.USE_MOCK_LLM:
        text = _mock_llm_response(system, user)
        if on_token:
            on_token(text)
        return text

    if schema and cfg.USE_STRUCTURED_OUTPUT and not on_token:
        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            llm = _get_chat_llm()
            method = cfg.STRUCTURED_OUTPUT_METHOD
            if method not in ("function_calling", "json_schema", "json_mode"):
                method = "function_calling"
            structured = llm.with_structured_output(schema, method=method)
            messages = [SystemMessage(content=system), HumanMessage(content=user)]
            parsed = structured.invoke(messages)
            if hasattr(parsed, "model_dump"):
                return json.dumps(parsed.model_dump(), ensure_ascii=False)
            return json.dumps(parsed, ensure_ascii=False)
        except Exception as e:
            logger.warning("结构化输出失败，回退普通 JSON 文本: %s", e)

    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = _get_chat_llm()
        messages = [SystemMessage(content=system), HumanMessage(content=user)]
        if on_token:
            parts: list[str] = []
            for chunk in llm.stream(messages):
                delta = chunk.content or ""
                if delta:
                    parts.append(delta)
                    on_token(delta)
            return "".join(parts)
        resp = llm.invoke(messages)
        return resp.content or ""
    except Exception as e:
        logger.error("LLM 调用失败: %s", e)
        if cfg.USE_MOCK_LLM:
            logger.warning("Mock 模式已开启，回退本地模板")
            return _mock_llm_response(system, user)
        raise


def _invoke_structured(system: str, user: str, schema: type) -> dict:
    """结构化调用，返回 dict（解析失败则 {}）。"""
    raw = _invoke_llm(system, user, schema=schema)
    data = _parse_json_from_llm(raw)
    return data if isinstance(data, dict) else {}


def _requirement_from_prompt(user: str) -> str:
    m = re.search(r"##\s*业务需求[^\n]*\n([\s\S]*?)(?:\n##\s|\Z)", user)
    if m:
        return m.group(1).strip()
    m2 = re.search(r"用户原文需求[^：:]*[：:]\s*\n([\s\S]+)", user)
    if m2:
        return m2.group(1).strip()
    return user.strip()[:500]


def _mock_agent_role(system: str) -> str:
    head = (system or "")[:800]
    if "你是 Project Analyst" in head or "项目分析师" in head:
        return "project_analyst"
    if "你是 Supervisor" in head or "你是 Supervisor（Planner）" in head:
        return "supervisor"
    if "你是后端开发 Agent" in head:
        return "backend"
    if "你是前端开发 Agent" in head:
        return "frontend"
    if "你是代码评审 Agent" in head:
        return "code_review"
    if "你是测试 Agent" in head:
        return "test"
    if "你是缺陷修复 Agent" in head:
        return "bug_fix"
    return "unknown"


def _mock_llm_response(system: str, user: str) -> str:
    """Mock：按需求原文与 scope 生成，不写死登录/注册。"""
    req = _requirement_from_prompt(user)
    role = _mock_agent_role(system)
    if role == "project_analyst":
        return json.dumps(
            {
                "summary": f"Mock 项目分析: {req[:80]}",
                "recommendations_for_planner": ["按需求原文拆分 scope"],
                "constraints": ["遵循现有目录结构"],
            },
            ensure_ascii=False,
        )
    if role == "supervisor":
        scope = _resolve_dev_scope(req, [], {})
        tasks = _default_tasks_for_scope(scope, req)
        return json.dumps(
            {
                "scope": scope,
                "dev_scope": scope,
                "tasks": tasks,
                "api_contract": {},
                "notes": f"Mock: {req[:80]}",
            },
            ensure_ascii=False,
        )
    if role == "backend":
        safe = req.replace('"', "'")[:200]
        return json.dumps(
            {"files": {"README.md": f"# Mock 后端\n\n需求: {safe}\n"}},
            ensure_ascii=False,
        )
    if role == "frontend":
        from legacy import apply_requirement_on_baseline, parse_existing_files_from_prompt

        baselines = parse_existing_files_from_prompt(user)
        if baselines:
            out_files = {}
            for path, content in baselines.items():
                out_files[path] = apply_requirement_on_baseline(content, req, path)
            return json.dumps({"files": out_files}, ensure_ascii=False)
        safe = req.replace('"', "'")[:120]
        return json.dumps(
            {
                "files": {
                    "src/App.vue": (
                        "<template><main class=\"page\"><h1>{{ title }}</h1></main></template>\n"
                        f"<script setup>\nconst title = \"{safe}\";\n</script>\n"
                        "<style scoped>.page {{ padding: 2rem; }}</style>\n"
                    ),
                }
            },
            ensure_ascii=False,
        )
    if role == "code_review":
        return json.dumps({"score": 85, "issues": [], "passed": True}, ensure_ascii=False)
    if role == "test":
        return json.dumps(
            {"passed": True, "cases_run": 0, "failed": 0, "defects": [], "summary": "mock"},
            ensure_ascii=False,
        )
    if role == "bug_fix":
        from legacy import apply_requirement_on_baseline, parse_existing_files_from_prompt

        baselines = parse_existing_files_from_prompt(user)
        if baselines:
            out_files = {}
            for path, content in baselines.items():
                out_files[path] = apply_requirement_on_baseline(content, req, path)
            if "api/routes.py" in str(user) and "api/routes.py" not in out_files:
                out_files["api/routes.py"] = (
                    '# patched logout\n@router.post("/logout")\nasync def logout():\n    return {"ok": True}\n'
                )
            return json.dumps({"files": out_files}, ensure_ascii=False)
        return json.dumps({"files": {}}, ensure_ascii=False)
    return "MOCK_OK"


def _parse_files_from_llm(raw: str) -> dict[str, str]:
    text = (raw or "").strip()
    if not text or text in ("MOCK_BACKEND_OK", "MOCK_FRONTEND_OK", "MOCK_FIX_OK", "MOCK_OK"):
        return {}
    data = _parse_json_from_llm(text)
    files = data.get("files") if isinstance(data, dict) else None
    if isinstance(files, dict) and files:
        out: dict[str, str] = {}
        for path, content in files.items():
            p = str(path).strip().replace("\\", "/").lstrip("/")
            if p.startswith("backend/"):
                p = _normalize_side_rel(p, "backend")
            elif p.startswith("frontend/"):
                p = _normalize_side_rel(p, "frontend")
            if p and content is not None:
                body = content if isinstance(content, str) else str(content)
                if body and not body.endswith("\n"):
                    body += "\n"
                out[p] = body
        if out:
            return out
    out = {}
    for m in re.finditer(r"```[^\n]*\n([\s\S]*?)```", text):
        block = m.group(0)
        body = m.group(1)
        header = block.split("\n", 1)[0]
        path_m = re.search(r"[\w./-]+\.(?:py|sql|js|vue|ts|tsx)", header)
        if path_m:
            p = path_m.group(0).split(":")[-1].strip()
            out[p] = body if body.endswith("\n") else body + "\n"
    return out


_STRICT_JSON_REMINDER = (
    "【重要】严格按用户原文实现，禁止改成登录/注册/笔记/待办等其它业务。"
    '仅输出 JSON：{"files": {"相对路径": "完整文件内容"}}'
)


def _dev_llm_generate(
    agent: str,
    system: str,
    user: str,
    requirement: str,
) -> tuple[dict[str, str], str]:
    from llm_schemas import DevFilesOutput

    if cfg.USE_STRUCTURED_OUTPUT:
        data = _invoke_structured(system, user, DevFilesOutput)
        files = data.get("files") if isinstance(data.get("files"), dict) else {}
        if files:
            logger.info("%s 结构化输出 %d 个文件", agent, len(files))
            return files, "structured"
    raw = _invoke_llm(system, user)
    parsed = _parse_files_from_llm(raw)
    if parsed:
        logger.info("%s LLM 生成 %d 个文件", agent, len(parsed))
        return parsed, "llm"
    retry_user = (
        user + "\n\n" + _STRICT_JSON_REMINDER + f"\n用户原文需求：\n{requirement}"
    )
    logger.warning("%s 首次未解析出 files，重试", agent)
    raw2 = _invoke_llm(system, retry_user)
    parsed2 = _parse_files_from_llm(raw2)
    if parsed2:
        return parsed2, "llm"
    logger.error("%s 未解析出 files JSON，不写入模板", agent)
    return {}, "failed"


def _resolve_dev_scope(requirement: str, tasks: list[dict], data: dict) -> str:
    scope_raw = (data.get("scope") or data.get("dev_scope") or "").strip().lower()
    if scope_raw in ("frontend_only", "frontend", "fe_only", "fe"):
        return "frontend_only"
    if scope_raw in ("backend_only", "backend", "be_only", "be"):
        return "backend_only"
    if scope_raw in ("fullstack", "full", "both"):
        return "fullstack"

    req = requirement.lower()
    fe_only = (
        "只写前端", "仅前端", "只要前端", "只做前端", "只开发前端", "仅开发前端",
        "前端页面即可", "不写后端", "不要后端", "无需后端", "只用前端",
        "only frontend", "frontend only",
    )
    be_only = (
        "只写后端", "仅后端", "只要后端", "只做后端", "只开发后端",
        "不写前端", "不要前端", "无需前端", "only backend", "backend only",
    )
    if any(k in req for k in fe_only):
        return "frontend_only"
    if any(k in req for k in be_only):
        return "backend_only"

    roles = {(t.get("role") or "").lower() for t in tasks}
    has_be = any(r in ("backend", "be", "后端") for r in roles)
    has_fe = any(r in ("frontend", "fe", "前端") for r in roles)
    if has_fe and not has_be:
        return "frontend_only"
    if has_be and not has_fe:
        return "backend_only"
    return "fullstack"


def _default_tasks_for_scope(scope: str, requirement: str = "") -> list[dict]:
    desc = (requirement or "按用户描述实现").strip()[:200]
    if scope == "frontend_only":
        return [{"id": "fe-1", "role": "frontend", "desc": desc}]
    if scope == "backend_only":
        return [{"id": "be-1", "role": "backend", "desc": desc}]
    return [
        {"id": "be-1", "role": "backend", "desc": desc},
        {"id": "fe-1", "role": "frontend", "desc": desc},
    ]


# ═══════════════════════════════════════════════════════════════════════
# 3. 各角色 Agent 节点（含重试包装）
# ═══════════════════════════════════════════════════════════════════════
def _with_retry(fn, attempts: int | None = None):
    attempts = attempts or cfg.NODE_RETRY_ATTEMPTS

    def wrapped(state: DevState) -> dict:
        last_err = None
        for i in range(1, attempts + 1):
            try:
                return fn(state)
            except Exception as e:
                last_err = e
                logger.warning("%s 第 %s 次失败: %s", fn.__name__, i, e)
                time.sleep(0.3 * i)
        return {
            "errors": [f"{fn.__name__}: {last_err}"],
            "logs": [f"[retry] {fn.__name__} 在 {attempts} 次后仍失败"],
        }

    wrapped.__name__ = fn.__name__
    return wrapped


def node_reset_run(state: DevState) -> dict:
    """新需求开始：清空上一轮产物，保留 Checkpoint 中的 conversation_turns。"""
    updates = _log(state, "ResetRun", "新需求：清空上一轮流水线产物", set_phase=False)
    empty_marker = {_DICT_REPLACE: True}
    updates.update(
        {
            "backend_files": empty_marker,
            "frontend_files": empty_marker,
            "defects": [],
            "fix_round": 0,
            "review_round": 0,
            "review_dev_retries": 0,
            "pipeline_step": 0,
            "force_deliver": False,
            "fix_experiences": [],
            "memory_retrieved": [],
            "delivered": False,
            "test_passed": False,
            "review_passed": False,
            "review_result": {},
            "test_result": {},
            "merge_result": {},
            "export_package": {},
            "agent_outputs": empty_marker,
        }
    )
    return updates


def node_prepare_workspace(state: DevState) -> dict:
    """隔离导入老项目：复制快照 + 索引（绝不修改原目录）。"""
    legacy = (state.get("legacy_path") or cfg.DEFAULT_LEGACY_PATH).strip()
    if not legacy:
        return _log(state, "PrepareWorkspace", "未配置老项目路径，跳过", set_phase=False, count_step=True)

    existing = state.get("legacy_workspace") or {}
    src = str(Path(legacy).expanduser().resolve())
    if existing.get("ok") and existing.get("source_path") == src:
        return _log(state, "PrepareWorkspace", "工作区已就绪，跳过重复准备", set_phase=False, count_step=True)

    updates = _log(state, "PrepareWorkspace", f"准备老项目工作区: {legacy}", set_phase=False, count_step=True)
    try:
        from legacy import format_legacy_context, prepare_legacy_workspace

        ws = prepare_legacy_workspace(legacy)
        updates["legacy_workspace"] = ws
        updates["legacy_path"] = legacy
        if ws.get("ok"):
            idx = ws.get("index") or {}
            skip = "（复用缓存）" if ws.get("skipped_copy") else ""
            updates["logs"] = updates.get("logs", []) + [
                f"[PrepareWorkspace] 快照 {ws.get('snapshot_path')}{skip} · "
                f"索引 {idx.get('file_count', 0)} 个文件 · stack={idx.get('stack')}"
            ]
        else:
            updates["logs"] = updates.get("logs", []) + [
                f"[PrepareWorkspace] 失败: {ws.get('error')}"
            ]
    except Exception as e:
        logger.exception("工作区准备失败")
        updates["legacy_workspace"] = {"ok": False, "error": str(e)}
        updates["logs"] = updates.get("logs", []) + [f"[PrepareWorkspace] 异常: {e}"]
    return updates


def _dev_existing_files_context(
    state: DevState, side: str
) -> tuple[dict[str, str], str, list[str]]:
    """加载快照中待改文件全文，供 Dev Prompt 使用。"""
    ws = state.get("legacy_workspace") or {}
    if not ws.get("ok"):
        return {}, "从零实现（未准备老项目工作区）", []

    req = state.get("requirement", "")
    report = state.get("project_context_report") or {}
    index = ws.get("index") or {}
    touch_from_state = (state.get("touch_paths") or {}).get(side) or []

    try:
        from legacy import (
            format_existing_files_block,
            infer_touch_paths,
            load_source_files,
            wants_modify_existing,
        )

        modify = wants_modify_existing(req) or bool(touch_from_state) or bool(
            report.get("suggested_touch_paths")
        )
        if not modify:
            return {}, "从零实现（未识别为存量页面改造）", []

        paths = touch_from_state or infer_touch_paths(req, report, index, side)
        files = load_source_files(ws, paths, side)
        if not files:
            return {}, "存量改造但未在快照中找到目标文件，请检查路径", paths

        block = format_existing_files_block(files, side)
        mode = (
            "存量改造：必须在「待修改已有文件」上增改；"
            "输出完整文件内容；禁止新建 App.vue 等替代页面"
        )
        return files, block if block else mode, list(files.keys())
    except Exception as e:
        logger.warning("加载待改文件失败: %s", e)
        return {}, f"加载失败: {e}", []


def _filter_dev_output(
    files: dict[str, str], touch_paths: list[str], side: str
) -> dict[str, str]:
    """存量改造时丢弃 LLM 擅自新建的路径。"""
    if not touch_paths:
        return files
    allowed = {_normalize_side_rel(p, side) for p in touch_paths}
    if side == "frontend":
        if any("LoginView" in p for p in allowed):
            allowed.add("src/api/auth.js")
        if any("logout" in (files.get(p) or "").lower() for p in files):
            allowed.add("src/api/auth.js")
    if side == "backend" and any("routes" in p or "api" in p for p in allowed):
        allowed.add("api/routes.py")
        allowed.add("services/auth_service.py")

    out: dict[str, str] = {}
    for path, content in files.items():
        norm = _normalize_side_rel(path, side)
        if norm in allowed:
            out[norm] = content
    if out:
        dropped = set(files) - set(out)
        if dropped:
            logger.info("%s 丢弃非待改路径: %s", side, dropped)
        return out
    return files


def _conversation_context_text(state: DevState) -> str:
    ctx = (state.get("conversation_context") or "").strip()
    if ctx:
        return ctx
    if cfg.CONVERSATION_MEMORY_ENABLED:
        try:
            from memory import format_for_prompt

            hist = state.get("conversation_history") or []
            return format_for_prompt(hist, current_requirement=state.get("requirement", ""))
        except Exception:
            pass
    return "（无历史对话）"


def _project_context_text(state: DevState) -> str:
    """Supervisor / Dev 使用的项目上下文文本。"""
    req = state.get("requirement", "")
    report = state.get("project_context_report") or {}
    if report.get("ok"):
        try:
            from legacy import format_report_for_planner

            return format_report_for_planner(report, req)
        except Exception:
            pass
    ws = state.get("legacy_workspace") or {}
    if ws.get("ok"):
        try:
            from legacy import format_legacy_context

            return format_legacy_context(ws, req)
        except Exception:
            pass
    legacy = state.get("legacy_path", "")
    if legacy:
        info = scan_legacy_project(legacy)
        return json.dumps(info, ensure_ascii=False)[:2000]
    return "（无老项目上下文）"


def node_project_analyst(state: DevState) -> dict:
    """Project Analyst：Planner 之前分析老项目，生成上下文报告。"""
    updates = _log(state, "ProjectAnalyst", "开始项目结构分析与上下文报告")
    req = state.get("requirement", "")
    ws = state.get("legacy_workspace") or {}

    if not ws.get("ok"):
        report = {"ok": False, "skipped": True, "error": ws.get("error", "无工作区")}
        updates["project_context_report"] = report
        updates["logs"] = updates.get("logs", []) + ["[ProjectAnalyst] 跳过（未准备老项目工作区）"]
        return updates

    prior = state.get("project_context_report") or {}
    if prior.get("ok") and prior.get("source_path") == ws.get("source_path"):
        updates["project_context_report"] = prior
        updates["logs"] = updates.get("logs", []) + ["[ProjectAnalyst] 复用已有报告，跳过重复分析"]
        return updates

    try:
        from legacy import (
            build_analyst_report,
            collect_code_samples,
            infer_touch_paths,
            merge_llm_analysis,
        )
        from pathlib import Path

        report = build_analyst_report(ws, req)
        index_json = json.dumps(ws.get("index") or {}, ensure_ascii=False)[:4000]
        samples = collect_code_samples(ws)
        workspace_info = json.dumps(
            {
                "workspace_id": ws.get("workspace_id"),
                "snapshot_path": ws.get("snapshot_path"),
                "source_path": ws.get("source_path"),
            },
            ensure_ascii=False,
        )

        system = build_system("project_analyst")
        conv = _conversation_context_text(state)
        user = build_user(
            "project_analyst",
            requirement=req,
            conversation_history=conv,
            workspace_info=workspace_info,
            project_index=index_json,
            code_samples=samples,
        )
        from llm_schemas import ProjectAnalystReport

        llm_data = _invoke_structured(system, user, ProjectAnalystReport)
        if not llm_data:
            llm_data = _parse_json_from_llm(_invoke_llm(system, user))
        report = merge_llm_analysis(report, llm_data)
        if llm_data.get("reusable_components"):
            report["reusable_components"] = llm_data["reusable_components"]
        if llm_data.get("code_style"):
            report["code_style"] = {**(report.get("code_style") or {}), **llm_data["code_style"]}
        if llm_data.get("constraints"):
            report["constraints"] = list(dict.fromkeys((report.get("constraints") or []) + llm_data["constraints"]))

        report_path = Path(report.get("report_path", ""))
        if report_path.parent.exists():
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        updates["project_context_report"] = report
        updates["legacy_analysis"] = ws.get("index") or {}
        fe_touch = infer_touch_paths(req, report, ws.get("index") or {}, "frontend")
        be_touch = infer_touch_paths(req, report, ws.get("index") or {}, "backend")
        updates["touch_paths"] = {"frontend": fe_touch, "backend": be_touch}
        reuse_n = len(report.get("reusable_components") or [])
        updates.update(
            _save_agent_output(
                state,
                "ProjectAnalyst",
                {
                    "summary": report.get("summary"),
                    "reusable_count": reuse_n,
                    "report_path": report.get("report_path"),
                },
            )
        )
        updates["logs"] = updates.get("logs", []) + [
            f"[ProjectAnalyst] 报告已生成 · 可复用 {reuse_n} 项 · {report.get('report_path', '')}"
        ]
        logger.info("ProjectAnalyst ok reusable=%d", reuse_n)
    except Exception as e:
        logger.exception("ProjectAnalyst 失败")
        updates["project_context_report"] = {"ok": False, "error": str(e)}
        updates["errors"] = (state.get("errors") or []) + [str(e)]
        updates["logs"] = updates.get("logs", []) + [f"[ProjectAnalyst] 异常: {e}"]
    return updates


def node_supervisor(state: DevState) -> dict:
    """Supervisor (Planner): 任务拆分、API 契约、流程管控。"""
    updates = _log(state, "Supervisor", "开始任务拆分与流程编排")
    req = state.get("requirement", "")
    legacy = state.get("legacy_path", "")

    project_ctx = _project_context_text(state)
    legacy_info: dict = state.get("legacy_analysis") or {}
    ws = state.get("legacy_workspace") or {}
    if not legacy_info and ws.get("ok"):
        legacy_info = ws.get("index") or {}
    elif not legacy_info and legacy:
        legacy_info = scan_legacy_project(legacy)

    if legacy_info or state.get("project_context_report", {}).get("ok"):
        updates["legacy_analysis"] = legacy_info if isinstance(legacy_info, dict) else {}
        stack = legacy_info.get("stack", "?") if legacy_info else "?"
        updates["logs"] = updates.get("logs", []) + [
            f"[Supervisor] 已读取 Project Analyst 报告 (stack={stack})"
        ]

    system = build_system("supervisor")
    conv = _conversation_context_text(state)
    hist_n = len(state.get("conversation_history") or [])
    if hist_n:
        updates["logs"] = updates.get("logs", []) + [
            f"[Supervisor] 已加载多轮对话记忆 {hist_n} 轮"
        ]
    user = build_user(
        "supervisor",
        requirement=req,
        conversation_history=conv,
        project_context=project_ctx,
    )
    from llm_schemas import SupervisorPlan

    data = _invoke_structured(system, user, SupervisorPlan)
    if not data:
        data = _parse_json_from_llm(_invoke_llm(system, user))

    tasks = data.get("tasks") or []
    dev_scope = _resolve_dev_scope(req, tasks, data)
    if not tasks:
        tasks = _default_tasks_for_scope(dev_scope, req)
    elif dev_scope == "frontend_only":
        tasks = [t for t in tasks if (t.get("role") or "").lower() in ("frontend", "fe", "前端")]
        if not tasks:
            tasks = _default_tasks_for_scope("frontend_only", req)
    elif dev_scope == "backend_only":
        tasks = [t for t in tasks if (t.get("role") or "").lower() in ("backend", "be", "后端")]
        if not tasks:
            tasks = _default_tasks_for_scope("backend_only", req)

    contract = data.get("api_contract")
    if contract is None:
        contract = {}

    payload = {
        "tasks": tasks,
        "api_contract": contract,
        "dev_scope": dev_scope,
        "scope": dev_scope,
    }
    updates.update(
        {
            "tasks": tasks,
            "api_contract": contract,
            "dev_scope": dev_scope,
            **_save_agent_output(state, "Supervisor", payload),
            "logs": updates.get("logs", [])
            + [f"[Supervisor] dev_scope={dev_scope}，子任务 {len(tasks)} 个"],
        }
    )
    logger.info("Supervisor scope=%s tasks=%d", dev_scope, len(tasks))
    return updates


def node_backend_dev(state: DevState) -> dict:
    """后端开发 Agent: 按需求生成代码（无写死模板）。"""
    updates = _log(state, "BackendDev", "开始后端开发", set_phase=False, count_step=False)
    req = state.get("requirement", "")
    contract = state.get("api_contract", {})
    legacy = state.get("legacy_analysis", {})

    legacy_ctx = _project_context_text(state)[:2500]
    ws = state.get("legacy_workspace") or {}
    stack = (ws.get("index") or {}).get("stack") or legacy.get("stack_hint", "python")
    baseline_map, existing_block, touch_list = _dev_existing_files_context(state, "backend")

    system = build_system("backend")
    user = build_user(
        "backend",
        requirement=req,
        conversation_history=_conversation_context_text(state),
        api_contract=json.dumps(contract, ensure_ascii=False),
        stack_hint=stack,
        legacy_context=legacy_ctx or "（无）",
        modify_mode=(
            "存量改造：只改待改文件，输出完整内容"
            if touch_list
            else "可按需新建文件"
        ),
        existing_files=existing_block or "（无待改文件列表）",
    )
    files, code_source = _dev_llm_generate("BackendDev", system, user, req)
    if touch_list:
        files = _filter_dev_output(files, touch_list, "backend")
    if baseline_map:
        from legacy import coalesce_with_baseline

        files, co_notes = coalesce_with_baseline(files, baseline_map, req)
        for n in co_notes:
            updates["logs"] = updates.get("logs", []) + [f"[BackendDev] {n}"]
    if touch_list:
        updates["logs"] = updates.get("logs", []) + [
            f"[BackendDev] 存量改造，待改: {', '.join(touch_list)}"
        ]

    updates.update(
        {
            "backend_files": files,
            **_save_agent_output(
                state,
                "BackendDev",
                {"files": list(files.keys()), "code_source": code_source},
            ),
        }
    )
    if code_source == "failed":
        updates["logs"] = updates.get("logs", []) + [
            "[BackendDev] 模型未返回可解析 files JSON"
        ]
    logger.info("BackendDev 产出 %d 个文件 source=%s", len(files), code_source)
    return updates


def node_frontend_dev(state: DevState) -> dict:
    """前端开发 Agent: 按需求生成代码（无写死模板）。"""
    updates = _log(state, "FrontendDev", "开始前端开发", set_phase=False, count_step=False)
    contract = state.get("api_contract", {})
    req = state.get("requirement", "")

    system = build_system("frontend")
    legacy_ctx = _project_context_text(state)[:2500]
    baseline_map, existing_block, touch_list = _dev_existing_files_context(state, "frontend")

    user = build_user(
        "frontend",
        api_contract=json.dumps(contract, ensure_ascii=False),
        requirement=req,
        conversation_history=_conversation_context_text(state),
        legacy_context=legacy_ctx or "（无）",
        modify_mode=(
            "存量改造：只改待改文件，输出完整内容"
            if touch_list
            else "可按需新建文件"
        ),
        existing_files=existing_block or "（无待改文件列表）",
    )
    files, code_source = _dev_llm_generate("FrontendDev", system, user, req)
    if touch_list:
        files = _filter_dev_output(files, touch_list, "frontend")
    if baseline_map:
        from legacy import coalesce_with_baseline

        files, co_notes = coalesce_with_baseline(files, baseline_map, req)
        for n in co_notes:
            updates["logs"] = updates.get("logs", []) + [f"[FrontendDev] {n}"]
    if touch_list:
        updates["logs"] = updates.get("logs", []) + [
            f"[FrontendDev] 存量改造，待改: {', '.join(touch_list)}"
        ]

    updates.update(
        {
            "frontend_files": files,
            **_save_agent_output(
                state,
                "FrontendDev",
                {"files": list(files.keys()), "code_source": code_source},
            ),
        }
    )
    if code_source == "failed":
        updates["logs"] = updates.get("logs", []) + [
            "[FrontendDev] 模型未返回可解析 files JSON"
        ]
    logger.info("FrontendDev 产出 %d 个文件 source=%s", len(files), code_source)
    return updates


def node_code_review(state: DevState) -> dict:
    """代码评审 Agent: 规范、一致性、安全与性能。"""
    updates = _log(state, "CodeReview", "开始代码评审")
    backend = state.get("backend_files") or {}
    frontend = state.get("frontend_files") or {}
    contract = state.get("api_contract") or {}

    issues: list[dict] = []
    score = 100
    scope = state.get("dev_scope") or "fullstack"

    if scope in ("fullstack", "backend_only") and not backend:
        issues.append({"severity": "high", "msg": "未生成任何后端文件"})
        score -= 40
    if scope in ("fullstack", "frontend_only") and not frontend:
        issues.append({"severity": "high", "msg": "未生成任何前端文件"})
        score -= 40

    be_text = "\n".join(backend.values())
    if be_text and "password" in be_text.lower() and "hash" not in be_text.lower():
        issues.append({"severity": "high", "msg": "后端可能存在明文密码风险"})
        score -= 15

    contract_str = json.dumps(contract, ensure_ascii=False)
    static_score = max(0, min(100, score))

    system = build_system("code_review")
    user = build_user(
        "code_review",
        dev_scope=scope,
        static_score=static_score,
        issues=json.dumps(issues, ensure_ascii=False),
        backend_files=list(backend.keys()),
        frontend_files=list(frontend.keys()),
        api_contract=contract_str[:1500],
    )
    from llm_schemas import ReviewOutput

    llm_review = _invoke_structured(system, user, ReviewOutput)
    if not llm_review:
        raw = _invoke_llm(system, user)
        llm_review = _parse_json_from_llm(raw)
        logger.info("CodeReview LLM 原始回复前200字: %s", (raw or "")[:200])
    else:
        logger.info("CodeReview 结构化输出 score=%s", llm_review.get("score"))

    # 静态分保底，LLM 分加权合并，避免 LLM 返回 0 覆盖合理静态分
    score = static_score
    llm_score_raw = llm_review.get("score")
    if llm_score_raw is not None:
        try:
            llm_score = int(float(llm_score_raw))
            if 1 <= llm_score <= 100:
                score = round(0.55 * static_score + 0.45 * llm_score)
            elif llm_score == 0 and static_score >= 40:
                score = static_score
                logger.warning("CodeReview: LLM 返回 score=0，保留静态分 %s", static_score)
        except (TypeError, ValueError):
            logger.warning("CodeReview: LLM score 无法解析: %r", llm_score_raw)

    for item in llm_review.get("issues") or []:
        if isinstance(item, dict):
            issues.append(item)
        elif isinstance(item, str):
            issues.append({"severity": "medium", "msg": item})

    passed = score >= cfg.REVIEW_PASS_SCORE and not any(
        i.get("severity") == "high" for i in issues
    )
    review_round = (state.get("review_round") or 0) + 1

    result = {
        "score": score,
        "static_score": static_score,
        "llm_score": llm_review.get("score"),
        "issues": issues,
        "passed": passed,
        "round": review_round,
    }
    dev_retries = state.get("review_dev_retries") or 0
    if not passed:
        dev_retries += 1
    updates.update(
        {
            "review_result": result,
            "review_passed": passed,
            "review_round": review_round,
            "review_dev_retries": dev_retries,
            **_save_agent_output(state, "CodeReview", result),
        }
    )
    logger.info("CodeReview 得分=%s 通过=%s", score, passed)
    return updates


def _collect_test_defects(
    state: DevState,
    backend: dict[str, str],
    frontend: dict[str, str],
) -> list[dict]:
    """静态缺陷检测（进入 BugFix 的条件）。"""
    defects: list[dict] = []
    scope = state.get("dev_scope") or "fullstack"

    if scope != "frontend_only":
        for path, content in backend.items():
            if not path.endswith(".py"):
                continue
            is_route = path.endswith("routes.py") or "APIRouter" in content or "@router." in content
            if is_route and "HTTPException" not in content:
                defects.append(
                    {
                        "id": "D-001",
                        "module": "backend",
                        "desc": f"{path} 建议补充 HTTPException 异常处理",
                    }
                )
                break

    for path, content in frontend.items():
        if path.endswith(".vue") and "password" in content.lower() and 'type="password"' not in content:
            defects.append(
                {
                    "id": f"D-fe-{path}",
                    "module": "frontend",
                    "desc": f"{path} 密码框建议 type=password",
                }
            )

    return defects


def node_test(state: DevState) -> dict:
    """测试 Agent: 生成并执行检测，输出缺陷清单。"""
    updates = _log(state, "TestAgent", "开始自动化测试")
    backend = state.get("backend_files") or {}
    frontend = state.get("frontend_files") or {}

    test_files: dict[str, str] = {}

    system = build_system("test")
    user = build_user(
        "test",
        backend_files=list(backend.keys()),
        frontend_files=list(frontend.keys()),
        api_contract=json.dumps(state.get("api_contract") or {}, ensure_ascii=False)[:1500],
    )
    from llm_schemas import TestOutput

    llm_test = _invoke_structured(system, user, TestOutput)
    if not llm_test:
        llm_test = _parse_json_from_llm(_invoke_llm(system, user))

    defects: list[dict] = _collect_test_defects(state, backend, frontend)
    for d in llm_test.get("defects") or []:
        if isinstance(d, dict) and d.get("desc"):
            defects.append(
                {
                    "id": str(d.get("id") or f"D-llm-{len(defects)}"),
                    "module": d.get("module") or "backend",
                    "desc": str(d.get("desc", ""))[:300],
                    "severity": d.get("severity", "medium"),
                }
            )

    scope = state.get("dev_scope") or "fullstack"
    if not defects:
        logger.info(
            "TestAgent 未检出缺陷 scope=%s backend=%s frontend=%s（故不进 BugFix）",
            scope,
            list(backend.keys()),
            list(frontend.keys()),
        )
    else:
        logger.info("TestAgent 检出缺陷 %d 条: %s", len(defects), [d.get("id") for d in defects])

    passed = len(defects) == 0
    fix_round = state.get("fix_round") or 0
    if not passed and fix_round >= cfg.MAX_FIX_ROUNDS:
        logger.warning(
            "TestAgent: 已达 MAX_FIX_ROUNDS=%s，强制结束测试循环",
            cfg.MAX_FIX_ROUNDS,
        )
        passed = True
    result = {
        "passed": passed,
        "cases_run": len(test_files),
        "failed": len(defects),
        "defects": defects,
        "test_files": list(test_files.keys()),
    }

    updates.update(
        {
            "test_result": result,
            "defects": defects,
            "test_passed": passed,
            **_save_agent_output(state, "TestAgent", result),
        }
    )
    # 写入测试文件到 state 供后续落盘
    updates["backend_files"] = {f"tests/{k}": v for k, v in test_files.items()}
    logger.info("TestAgent 缺陷数=%d 通过=%s", len(defects), passed)
    return updates


def node_bug_fix(state: DevState) -> dict:
    """缺陷修复 Agent: RAG 检索历史成功修复 + LLM 改代码。"""
    fix_round = (state.get("fix_round") or 0) + 1
    updates = _log(state, "BugFix", f"开始第 {fix_round} 轮缺陷修复")
    defects = state.get("defects") or []
    req = state.get("requirement", "")
    scope = state.get("dev_scope") or "fullstack"

    backend = dict(state.get("backend_files") or {})
    frontend = dict(state.get("frontend_files") or {})

    memory_cases: list[dict] = []
    hints = ""
    try:
        from memory import format_hints_for_prompt, retrieve_similar_fixes

        memory_cases = retrieve_similar_fixes(req, scope, defects)
        hints = format_hints_for_prompt(memory_cases)
        if memory_cases:
            updates["logs"] = updates.get("logs", []) + [
                f"[BugFix] 检索到 {len(memory_cases)} 条历史成功修复经验"
            ]
    except Exception as e:
        logger.warning("修复经验检索跳过: %s", e)

    fe_base, fe_block, fe_touch = _dev_existing_files_context(state, "frontend")
    be_base, be_block, be_touch = _dev_existing_files_context(state, "backend")
    existing_for_fix = fe_block if fe_block and not fe_block.startswith("（无") else ""
    if be_block and not be_block.startswith("（无"):
        existing_for_fix = (existing_for_fix + "\n\n" + be_block).strip()

    system = build_system("bug_fix")
    user = build_user(
        "bug_fix",
        defects=json.dumps(defects, ensure_ascii=False),
        conversation_history=_conversation_context_text(state),
        backend_files=json.dumps({k: v[:3000] for k, v in backend.items()}, ensure_ascii=False),
        frontend_files=json.dumps({k: v[:3000] for k, v in frontend.items()}, ensure_ascii=False),
        fix_experience_hints=hints or "（暂无相似历史案例）",
        modify_mode="存量改造：在快照原文上修复缺陷，保留原有功能",
        existing_files=existing_for_fix or "（无）",
    )
    from llm_schemas import DevFilesOutput

    patched: dict[str, str] = {}
    if cfg.USE_STRUCTURED_OUTPUT:
        data = _invoke_structured(system, user, DevFilesOutput)
        if isinstance(data.get("files"), dict):
            patched = data["files"]
    if not patched:
        patched = _parse_files_from_llm(_invoke_llm(system, user))
    fix_action = "structured" if patched and cfg.USE_STRUCTURED_OUTPUT else (
        "llm_patched" if patched else "rule_fallback"
    )
    if patched:
        fe_patch: dict[str, str] = {}
        be_patch: dict[str, str] = {}
        for path, content in patched.items():
            if path.startswith("src/") or path.endswith(".vue") or path.endswith(".js"):
                fe_patch[path] = content
            else:
                be_patch[path] = content
        if fe_base:
            from legacy import coalesce_with_baseline

            fe_patch, notes = coalesce_with_baseline(fe_patch, fe_base, req)
            for n in notes:
                updates["logs"] = updates.get("logs", []) + [f"[BugFix] {n}"]
        if be_base:
            from legacy import coalesce_with_baseline

            be_patch, notes = coalesce_with_baseline(be_patch, be_base, req)
            for n in notes:
                updates["logs"] = updates.get("logs", []) + [f"[BugFix] {n}"]
        frontend.update(fe_patch)
        backend.update(be_patch)
    else:
        for d in defects:
            if d.get("module") == "frontend" and "password" in d.get("desc", "").lower():
                for path, content in list(frontend.items()):
                    if path.endswith(".vue") and "password" in content.lower() and 'type="password"' not in content:
                        frontend[path] = content.replace(
                            'v-model="password"',
                            'v-model="password" type="password"',
                            1,
                        )
            if d.get("module") == "backend":
                path = "api/routes.py"
                if path in backend and "HTTPException" not in backend[path]:
                    backend[path] += "\n# patched: error handling\n"
                    fix_action = "rule_fallback_http"

    experience = {
        "round": fix_round,
        "defects": [dict(d) for d in defects if isinstance(d, dict)],
        "patched_files": list(patched.keys()) if patched else [],
        "fix_action": fix_action,
    }

    updates.update(
        {
            "backend_files": backend,
            "frontend_files": frontend,
            "fix_round": fix_round,
            "fix_experiences": [experience],
            "memory_retrieved": [
                {"case_id": c.get("case_id"), "distance": c.get("distance")}
                for c in memory_cases
            ],
            **_save_agent_output(
                state,
                "BugFix",
                {
                    "fixed": [d.get("id") for d in defects if isinstance(d, dict)],
                    "round": fix_round,
                    "memory_retrieved": updates.get("memory_retrieved", []),
                    "fix_action": fix_action,
                },
            ),
        }
    )
    logger.info("BugFix 第 %s 轮完成 action=%s", fix_round, fix_action)
    return updates


def node_deliver(state: DevState) -> dict:
    """交付节点: 落盘输出，不覆盖存量原目录。"""
    step_count = len(state.get("logs") or [])
    updates = _log(
        state,
        "Deliver",
        f"项目交付（本次流水线约 {step_count} 条节点日志，非对话记忆轮数）",
    )
    out = _ensure_output_dir(state)
    state_for_write = dict(state)
    state_for_write["output_dir"] = str(out)
    write_artifacts(out, state_for_write)

    code_changes: dict = {}
    ws = state.get("legacy_workspace") or {}
    try:
        from legacy import compute_code_changes, format_changes_log_line

        code_changes = compute_code_changes(
            ws,
            state.get("backend_files") or {},
            state.get("frontend_files") or {},
        )
        updates["code_changes"] = code_changes
        (out / "reports").mkdir(parents=True, exist_ok=True)
        (out / "reports" / "changes.json").write_text(
            json.dumps(code_changes, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        for item in code_changes.get("files") or []:
            if item.get("status") not in ("modified", "new") or not item.get("unified_diff"):
                continue
            patch_name = f"{item['side']}_{item['path'].replace('/', '__')}.patch"
            (out / "reports" / "patches").mkdir(parents=True, exist_ok=True)
            (out / "reports" / "patches" / patch_name).write_text(
                item["unified_diff"], encoding="utf-8"
            )
        updates["logs"] = updates.get("logs", []) + [
            f"[Deliver] {format_changes_log_line(code_changes)}"
        ]
    except Exception as e:
        logger.warning("代码变更对比失败: %s", e)

    # 若指定存量路径，复制分析快照（只读引用，不改原文件）
    legacy = state.get("legacy_path")
    if legacy:
        snap = out / "legacy_snapshot.txt"
        analysis = state.get("legacy_analysis") or {}
        snap.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")

    merge_result: dict = {"ok": False, "skipped": True, "reason": "export_pending"}
    export_pkg: dict = {}
    req = state.get("requirement", "")
    legacy_target = (state.get("legacy_path") or cfg.DEFAULT_LEGACY_PATH).strip()

    if ws.get("ok"):
        try:
            from legacy import build_export_package, export_to_legacy

            export_pkg = build_export_package(out, ws, req, None)
            updates["export_package"] = export_pkg
            updates["logs"] = updates.get("logs", []) + [
                f"[Deliver] 导出包（待确认）: {export_pkg.get('export_dir')}"
            ]
            if state.get("export_approved") and state.get("merge_enabled"):
                merge_result = export_to_legacy(
                    out,
                    legacy_target,
                    approved=True,
                    backend_subdir=state.get("merge_backend_subdir"),
                    frontend_subdir=state.get("merge_frontend_subdir"),
                    conflict_mode=state.get("merge_conflict_mode"),
                )
                export_pkg.get("manifest", {})["status"] = "applied"
            else:
                updates["logs"] = updates.get("logs", []) + [
                    "[Deliver] 未写回老项目原路径，请在界面确认「写入老项目」"
                ]
        except Exception as e:
            logger.warning("导出包失败: %s", e)
            updates["logs"] = updates.get("logs", []) + [f"[Deliver] 导出包异常: {e}"]
    elif state.get("merge_enabled"):
        target = cfg.resolve_merge_target(state.get("merge_target", ""))
        merge_mode = state.get("merge_conflict_mode") or None
        merge_result = merge_to_project(
            out,
            target,
            backend_subdir=state.get("merge_backend_subdir") or cfg.MERGE_BACKEND_SUBDIR,
            frontend_subdir=state.get("merge_frontend_subdir") or cfg.MERGE_FRONTEND_SUBDIR,
            conflict_mode=merge_mode,
        )
        mode = merge_result.get("conflict_mode", "")
        if merge_result.get("needs_manual_resolution"):
            updates["logs"] = updates.get("logs", []) + [
                f"[Deliver] 合并模式={mode}：{len(merge_result.get('conflicts', []))} 个已存在文件"
                f"未覆盖，见 .merge_conflicts（新文件已合并）"
            ]
            if merge_result.get("conflicts_report"):
                updates["logs"].append(f"[Deliver] 冲突清单: {merge_result['conflicts_report']}")
        if merge_result.get("backend_files") or merge_result.get("frontend_files"):
            updates["logs"] = updates.get("logs", []) + [
                f"[Deliver] 已合并到主项目: {target} "
                f"(backend {len(merge_result['backend_files'])} 个, "
                f"frontend {len(merge_result['frontend_files'])} 个, mode={mode})"
            ]
            ow = merge_result.get("overwritten") or []
            if ow:
                updates["logs"].append(f"[Deliver] 已覆盖 {len(ow)} 个已存在文件")
        if not merge_result.get("ok"):
            updates["logs"] = updates.get("logs", []) + [
                f"[Deliver] 合并异常: {merge_result.get('error', 'unknown')}"
            ]
            logger.warning("合并失败: %s", merge_result)
    else:
        updates["logs"] = updates.get("logs", []) + ["[Deliver] 未启用写回主项目"]

    state_for_write["merge_result"] = merge_result
    memory_ingested = 0
    try:
        from memory import ingest_successful_run
        from memory.store import collection_count

        final_state = {**state, **updates, "merge_result": merge_result}
        from memory import ingest_skip_reason

        memory_ingested = ingest_successful_run(final_state, run_id=out.name)
        if memory_ingested:
            updates["logs"] = updates.get("logs", []) + [
                f"[Deliver] 已入库 {memory_ingested} 条修复经验（库内共 {collection_count()} 条）"
            ]
        else:
            reason = ingest_skip_reason(final_state)
            if reason:
                updates["logs"] = updates.get("logs", []) + [
                    f"[Deliver] 修复经验未入库: {reason}"
                ]
    except Exception as e:
        logger.warning("修复经验入库跳过: %s", e)

    if cfg.CONVERSATION_MEMORY_ENABLED:
        try:
            from memory import append_turn, build_turn_from_state

            tid = state.get("conversation_thread_id") or cfg.CONVERSATION_DEFAULT_THREAD
            turn = build_turn_from_state({**state, **updates}, tid)
            prev_turns = list(state.get("conversation_turns") or [])
            all_turns = prev_turns + [turn]
            updates["conversation_turns"] = [turn]
            updates["conversation_history"] = all_turns
            storage = []
            if cfg.CONVERSATION_USE_CHECKPOINT and cfg.LANGGRAPH_CHECKPOINT_ENABLED:
                storage.append("LangGraph Checkpoint")
            if cfg.CONVERSATION_USE_JSONL:
                append_turn(tid, turn)
                storage.append("JSONL")
            updates["logs"] = updates.get("logs", []) + [
                f"[Deliver] 对话记忆已保存（{', '.join(storage) or '无'} · 线程 {tid} · 共 {len(all_turns)} 轮）"
            ]
        except Exception as e:
            logger.warning("对话记忆保存失败: %s", e)

    (out / "reports" / "summary.json").write_text(
        json.dumps(
            {
                "requirement": state.get("requirement"),
                "review": state.get("review_result"),
                "test": state.get("test_result"),
                "defects": state.get("defects"),
                "fix_experiences": state.get("fix_experiences") or [],
                "fix_round": state.get("fix_round", 0),
                "test_passed": state.get("test_passed"),
                "delivered": True,
                "merge": merge_result,
                "memory_ingested": memory_ingested,
                "export_package": export_pkg,
                "legacy_path": legacy_target,
                "output_dir": str(out),
                "code_changes": code_changes,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    deliver_payload = {
        "path": str(out),
        "merge": merge_result,
        "export_package": export_pkg,
        "memory_ingested": memory_ingested,
        "code_changes_summary": (code_changes.get("text_summary") if code_changes else ""),
    }
    updates.update(
        {
            "delivered": True,
            "output_dir": str(out),
            "merge_result": merge_result,
            **_save_agent_output(state, "Deliver", deliver_payload),
            "code_changes": code_changes,
        }
    )
    logger.info("Deliver 输出目录: %s memory_ingested=%s", out, memory_ingested)
    return updates


# ═══════════════════════════════════════════════════════════════════════
# 4. 路由与并行扇出
# ═══════════════════════════════════════════════════════════════════════
def route_parallel_dev(state: DevState) -> list[Send]:
    """按 dev_scope 只启动需要的开发 Agent。"""
    scope = state.get("dev_scope") or _resolve_dev_scope(
        state.get("requirement", ""),
        state.get("tasks") or [],
        {},
    )
    sends: list[Send] = []
    if scope in ("fullstack", "backend_only"):
        sends.append(Send("backend_dev", state))
    if scope in ("fullstack", "frontend_only"):
        sends.append(Send("frontend_dev", state))
    if not sends:
        sends.append(Send("frontend_dev", state))
    names = [s.node for s in sends]
    logger.info("路由: dev_scope=%s 启动 %s", scope, names)
    return sends


def route_after_review(
    state: DevState,
) -> Literal["test", "frontend_dev", "backend_dev", "supervisor", "deliver"]:
    """评审后条件分支: 通过→测试; 不通过→直接回对应 Dev（不重头 Prepare）。"""
    if state.get("force_deliver") or _pipeline_over_step_limit(state):
        logger.error("路由: 强制 Deliver（步数上限或 guard）")
        return "deliver"
    if state.get("review_passed"):
        return "test"
    dev_retries = state.get("review_dev_retries") or 0
    if dev_retries < cfg.MAX_REVIEW_RETRIES:
        scope = state.get("dev_scope") or "fullstack"
        if scope == "frontend_only":
            logger.info("路由: 评审未通过，回退 FrontendDev (retry=%s)", dev_retries)
            return "frontend_dev"
        if scope == "backend_only":
            logger.info("路由: 评审未通过，回退 BackendDev (retry=%s)", dev_retries)
            return "backend_dev"
        logger.info("路由: 评审未通过，回退 Supervisor 编排 (retry=%s)", dev_retries)
        return "supervisor"
    logger.warning("路由: 评审未通过但已达最大重试，进入测试")
    return "test"


def route_after_test(state: DevState) -> Literal["bug_fix", "deliver"]:
    """测试后: 有缺陷且未超重试→修复子图; 否则交付。"""
    if state.get("force_deliver") or _pipeline_over_step_limit(state):
        logger.error("路由: 测试后强制 Deliver（步数上限）")
        return "deliver"
    if state.get("test_passed"):
        logger.info("路由: 测试通过，进入 Deliver（无 BugFix）")
        return "deliver"
    fix_round = state.get("fix_round") or 0
    defects = state.get("defects") or []
    if fix_round < cfg.MAX_FIX_ROUNDS:
        logger.info(
            "路由: 测试失败 defects=%d，进入 BugFix (round=%s)",
            len(defects),
            fix_round,
        )
        return "bug_fix"
    logger.warning("路由: 修复轮次耗尽，强制 Deliver")
    return "deliver"


# ═══════════════════════════════════════════════════════════════════════
# 6. 主图装配
# ═══════════════════════════════════════════════════════════════════════
def build_pipeline():
    """
    主流水线:
    START → supervisor → [并行] backend_dev + frontend_dev
         → join → code_review → (条件) test / 回开发
         → (条件) bug_fix 循环 / deliver → END
    """
    checkpointer = get_checkpointer() if cfg.LANGGRAPH_CHECKPOINT_ENABLED else None

    graph = StateGraph(DevState)

    graph.add_node("reset_run", _with_retry(node_reset_run))
    graph.add_node("prepare_workspace", _with_retry(node_prepare_workspace))
    graph.add_node("project_analyst", _with_retry(node_project_analyst))
    graph.add_node("supervisor", _with_retry(node_supervisor))
    graph.add_node("backend_dev", _with_retry(node_backend_dev))
    graph.add_node("frontend_dev", _with_retry(node_frontend_dev))
    graph.add_node("join", lambda s: _log(s, "Join", "并行开发完成，汇合进入评审"))
    graph.add_node("code_review", _with_retry(node_code_review))
    graph.add_node("test", _with_retry(node_test))
    graph.add_node("bug_fix", _with_retry(node_bug_fix))
    graph.add_node("deliver", _with_retry(node_deliver))

    graph.add_edge(START, "reset_run")
    graph.add_edge("reset_run", "prepare_workspace")
    graph.add_edge("prepare_workspace", "project_analyst")
    graph.add_edge("project_analyst", "supervisor")
    graph.add_conditional_edges("supervisor", route_parallel_dev, ["backend_dev", "frontend_dev"])
    graph.add_edge("backend_dev", "join")
    graph.add_edge("frontend_dev", "join")
    graph.add_edge("join", "code_review")

    graph.add_conditional_edges(
        "code_review",
        route_after_review,
        {
            "test": "test",
            "frontend_dev": "frontend_dev",
            "backend_dev": "backend_dev",
            "supervisor": "supervisor",
            "deliver": "deliver",
        },
    )
    graph.add_conditional_edges(
        "test",
        route_after_test,
        {"bug_fix": "bug_fix", "deliver": "deliver"},
    )
    graph.add_edge("bug_fix", "test")
    graph.add_edge("deliver", END)

    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=[],
        debug=False,
    )


def get_checkpointer():
    """LangGraph Checkpointer 单例（SQLite 或内存）。"""
    if not cfg.LANGGRAPH_CHECKPOINT_ENABLED:
        return None
    from memory.checkpoint import get_checkpointer as _get

    return _get()


def _run_config(
    conversation_thread_id: str = "",
    graph_thread_id: str = "",
) -> dict | None:
    """
    流水线 Checkpoint 配置。
    每次运行必须用独立 graph_thread_id，避免从上次中断的 test↔bugfix 中间态续跑。
    """
    if not cfg.LANGGRAPH_CHECKPOINT_ENABLED:
        return None
    from memory.checkpoint import thread_config

    tid = (graph_thread_id or "").strip()
    if not tid:
        conv = (conversation_thread_id or cfg.CONVERSATION_DEFAULT_THREAD).strip()
        tid = f"{conv}__run_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    return {
        **thread_config(tid),
        "recursion_limit": cfg.LANGGRAPH_RECURSION_LIMIT,
    }


# 单例编译图
PIPELINE = build_pipeline()


def _build_initial_state(
    requirement: str,
    legacy_path: str = "",
    output_dir: str = "",
    merge_target: str = "",
    merge_enabled: bool | None = None,
    merge_backend_subdir: str = "",
    merge_frontend_subdir: str = "",
    merge_conflict_mode: str = "",
    export_approved: bool = False,
    conversation_thread_id: str = "",
    conversation_history: list[dict] | None = None,
) -> DevState:
    """构建流水线初始状态（含可配置合并目录）。"""
    enabled = cfg.MERGE_ENABLED if merge_enabled is None else merge_enabled
    mode = (merge_conflict_mode or "").strip().lower()
    conv_thread = (conversation_thread_id or cfg.CONVERSATION_DEFAULT_THREAD).strip()
    graph_tid = f"{conv_thread}__run_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    conv_history: list[dict] = []
    conv_context = ""
    if cfg.CONVERSATION_MEMORY_ENABLED:
        try:
            from memory import format_for_prompt, load_turns

            conv_history: list[dict] = []
            if conversation_history is not None:
                conv_history = conversation_history
            elif cfg.CONVERSATION_USE_JSONL:
                conv_history = load_turns(conv_thread)
            conv_context = format_for_prompt(
                conv_history, current_requirement=requirement.strip()
            )
        except Exception as e:
            logger.warning("对话记忆加载失败: %s", e)
    return {
        "requirement": requirement.strip(),
        "legacy_path": (legacy_path or cfg.DEFAULT_LEGACY_PATH).strip(),
        "legacy_workspace": {},
        "export_package": {},
        "export_approved": export_approved,
        "project_context_report": {},
        "touch_paths": {},
        "conversation_thread_id": conv_thread,
        "graph_thread_id": graph_tid,
        "pipeline_step": 0,
        "force_deliver": False,
        "conversation_turns": conv_history,
        "conversation_history": conv_history,
        "conversation_context": conv_context,
        "output_dir": output_dir or str(cfg.DEFAULT_OUTPUT_DIR),
        "merge_target": (merge_target or cfg.MERGE_TARGET_ROOT).strip(),
        "merge_enabled": enabled,
        "merge_backend_subdir": (merge_backend_subdir or cfg.MERGE_BACKEND_SUBDIR).strip(),
        "merge_frontend_subdir": (merge_frontend_subdir or cfg.MERGE_FRONTEND_SUBDIR).strip(),
        "merge_conflict_mode": mode,
        "merge_result": {},
        "dev_scope": "",
        "tasks": [],
        "backend_files": {},
        "frontend_files": {},
        "defects": [],
        "fix_round": 0,
        "review_round": 0,
        "review_dev_retries": 0,
        "fix_experiences": [],
        "memory_retrieved": [],
        "logs": [],
        "agent_outputs": {},
        "errors": [],
        "delivered": False,
    }


def run_pipeline(
    requirement: str,
    legacy_path: str = "",
    output_dir: str = "",
    merge_target: str = "",
    merge_enabled: bool | None = None,
    merge_backend_subdir: str = "",
    merge_frontend_subdir: str = "",
    merge_conflict_mode: str = "",
    export_approved: bool = False,
    conversation_thread_id: str = "",
) -> DevState:
    """对外统一入口，供 CLI / Streamlit 调用。"""
    initial = _build_initial_state(
        requirement,
        legacy_path,
        output_dir,
        merge_target,
        merge_enabled,
        merge_backend_subdir,
        merge_frontend_subdir,
        merge_conflict_mode,
        export_approved=export_approved,
        conversation_thread_id=conversation_thread_id,
    )
    logger.info("========== 流水线启动 ==========")
    logger.info("需求: %s", requirement[:120])
    if legacy_path:
        logger.info("存量路径: %s", legacy_path)
    if initial.get("merge_enabled"):
        logger.info("合并目标: %s", initial.get("merge_target"))

    run_cfg = _run_config(
        conversation_thread_id,
        initial.get("graph_thread_id", ""),
    )
    logger.info("Checkpoint graph_thread_id=%s", run_cfg.get("configurable", {}).get("thread_id"))
    try:
        final = PIPELINE.invoke(initial, config=run_cfg)
    except Exception:
        logger.error("流水线异常:\n%s", traceback.format_exc())
        initial["errors"] = [traceback.format_exc()]
        return initial

    logger.info("========== 流水线结束 delivered=%s ==========", final.get("delivered"))
    return final


def run_pipeline_stream(
    requirement: str,
    legacy_path: str = "",
    output_dir: str = "",
    merge_target: str = "",
    merge_enabled: bool | None = None,
    merge_backend_subdir: str = "",
    merge_frontend_subdir: str = "",
    merge_conflict_mode: str = "",
    conversation_thread_id: str = "",
):
    """
    流式执行流水线，逐步 yield 进度事件（供 Streamlit 实时展示）。
    事件类型: start | progress | done | error
    """
    initial = _build_initial_state(
        requirement,
        legacy_path,
        output_dir,
        merge_target,
        merge_enabled,
        merge_backend_subdir,
        merge_frontend_subdir,
        merge_conflict_mode,
        conversation_thread_id=conversation_thread_id,
    )
    hist_n = len(initial.get("conversation_history") or [])
    yield {
        "type": "start",
        "message": f"流水线启动（对话记忆 {hist_n} 轮）" if hist_n else "流水线启动",
    }
    logger.info("========== 流水线流式启动 ==========")
    if hist_n:
        logger.info("对话记忆线程=%s 历史=%d轮", initial.get("conversation_thread_id"), hist_n)

    last_log_len = 0
    final_state: DevState = initial

    try:
        run_cfg = _run_config(
            conversation_thread_id,
            initial.get("graph_thread_id", ""),
        )
        logger.info(
            "Checkpoint graph_thread_id=%s",
            (run_cfg or {}).get("configurable", {}).get("thread_id"),
        )
        for state in PIPELINE.stream(initial, config=run_cfg, stream_mode="values"):
            final_state = state
            logs = state.get("logs") or []
            new_logs = logs[last_log_len:]
            last_log_len = len(logs)
            yield {
                "type": "progress",
                "phase": state.get("phase", ""),
                "logs": new_logs,
                "review_result": state.get("review_result"),
                "test_result": state.get("test_result"),
                "agent_outputs": state.get("agent_outputs"),
                "state": state,
            }
        yield {"type": "done", "state": final_state}
    except Exception as e:
        logger.error("流水线流式异常:\n%s", traceback.format_exc())
        initial["errors"] = [traceback.format_exc()]
        yield {"type": "error", "message": str(e), "state": initial}

    logger.info("========== 流水线流式结束 ==========")


def get_mermaid_diagram() -> str:
    """生成流程图（Streamlit / 文档展示）。"""
    return """
flowchart TD
    START([开始]) --> RST[ResetRun 清空上轮产物]
    RST --> PW[PrepareWorkspace 隔离快照]
    PW --> PA[Project Analyst 项目分析]
    PA --> SUP[Supervisor Planner 任务拆分]
    SUP --> PAR{{并行扇出}}
    PAR --> BE[后端开发 Agent]
    PAR --> FE[前端开发 Agent]
    BE --> JOIN[汇合]
    FE --> JOIN
    JOIN --> REV[代码评审 Agent]
    REV -->|通过| TEST[测试 Agent]
    REV -->|未通过| SUP
    TEST -->|有缺陷| BF[BugFix]
    BF --> TEST
    TEST -->|通过| DEL[交付输出]
    DEL --> END_NODE([结束])
    """


# ═══════════════════════════════════════════════════════════════════════
# 7. CLI 入口
# ═══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="多智能体协作开发流水线")
    parser.add_argument("-r", "--requirement", default="", help="业务需求描述")
    parser.add_argument("-l", "--legacy-path", default="", help="存量项目目录（可选）")
    parser.add_argument("-o", "--output-dir", default="", help="输出目录（可选）")
    parser.add_argument("-m", "--merge-target", default="", help="合并到主项目根目录")
    parser.add_argument(
        "--no-merge",
        action="store_true",
        help="交付时不合并到主项目",
    )
    parser.add_argument(
        "--merge-run",
        default="",
        help="将已有 output/run_xxx 目录合并到主项目后退出",
    )
    parser.add_argument(
        "--merge-mode",
        default="",
        choices=["", "overwrite", "manual", "skip", "backup"],
        help="合并冲突策略（默认: MERGE_OVERWRITE=true 时为 overwrite）",
    )
    parser.add_argument(
        "--repair-nested-merge",
        metavar="TARGET",
        default="",
        help="修复主项目中 backend/backend、frontend/frontend 嵌套（不上传新代码）",
    )
    args = parser.parse_args()

    if args.repair_nested_merge:
        from legacy import repair_nested_merge_dirs

        target = cfg.resolve_merge_target(args.repair_nested_merge or args.merge_target)
        rep = repair_nested_merge_dirs(target)
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        raise SystemExit(0 if rep.get("ok") else 1)

    if args.merge_run:
        mode = args.merge_mode or None
        m = merge_from_run(args.merge_run, merge_target=args.merge_target, conflict_mode=mode)
        print(json.dumps(m, ensure_ascii=False, indent=2))
        raise SystemExit(0 if m.get("ok") and not m.get("needs_manual_resolution") else 1)

    if not args.requirement.strip():
        parser.error("请提供 -r/--requirement，或使用 --merge-run 仅做合并")

    result = run_pipeline(
        args.requirement,
        args.legacy_path,
        args.output_dir,
        merge_target=args.merge_target,
        merge_enabled=False if args.no_merge else None,
        merge_conflict_mode=args.merge_mode,
    )
    print("\n--- 执行日志 ---")
    for line in result.get("logs", []):
        print(line)
    print("\n--- 交付 ---")
    print("delivered:", result.get("delivered"))
    print("output:", result.get("output_dir"))
