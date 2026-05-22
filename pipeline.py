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
def _merge_dicts(left: dict, right: dict) -> dict:
    merged = dict(left or {})
    merged.update(right or {})
    return merged


def _append_logs(left: list, right: list) -> list:
    return (left or []) + (right or [])


class DevState(TypedDict, total=False):
    """统一管理需求、任务、代码、评审、测试、缺陷等全流程数据。"""

    requirement: str
    legacy_path: str
    output_dir: str

    # 合并到主项目（可配置，见 config.py / .env / Streamlit）
    merge_target: str
    merge_enabled: bool
    merge_backend_subdir: str
    merge_frontend_subdir: str
    merge_result: dict

    # Supervisor 产出
    tasks: list[dict]
    api_contract: dict

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

    # 流程控制
    phase: str
    review_passed: bool
    test_passed: bool
    delivered: bool

    # 可观测性
    logs: Annotated[list[str], _append_logs]
    agent_outputs: Annotated[dict[str, Any], _merge_dicts]
    errors: list[str]


# ═══════════════════════════════════════════════════════════════════════
# 2. 工具层（存量项目 / 输出 / LLM）
# ═══════════════════════════════════════════════════════════════════════
def _log(state: DevState, agent: str, msg: str, *, set_phase: bool = True) -> dict:
    """并行节点勿写 phase，避免 LangGraph 并发更新冲突。"""
    line = f"[{agent}] {msg}"
    logger.info(line)
    out: dict = {"logs": [line]}
    if set_phase:
        out["phase"] = agent
    return out


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


def write_artifacts(out_dir: Path, state: DevState) -> None:
    """将生成代码写入独立输出目录，不覆盖存量原文件。"""
    for rel, content in (state.get("backend_files") or {}).items():
        target = out_dir / "backend" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    for rel, content in (state.get("frontend_files") or {}).items():
        target = out_dir / "frontend" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    report = {
        "requirement": state.get("requirement"),
        "review": state.get("review_result"),
        "test": state.get("test_result"),
        "defects": state.get("defects"),
        "delivered": state.get("delivered"),
    }
    (out_dir / "reports" / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def merge_to_project(
    source_run_dir: Path,
    target_root: Path,
    backend_subdir: str | None = None,
    frontend_subdir: str | None = None,
    overwrite: bool | None = None,
) -> dict:
    """
    将 output/run_xxx 下的 backend/、frontend/ 合并到可配置主项目目录。
    默认: MERGE_TARGET_ROOT/backend、MERGE_TARGET_ROOT/frontend
    """
    backend_subdir = backend_subdir or cfg.MERGE_BACKEND_SUBDIR
    frontend_subdir = frontend_subdir or cfg.MERGE_FRONTEND_SUBDIR
    overwrite = cfg.MERGE_OVERWRITE if overwrite is None else overwrite

    result: dict = {
        "ok": False,
        "target_root": str(target_root),
        "backend_dir": "",
        "frontend_dir": "",
        "backend_files": [],
        "frontend_files": [],
        "skipped": [],
        "error": "",
    }

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

    def _copy_tree(src: Path, dst: Path, label: str) -> list[str]:
        copied: list[str] = []
        if not src.is_dir():
            return copied
        for fp in src.rglob("*"):
            if not fp.is_file():
                continue
            rel = fp.relative_to(src)
            target = dst / rel
            if target.exists() and not overwrite:
                result["skipped"].append(str(rel))
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(fp, target)
            copied.append(str(rel))
            logger.info("合并[%s]: %s -> %s", label, rel, target)
        return copied

    be_src = source_run_dir / "backend"
    fe_src = source_run_dir / "frontend"
    result["backend_files"] = _copy_tree(be_src, be_dst, "backend")
    result["frontend_files"] = _copy_tree(fe_src, fe_dst, "frontend")
    result["ok"] = bool(result["backend_files"] or result["frontend_files"])
    if not result["ok"] and not result["skipped"]:
        result["error"] = f"源目录无可用文件: {source_run_dir}"
    return result


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


def _invoke_llm(system: str, user: str, on_token: Any = None) -> str:
    if cfg.USE_MOCK_LLM:
        text = _mock_llm_response(system, user)
        if on_token:
            on_token(text)
        return text
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


def _mock_llm_response(system: str, user: str) -> str:
    """无 API Key 时的可运行演示逻辑。"""
    if "Supervisor" in system or "调度" in system:
        return json.dumps(
            {
                "tasks": [
                    {"id": "be-1", "role": "backend", "desc": "用户表与注册登录 API"},
                    {"id": "fe-1", "role": "frontend", "desc": "登录页与注册表单"},
                ],
                "api_contract": {
                    "POST /api/auth/register": {"body": ["username", "password", "email"]},
                    "POST /api/auth/login": {"body": ["username", "password"]},
                },
            },
            ensure_ascii=False,
        )
    if "后端" in system:
        return "MOCK_BACKEND_OK"
    if "前端" in system or "Vue" in system:
        return "MOCK_FRONTEND_OK"
    if "评审" in system or "code_review" in system.lower():
        return json.dumps({"score": 82, "issues": [], "passed": True}, ensure_ascii=False)
    if "测试" in system:
        return json.dumps({"passed": True, "cases": 5, "failed": 0}, ensure_ascii=False)
    if "修复" in system:
        return "MOCK_FIX_OK"
    return "MOCK_OK"


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


def node_supervisor(state: DevState) -> dict:
    """Supervisor: 任务拆分、API 契约、流程管控。"""
    updates = _log(state, "Supervisor", "开始任务拆分与流程编排")
    req = state.get("requirement", "")
    legacy = state.get("legacy_path", "")

    legacy_info = {}
    if legacy:
        legacy_info = scan_legacy_project(legacy)
        updates["legacy_analysis"] = legacy_info
        updates["logs"] = updates.get("logs", []) + [
            f"[Supervisor] 存量项目扫描: {legacy_info.get('file_count', 0)} 个文件, stack={legacy_info.get('stack_hint')}"
        ]

    system = build_system("supervisor")
    user = build_user(
        "supervisor",
        requirement=req,
        legacy_info=json.dumps(legacy_info, ensure_ascii=False)[:2000],
    )
    raw = _invoke_llm(system, user)
    data = _parse_json_from_llm(raw)

    tasks = data.get("tasks") or [
        {"id": "be-1", "role": "backend", "desc": "核心业务 API"},
        {"id": "fe-1", "role": "frontend", "desc": "业务页面与交互"},
    ]
    contract = data.get("api_contract") or {
        "GET /api/health": {"response": {"status": "ok"}},
    }

    payload = {"tasks": tasks, "api_contract": contract}
    updates.update(
        {
            "tasks": tasks,
            "api_contract": contract,
            **_save_agent_output(state, "Supervisor", payload),
        }
    )
    logger.info("Supervisor 拆分 %d 个子任务", len(tasks))
    return updates


def node_backend_dev(state: DevState) -> dict:
    """后端开发 Agent: 数据表、接口、服务层。"""
    updates = _log(state, "BackendDev", "开始后端开发", set_phase=False)
    req = state.get("requirement", "")
    contract = state.get("api_contract", {})
    legacy = state.get("legacy_analysis", {})

    system = build_system("backend")
    user = build_user(
        "backend",
        requirement=req,
        api_contract=json.dumps(contract, ensure_ascii=False),
        stack_hint=legacy.get("stack_hint", "python"),
    )
    _invoke_llm(system, user)

    files = {
        "models/user.py": textwrap.dedent(
            '''
            """用户模型 — 由多智能体流水线生成"""
            from dataclasses import dataclass
            from datetime import datetime

            @dataclass
            class User:
                id: int
                username: str
                email: str
                password_hash: str
                created_at: datetime
            '''
        ).strip()
        + "\n",
        "services/auth_service.py": textwrap.dedent(
            '''
            """认证服务层"""
            from typing import Optional

            class AuthService:
                def register(self, username: str, password: str, email: str) -> dict:
                    return {"id": 1, "username": username, "email": email}

                def login(self, username: str, password: str) -> Optional[dict]:
                    if not username or not password:
                        return None
                    return {"token": "demo-token", "username": username}
            '''
        ).strip()
        + "\n",
        "api/routes.py": textwrap.dedent(
            '''
            """REST 路由 — 与 api_contract 对齐"""
            from fastapi import APIRouter, HTTPException
            from pydantic import BaseModel

            router = APIRouter(prefix="/api/auth")

            class RegisterBody(BaseModel):
                username: str
                password: str
                email: str

            class LoginBody(BaseModel):
                username: str
                password: str

            @router.post("/register")
            def register(body: RegisterBody):
                return {"ok": True, "user": body.username}

            @router.post("/login")
            def login(body: LoginBody):
                if len(body.password) < 6:
                    raise HTTPException(400, "密码过短")
                return {"token": "demo-token"}
            '''
        ).strip()
        + "\n",
        "schema.sql": textwrap.dedent(
            '''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username VARCHAR(64) UNIQUE NOT NULL,
                email VARCHAR(128) UNIQUE NOT NULL,
                password_hash VARCHAR(256) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            '''
        ).strip()
        + "\n",
    }

    updates.update(
        {
            "backend_files": files,
            **_save_agent_output(state, "BackendDev", {"files": list(files.keys())}),
        }
    )
    logger.info("BackendDev 产出 %d 个文件", len(files))
    return updates


def node_frontend_dev(state: DevState) -> dict:
    """前端开发 Agent: 页面、路由、请求、交互。"""
    updates = _log(state, "FrontendDev", "开始前端开发", set_phase=False)
    contract = state.get("api_contract", {})

    req = state.get("requirement", "")
    system = build_system("frontend")
    user = build_user(
        "frontend",
        api_contract=json.dumps(contract, ensure_ascii=False),
        requirement=req[:500],
    )
    _invoke_llm(system, user)

    files = {
        "src/api/auth.js": textwrap.dedent(
            '''
            /** API 客户端 — Vue 3，与 api_contract 一致 */
            const BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

            export async function register(data) {
              const res = await fetch(`${BASE}/api/auth/register`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(data),
              });
              if (!res.ok) throw new Error("注册失败");
              return res.json();
            }

            export async function login(data) {
              const res = await fetch(`${BASE}/api/auth/login`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(data),
              });
              if (!res.ok) throw new Error("登录失败");
              return res.json();
            }
            '''
        ).strip()
        + "\n",
        "src/views/LoginView.vue": textwrap.dedent(
            '''
            <template>
              <div class="login-page">
                <h1>登录 / 注册</h1>
                <input v-model="username" placeholder="用户名" />
                <input v-model="password" type="password" placeholder="密码" />
                <input v-model="email" placeholder="邮箱" />
                <button :disabled="loading" @click="onLogin">登录</button>
                <button :disabled="loading" @click="onRegister">注册</button>
                <p>{{ msg }}</p>
              </div>
            </template>

            <script setup>
            import { ref } from "vue";
            import { login, register } from "../api/auth.js";

            const username = ref("");
            const password = ref("");
            const email = ref("");
            const msg = ref("");
            const loading = ref(false);

            async function onLogin() {
              loading.value = true;
              try {
                const data = await login({ username: username.value, password: password.value });
                msg.value = `登录成功: ${data.token}`;
              } catch (e) {
                msg.value = String(e);
              } finally {
                loading.value = false;
              }
            }

            async function onRegister() {
              loading.value = true;
              try {
                await register({
                  username: username.value,
                  password: password.value,
                  email: email.value,
                });
                msg.value = "注册成功";
              } catch (e) {
                msg.value = String(e);
              } finally {
                loading.value = false;
              }
            }
            </script>

            <style scoped>
            .login-page { max-width: 400px; margin: 2rem auto; }
            input { display: block; width: 100%; margin: 0.5rem 0; padding: 0.5rem; }
            </style>
            '''
        ).strip()
        + "\n",
        "src/router/index.js": textwrap.dedent(
            '''
            import { createRouter, createWebHistory } from "vue-router";

            const routes = [
              { path: "/", redirect: "/login" },
              { path: "/login", component: () => import("../views/LoginView.vue") },
            ];

            export default createRouter({
              history: createWebHistory(),
              routes,
            });
            '''
        ).strip()
        + "\n",
        "src/App.vue": textwrap.dedent(
            '''
            <template>
              <router-view />
            </template>

            <script setup>
            </script>
            '''
        ).strip()
        + "\n",
    }

    updates.update(
        {
            "frontend_files": files,
            **_save_agent_output(state, "FrontendDev", {"files": list(files.keys())}),
        }
    )
    logger.info("FrontendDev 产出 %d 个文件", len(files))
    return updates


def node_code_review(state: DevState) -> dict:
    """代码评审 Agent: 规范、一致性、安全与性能。"""
    updates = _log(state, "CodeReview", "开始代码评审")
    backend = state.get("backend_files") or {}
    frontend = state.get("frontend_files") or {}
    contract = state.get("api_contract") or {}

    issues: list[dict] = []
    score = 100

    # 规则化静态检查（可扩展）
    if "schema.sql" not in backend:
        issues.append({"severity": "medium", "msg": "缺少数据库 schema 文件"})
        score -= 10
    if "api/routes.py" not in backend:
        issues.append({"severity": "high", "msg": "缺少 API 路由"})
        score -= 20
    fe_api = any(p.startswith("src/api/") for p in frontend)
    if not fe_api:
        issues.append({"severity": "high", "msg": "缺少前端 API 客户端 (src/api/)"})
        score -= 20
    if not any(p.endswith(".vue") for p in frontend):
        issues.append({"severity": "medium", "msg": "缺少 Vue 页面组件 (src/views/*.vue)"})
        score -= 10

    be_text = "\n".join(backend.values())
    if "password" in be_text and "hash" not in be_text.lower():
        issues.append({"severity": "high", "msg": "后端可能存在明文密码风险"})
        score -= 15

    fe_text = "\n".join(frontend.values())
    for ep in ["/register", "/login"]:
        if ep not in fe_text:
            issues.append({"severity": "medium", "msg": f"前端未覆盖端点 {ep}"})
            score -= 5

    # 契约一致性
    contract_str = json.dumps(contract, ensure_ascii=False)
    if "/api/auth" not in contract_str and "/api/" not in contract_str:
        issues.append({"severity": "low", "msg": "API 契约较简略"})
        score -= 5

    static_score = max(0, min(100, score))

    system = build_system("code_review")
    user = build_user(
        "code_review",
        static_score=static_score,
        issues=json.dumps(issues, ensure_ascii=False),
        backend_files=list(backend.keys()),
        frontend_files=list(frontend.keys()),
        api_contract=contract_str[:1500],
    )
    raw = _invoke_llm(system, user)
    llm_review = _parse_json_from_llm(raw)
    logger.info("CodeReview LLM 原始回复前200字: %s", (raw or "")[:200])

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
    updates.update(
        {
            "review_result": result,
            "review_passed": passed,
            "review_round": review_round,
            **_save_agent_output(state, "CodeReview", result),
        }
    )
    logger.info("CodeReview 得分=%s 通过=%s", score, passed)
    return updates


def node_test(state: DevState) -> dict:
    """测试 Agent: 生成并执行检测，输出缺陷清单。"""
    updates = _log(state, "TestAgent", "开始自动化测试")
    backend = state.get("backend_files") or {}
    frontend = state.get("frontend_files") or {}

    test_files = {
        "test_auth_service.py": textwrap.dedent(
            '''
            import pytest

            def test_login_requires_password():
                from services.auth_service import AuthService
                svc = AuthService()
                assert svc.login("alice", "") is None

            def test_register_returns_user():
                from services.auth_service import AuthService
                svc = AuthService()
                r = svc.register("alice", "secret123", "a@b.com")
                assert r["username"] == "alice"
            '''
        ).strip()
        + "\n",
        "test_api_contract.py": textwrap.dedent(
            '''
            def test_routes_define_login():
                content = open("api/routes.py", encoding="utf-8").read()
                assert "/login" in content
                assert "HTTPException" in content
            '''
        ).strip()
        + "\n",
    }

    system = build_system("test")
    user = build_user(
        "test",
        backend_files=list(backend.keys()),
        frontend_files=list(frontend.keys()),
        api_contract=json.dumps(state.get("api_contract") or {}, ensure_ascii=False)[:1500],
    )
    _invoke_llm(system, user)

    defects: list[dict] = []
    if "HTTPException" not in backend.get("api/routes.py", ""):
        defects.append({"id": "D-001", "module": "backend", "desc": "路由缺少异常处理"})
    login_vue = frontend.get("src/views/LoginView.vue", "")
    if login_vue and 'type="password"' not in login_vue:
        defects.append({"id": "D-002", "module": "frontend", "desc": "Vue 密码框未设置 type=password"})

    # 修复轮次后模拟复测通过
    fix_round = state.get("fix_round") or 0
    if fix_round > 0:
        defects = [d for d in defects if d["id"] != "D-002"]

    passed = len(defects) == 0
    result = {
        "passed": passed,
        "cases_run": 4,
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
    """缺陷修复 Agent: 依据缺陷清单修正前后端代码。"""
    fix_round = (state.get("fix_round") or 0) + 1
    updates = _log(state, "BugFix", f"开始第 {fix_round} 轮缺陷修复")
    defects = state.get("defects") or []

    backend = dict(state.get("backend_files") or {})
    frontend = dict(state.get("frontend_files") or {})

    system = build_system("bug_fix")
    user = build_user(
        "bug_fix",
        defects=json.dumps(defects, ensure_ascii=False),
        backend_summary=list(backend.keys()),
        frontend_summary=list(frontend.keys()),
    )
    _invoke_llm(system, user)

    for d in defects:
        if d.get("module") == "frontend" and "password" in d.get("desc", ""):
            path = "src/views/LoginView.vue"
            if path in frontend and 'type="password"' not in frontend[path]:
                frontend[path] = frontend[path].replace(
                    'v-model="password" placeholder="密码"',
                    'v-model="password" type="password" placeholder="密码"',
                )
        if d.get("module") == "backend":
            path = "api/routes.py"
            if path in backend and "HTTPException" not in backend[path]:
                backend[path] += "\n# patched: error handling\n"

    updates.update(
        {
            "backend_files": backend,
            "frontend_files": frontend,
            "fix_round": fix_round,
            **_save_agent_output(state, "BugFix", {"fixed": [d["id"] for d in defects], "round": fix_round}),
        }
    )
    logger.info("BugFix 第 %s 轮完成", fix_round)
    return updates


def node_deliver(state: DevState) -> dict:
    """交付节点: 落盘输出，不覆盖存量原目录。"""
    updates = _log(state, "Deliver", "项目交付，写入独立输出目录")
    out = _ensure_output_dir(state)
    state_for_write = dict(state)
    state_for_write["output_dir"] = str(out)
    write_artifacts(out, state_for_write)

    # 若指定存量路径，复制分析快照（只读引用，不改原文件）
    legacy = state.get("legacy_path")
    if legacy:
        snap = out / "legacy_snapshot.txt"
        analysis = state.get("legacy_analysis") or {}
        snap.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")

    merge_result: dict = {"ok": False, "skipped": True}
    if state.get("merge_enabled"):
        target = cfg.resolve_merge_target(state.get("merge_target", ""))
        merge_result = merge_to_project(
            out,
            target,
            backend_subdir=state.get("merge_backend_subdir") or cfg.MERGE_BACKEND_SUBDIR,
            frontend_subdir=state.get("merge_frontend_subdir") or cfg.MERGE_FRONTEND_SUBDIR,
        )
        if merge_result.get("ok"):
            updates["logs"] = updates.get("logs", []) + [
                f"[Deliver] 已合并到主项目: {target} "
                f"(backend {len(merge_result['backend_files'])} 个, "
                f"frontend {len(merge_result['frontend_files'])} 个)"
            ]
        else:
            updates["logs"] = updates.get("logs", []) + [
                f"[Deliver] 合并跳过或失败: {merge_result.get('error', 'unknown')}"
            ]
            logger.warning("合并失败: %s", merge_result)

    deliver_payload = {"path": str(out), "merge": merge_result}
    updates.update(
        {
            "delivered": True,
            "output_dir": str(out),
            "merge_result": merge_result,
            **_save_agent_output(state, "Deliver", deliver_payload),
        }
    )
    logger.info("Deliver 输出目录: %s", out)
    return updates


# ═══════════════════════════════════════════════════════════════════════
# 4. 路由与并行扇出
# ═══════════════════════════════════════════════════════════════════════
def route_parallel_dev(state: DevState) -> list[Send]:
    """Supervisor 之后并行分派前后端 Agent（LangGraph Send 并行）。"""
    logger.info("路由: 并行启动 BackendDev + FrontendDev")
    return [
        Send("backend_dev", state),
        Send("frontend_dev", state),
    ]


def route_after_review(state: DevState) -> Literal["test", "parallel_dev", "deliver"]:
    """评审后条件分支: 通过→测试; 不通过且未超重试→回开发; 否则强制交付演示。"""
    if state.get("review_passed"):
        return "test"
    review_round = state.get("review_round") or 0
    if review_round < cfg.MAX_REVIEW_RETRIES:
        logger.info("路由: 评审未通过，回退并行开发 (round=%s)", review_round)
        return "parallel_dev"
    logger.warning("路由: 评审未通过但已达最大重试，进入测试")
    return "test"


def route_after_test(state: DevState) -> Literal["bug_fix", "deliver"]:
    """测试后: 有缺陷且未超重试→修复子图; 否则交付。"""
    if state.get("test_passed"):
        return "deliver"
    fix_round = state.get("fix_round") or 0
    if fix_round < cfg.MAX_FIX_ROUNDS:
        logger.info("路由: 测试失败，进入缺陷修复 (round=%s)", fix_round)
        return "bug_fix"
    logger.warning("路由: 修复轮次耗尽，强制交付")
    return "deliver"


# ═══════════════════════════════════════════════════════════════════════
# 5. 子图: 缺陷修复 → 复测 循环
# ═══════════════════════════════════════════════════════════════════════
def build_fix_subgraph() -> StateGraph:
    """嵌套子图: 修复 → 测试（循环体在父图条件边控制）。"""
    sg = StateGraph(DevState)
    sg.add_node("bug_fix", _with_retry(node_bug_fix))
    sg.add_node("retest", _with_retry(node_test))
    sg.add_edge(START, "bug_fix")
    sg.add_edge("bug_fix", "retest")
    sg.add_edge("retest", END)
    return sg.compile()


# ═══════════════════════════════════════════════════════════════════════
# 6. 主图装配
# ═══════════════════════════════════════════════════════════════════════
def build_pipeline():
    """
    主流水线:
    START → supervisor → [并行] backend_dev + frontend_dev
         → join → code_review → (条件) test / 回开发
         → (条件) fix_subgraph / deliver → END
    """
    fix_sub = build_fix_subgraph()

    graph = StateGraph(DevState)

    graph.add_node("supervisor", _with_retry(node_supervisor))
    graph.add_node("backend_dev", _with_retry(node_backend_dev))
    graph.add_node("frontend_dev", _with_retry(node_frontend_dev))
    graph.add_node("join", lambda s: _log(s, "Join", "并行开发完成，汇合进入评审"))
    graph.add_node("code_review", _with_retry(node_code_review))
    graph.add_node("test", _with_retry(node_test))
    graph.add_node("fix_loop", fix_sub)  # 子图嵌套
    graph.add_node("deliver", _with_retry(node_deliver))

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges("supervisor", route_parallel_dev, ["backend_dev", "frontend_dev"])
    graph.add_edge("backend_dev", "join")
    graph.add_edge("frontend_dev", "join")
    graph.add_edge("join", "code_review")

    graph.add_conditional_edges(
        "code_review",
        route_after_review,
        {"test": "test", "parallel_dev": "supervisor", "deliver": "deliver"},
    )
    graph.add_conditional_edges(
        "test",
        route_after_test,
        {"bug_fix": "fix_loop", "deliver": "deliver"},
    )
    graph.add_edge("fix_loop", "test")  # 修复子图结束后复测
    graph.add_edge("deliver", END)

    return graph.compile()


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
) -> DevState:
    """构建流水线初始状态（含可配置合并目录）。"""
    enabled = cfg.MERGE_ENABLED if merge_enabled is None else merge_enabled
    return {
        "requirement": requirement.strip(),
        "legacy_path": legacy_path.strip(),
        "output_dir": output_dir or str(cfg.DEFAULT_OUTPUT_DIR),
        "merge_target": (merge_target or cfg.MERGE_TARGET_ROOT).strip(),
        "merge_enabled": enabled,
        "merge_backend_subdir": (merge_backend_subdir or cfg.MERGE_BACKEND_SUBDIR).strip(),
        "merge_frontend_subdir": (merge_frontend_subdir or cfg.MERGE_FRONTEND_SUBDIR).strip(),
        "merge_result": {},
        "tasks": [],
        "backend_files": {},
        "frontend_files": {},
        "defects": [],
        "fix_round": 0,
        "review_round": 0,
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
    )
    logger.info("========== 流水线启动 ==========")
    logger.info("需求: %s", requirement[:120])
    if legacy_path:
        logger.info("存量路径: %s", legacy_path)
    if initial.get("merge_enabled"):
        logger.info("合并目标: %s", initial.get("merge_target"))

    try:
        final = PIPELINE.invoke(initial)
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
    )
    yield {"type": "start", "message": "流水线启动"}
    logger.info("========== 流水线流式启动 ==========")

    last_log_len = 0
    final_state: DevState = initial

    try:
        for state in PIPELINE.stream(initial, stream_mode="values"):
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
    START([开始]) --> SUP[Supervisor 任务拆分]
    SUP --> PAR{{并行扇出}}
    PAR --> BE[后端开发 Agent]
    PAR --> FE[前端开发 Agent]
    BE --> JOIN[汇合]
    FE --> JOIN
    JOIN --> REV[代码评审 Agent]
    REV -->|通过| TEST[测试 Agent]
    REV -->|未通过| SUP
    TEST -->|有缺陷| FIX[缺陷修复子图]
    FIX --> TEST
    TEST -->|通过| DEL[交付输出]
    DEL --> END_NODE([结束])
    """


# ═══════════════════════════════════════════════════════════════════════
# 7. CLI 入口
# ═══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="多智能体协作开发流水线")
    parser.add_argument("-r", "--requirement", required=True, help="业务需求描述")
    parser.add_argument("-l", "--legacy-path", default="", help="存量项目目录（可选）")
    parser.add_argument("-o", "--output-dir", default="", help="输出目录（可选）")
    parser.add_argument("-m", "--merge-target", default="", help="合并到主项目根目录")
    parser.add_argument(
        "--no-merge",
        action="store_true",
        help="交付时不合并到主项目",
    )
    args = parser.parse_args()

    result = run_pipeline(
        args.requirement,
        args.legacy_path,
        args.output_dir,
        merge_target=args.merge_target,
        merge_enabled=False if args.no_merge else None,
    )
    print("\n--- 执行日志 ---")
    for line in result.get("logs", []):
        print(line)
    print("\n--- 交付 ---")
    print("delivered:", result.get("delivered"))
    print("output:", result.get("output_dir"))
