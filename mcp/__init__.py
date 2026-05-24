"""MCP 集成：Playwright E2E、框架文档、SQL 校验。"""
from mcp.docs import fetch_framework_docs
from mcp.e2e import run_playwright_checks
from mcp.sql_check import validate_backend_schema

__all__ = [
    "fetch_framework_docs",
    "run_playwright_checks",
    "validate_backend_schema",
]
