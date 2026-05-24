"""MCP 集成：Playwright E2E、框架文档、SQL 校验、GitHub PR。"""
from mcp_tools.github_pr import create_github_pr_from_deliver
from mcp_tools.docs import fetch_framework_docs
from mcp_tools.e2e import run_playwright_checks
from mcp_tools.sql_check import validate_backend_schema

__all__ = [
    "fetch_framework_docs",
    "run_playwright_checks",
    "validate_backend_schema",
    "create_github_pr_from_deliver",
]
