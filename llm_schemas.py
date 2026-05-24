"""各 Agent 结构化输出 Schema（配合 Function Calling / JSON Schema）。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PlannerTask(BaseModel):
    id: str = ""
    role: str = ""
    desc: str = ""


class SupervisorPlan(BaseModel):
    """Supervisor / Planner 输出。"""

    scope: str = Field(description="fullstack|frontend_only|backend_only")
    dev_scope: str = ""
    tasks: list[PlannerTask] = Field(default_factory=list)
    api_contract: dict[str, Any] = Field(default_factory=dict)
    notes: str = ""


class DevFilesOutput(BaseModel):
    """前后端开发 / BugFix 文件输出。"""

    files: dict[str, str] = Field(default_factory=dict)


class ReviewIssue(BaseModel):
    severity: str = "medium"
    msg: str = ""


class ReviewOutput(BaseModel):
    score: int = Field(ge=0, le=100, default=0)
    issues: list[ReviewIssue] = Field(default_factory=list)
    passed: bool = False


class TestDefect(BaseModel):
    id: str = ""
    module: str = "backend"
    desc: str = ""
    severity: str = "medium"


class TestOutput(BaseModel):
    passed: bool = False
    cases_run: int = 0
    failed: int = 0
    defects: list[TestDefect] = Field(default_factory=list)
    summary: str = ""


class ProjectAnalystReport(BaseModel):
    summary: str = ""
    structure_notes: str = ""
    code_style: dict[str, Any] = Field(default_factory=dict)
    reusable_components: list[dict[str, Any]] = Field(default_factory=list)
    recommendations_for_planner: list[str] = Field(default_factory=list)
    suggested_touch_paths: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
