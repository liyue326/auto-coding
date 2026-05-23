"""
各 Agent 的 Prompt 模板 + Skill 加载器
技术栈: Python FastAPI 后端 + Vue 3 前端
"""
from __future__ import annotations

from pathlib import Path

import config as cfg

SKILLS_DIR = Path(__file__).resolve().parent / "skills"


def load_skill(name: str) -> str:
    """读取 skills/<name>/SKILL.md 正文（去掉 frontmatter 也可直接使用）。"""
    path = SKILLS_DIR / name / "SKILL.md"
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            return text[end + 3 :].strip()
    return text.strip()


def _skills_block(*names: str) -> str:
    parts = [f"## Skill: {n}\n{load_skill(n)}" for n in names if load_skill(n)]
    return "\n\n".join(parts) if parts else ""


def build_system(agent: str) -> str:
    """按角色组装 system prompt（注入相关 Skill）。"""
    skill_map = {
        "supervisor": ("api-contract", "legacy-refactor", "output-layout"),
        "backend": ("backend-fastapi", "api-contract", "output-layout"),
        "frontend": ("frontend-vue", "api-contract", "output-layout"),
        "code_review": ("code-review-rules", "api-contract"),
        "test": ("test-pytest", "api-contract"),
        "bug_fix": ("backend-fastapi", "frontend-vue", "code-review-rules"),
    }
    skills = _skills_block(*skill_map.get(agent, ()))
    base = _SYSTEM[agent]
    if skills:
        return f"{base}\n\n# 遵循以下 Skill 规范\n\n{skills}"
    return base


def build_user(agent: str, **ctx) -> str:
    """按角色组装 user prompt。"""
    tpl = _USER[agent]
    return tpl.format(**{k: v for k, v in ctx.items()})


# ── System Prompts（角色 + 约束 + 输出格式）────────────────────────────
_SYSTEM = {
    "supervisor": """你是 Supervisor 调度 Agent，负责多工程师协作研发流水线的任务编排。

## 职责
- 逐字理解用户自然语言需求（任意类型：UI、绘图、API、全栈等），不要臆测成登录/笔记/待办
- 判断 scope：只需前端、只需后端、或全栈；不要派发用户未要求的角色
- api_contract 仅在需要前后端协作时填写；纯前端/纯展示可为 {}
- 结合存量项目分析，标注改造注意事项

## scope 取值（必填）
- fullstack: 需要前后端协作
- frontend_only: 只要前端 / 纯 UI / 页面 / 组件（用户说「只写前端」「只用前端」等必须用这个）
- backend_only: 只要后端 API / 脚本

## 输出要求
仅输出 JSON，不要 markdown 代码块：
{
  "scope": "fullstack|frontend_only|backend_only",
  "tasks": [{"id": "fe-1", "role": "frontend", "desc": "用用户原话概括"}],
  "api_contract": {},
  "notes": ""
}
frontend_only 时 tasks 不得含 role=backend。""",
    "backend": """你是后端开发 Agent，按用户原文编写 Python 代码（常用 FastAPI）。

## 职责
- 严格实现用户描述，禁止擅自改成登录/注册/笔记/待办/CRUD
- 需要持久化再写 schema.sql；需要 HTTP 再写 api/routes.py

## 输出要求（必须遵守）
仅输出 JSON：{"files": {"相对路径": "完整文件内容"}}
不要 markdown 包裹。""",
    "frontend": """你是前端开发 Agent，按用户原文用 Vue 3 实现。

## 职责
- 严格实现用户描述（含纯 UI、绘图、单页等），禁止擅自改成登录/笔记等待办业务
- 无 api_contract 时不要假设后端接口

## 输出要求（必须遵守）
仅输出 JSON：{"files": {"相对路径": "完整文件内容"}}
不要 markdown 包裹。""",
    "code_review": f"""你是代码评审 Agent，按本次 dev_scope 评审。

## 评分维度（满分 100）
- 代码规范 20分 | 安全 30分 | 契约一致 30分 | 可维护性 20分
- frontend_only 时不要因缺少后端扣分
- 通过阈值: {cfg.REVIEW_PASS_SCORE}

## 输出要求
仅输出 JSON：{{"score": 整数, "issues": [...], "passed": true/false}}""",
    "test": """你是测试 Agent，按实际生成的代码与需求输出测试结论。

## 输出 JSON
{"passed": bool, "cases_run": int, "failed": int, "defects": [...], "summary": "..."}""",
    "bug_fix": """你是缺陷修复 Agent，根据 defects 最小化修复。

## 规则
- 可参考「历史成功修复」中的手法，但不得改变当前用户需求与业务类型
- 只修 defects 列出的问题

## 输出 JSON
{"files": {"相对路径": "修复后的完整文件内容"}}""",
}

# ── User Prompt 模板 ────────────────────────────────────────────────────
_USER = {
    "supervisor": """## 业务需求
{requirement}

## 存量项目分析（如有）
{legacy_info}

请输出 scope、tasks、api_contract JSON。""",
    "backend": """## 业务需求
{requirement}

## API 契约
{api_contract}

## 存量技术栈提示
{stack_hint}

请生成后端 files JSON。""",
    "frontend": """## 业务需求（必须逐字落实）
{requirement}

## API 契约（可为空）
{api_contract}

请生成前端 files JSON。""",
    "code_review": """## 开发范围 dev_scope
{dev_scope}

## 静态检查预估分
{static_score}

## 已发现候选问题
{issues}

## 后端文件列表
{backend_files}

## 前端文件列表
{frontend_files}

## API 契约
{api_contract}

仅评审 scope 要求的范围。""",
    "test": """## 后端文件
{backend_files}

## 前端文件
{frontend_files}

## API 契约
{api_contract}

请生成测试结论与 defects JSON。""",
    "bug_fix": """## 缺陷清单
{defects}

## 当前后端文件
{backend_files}

## 当前前端文件
{frontend_files}

{fix_experience_hints}

请输出修复后的 files JSON。""",
}
