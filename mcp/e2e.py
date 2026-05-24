"""Playwright MCP E2E 冒烟：打开页面、快照、按需求关键词校验。"""
from __future__ import annotations

import logging
import re
from typing import Any

import config as cfg
from mcp.client import call_mcp_tool, playwright_spec

logger = logging.getLogger("multi-agent.mcp")


def _requirement_checks(requirement: str) -> list[tuple[str, str]]:
    """(keyword_regex, human_desc)"""
    req = requirement or ""
    checks: list[tuple[str, str]] = []
    if re.search(r"登录|login", req, re.I):
        checks.append((r"login|登录|password|密码", "登录相关 UI"))
    if re.search(r"注销|登出|logout", req, re.I):
        checks.append((r"logout|注销|登出", "注销按钮或文案"))
    if re.search(r"注册|register", req, re.I):
        checks.append((r"register|注册", "注册相关 UI"))
    if re.search(r"笔记|notes", req, re.I):
        checks.append((r"note|笔记", "笔记相关 UI"))
    return checks


def _static_vue_checks(requirement: str, frontend_files: dict[str, str]) -> list[dict]:
    """无浏览器时的静态 DOM/模板启发式检查。"""
    defects: list[dict] = []
    vue_text = "\n".join(
        c for p, c in (frontend_files or {}).items() if p.endswith(".vue")
    )
    if not vue_text:
        return defects
    for pattern, desc in _requirement_checks(requirement):
        if not re.search(pattern, vue_text, re.I):
            defects.append(
                {
                    "id": f"E2E-static-{desc}",
                    "module": "frontend",
                    "desc": f"静态检查：前端 .vue 中未找到「{desc}」相关标记（建议配置 MCP_E2E_BASE_URL 做真实 E2E）",
                    "severity": "medium",
                    "source": "e2e_static",
                }
            )
    return defects


def _playwright_mcp_flow(base_url: str, requirement: str) -> tuple[list[dict], dict[str, Any]]:
    spec = playwright_spec()
    report: dict[str, Any] = {"base_url": base_url, "steps": [], "mode": "playwright_mcp"}
    defects: list[dict] = []

    if not spec:
        report["skipped"] = "MCP_PLAYWRIGHT_ENABLED=false"
        return defects, report

    ok, nav_msg = call_mcp_tool(
        spec,
        "browser_navigate",
        {"url": base_url},
        timeout=cfg.MCP_E2E_TIMEOUT_SEC,
    )
    report["steps"].append({"action": "navigate", "ok": ok, "detail": nav_msg[:500]})
    if not ok:
        defects.append(
            {
                "id": "E2E-nav",
                "module": "frontend",
                "desc": f"Playwright MCP 无法打开 {base_url}: {nav_msg[:200]}",
                "severity": "high",
                "source": "playwright_mcp",
            }
        )
        return defects, report

    ok2, snapshot = call_mcp_tool(
        spec,
        "browser_snapshot",
        {},
        timeout=cfg.MCP_E2E_TIMEOUT_SEC,
    )
    report["steps"].append({"action": "snapshot", "ok": ok2, "chars": len(snapshot or "")})
    snap_lower = (snapshot or "").lower()
    if not ok2 or not snapshot:
        defects.append(
            {
                "id": "E2E-snapshot",
                "module": "frontend",
                "desc": "Playwright MCP 页面快照失败",
                "severity": "high",
                "source": "playwright_mcp",
            }
        )
        return defects, report

    report["snapshot_preview"] = snapshot[:1200]
    for pattern, desc in _requirement_checks(requirement):
        if not re.search(pattern, snap_lower, re.I):
            defects.append(
                {
                    "id": f"E2E-{desc}",
                    "module": "frontend",
                    "desc": f"E2E：页面快照中未找到「{desc}」（url={base_url}）",
                    "severity": "high",
                    "source": "playwright_mcp",
                }
            )

    return defects, report


def run_playwright_checks(
    requirement: str,
    frontend_files: dict[str, str],
    *,
    base_url: str = "",
) -> tuple[list[dict], dict[str, Any]]:
    """
    E2E 检查。配置了 MCP_E2E_BASE_URL 时走 Playwright MCP；
    否则对 frontend .vue 做静态启发式检查。
    """
    url = (base_url or cfg.MCP_E2E_BASE_URL or "").strip()
    if url:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if not parsed.path or parsed.path == "/":
            url = url.rstrip("/") + "/login"
    if not cfg.MCP_PLAYWRIGHT_ENABLED and not cfg.MCP_ENABLED:
        return [], {"skipped": "playwright_disabled"}

    if url:
        try:
            return _playwright_mcp_flow(url, requirement)
        except Exception as e:
            logger.warning("Playwright MCP E2E 异常: %s", e)
            return [
                {
                    "id": "E2E-error",
                    "module": "frontend",
                    "desc": f"Playwright MCP 异常: {e}",
                    "severity": "medium",
                    "source": "playwright_mcp",
                }
            ], {"error": str(e), "base_url": url}

    if cfg.MCP_E2E_STATIC_FALLBACK:
        defects = _static_vue_checks(requirement, frontend_files)
        return defects, {"mode": "static_vue", "skipped_url": True}
    return [], {"skipped": "no MCP_E2E_BASE_URL", "hint": "设置 MCP_E2E_BASE_URL=http://localhost:5173"}
