"""MCP 客户端：stdio 连接外部 MCP Server，同步封装供 pipeline 调用。"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import config as cfg

logger = logging.getLogger("multi-agent.mcp")


@dataclass
class MCPServerSpec:
    name: str
    command: str
    args: list[str]
    env: dict[str, str] = field(default_factory=dict)


def _parse_args(raw: str) -> list[str]:
    return [a.strip() for a in (raw or "").split(",") if a.strip()]


def playwright_spec() -> MCPServerSpec | None:
    if not cfg.MCP_PLAYWRIGHT_ENABLED:
        return None
    env = dict(os.environ)
    return MCPServerSpec(
        name="playwright",
        command=cfg.MCP_PLAYWRIGHT_COMMAND,
        args=_parse_args(cfg.MCP_PLAYWRIGHT_ARGS),
        env=env,
    )


def context7_spec() -> MCPServerSpec | None:
    if not cfg.MCP_CONTEXT7_ENABLED:
        return None
    env = dict(os.environ)
    if cfg.CONTEXT7_API_KEY:
        env["CONTEXT7_API_KEY"] = cfg.CONTEXT7_API_KEY
    return MCPServerSpec(
        name="context7",
        command=cfg.MCP_CONTEXT7_COMMAND,
        args=_parse_args(cfg.MCP_CONTEXT7_ARGS),
        env=env,
    )


def fetch_spec() -> MCPServerSpec | None:
    if not cfg.MCP_FETCH_ENABLED:
        return None
    return MCPServerSpec(
        name="fetch",
        command=cfg.MCP_FETCH_COMMAND,
        args=_parse_args(cfg.MCP_FETCH_ARGS),
        env=dict(os.environ),
    )


def postgres_spec() -> MCPServerSpec | None:
    if not cfg.MCP_POSTGRES_ENABLED or not cfg.MCP_POSTGRES_URI:
        return None
    env = dict(os.environ)
    env["POSTGRES_CONNECTION_STRING"] = cfg.MCP_POSTGRES_URI
    return MCPServerSpec(
        name="postgres",
        command=cfg.MCP_POSTGRES_COMMAND,
        args=_parse_args(cfg.MCP_POSTGRES_ARGS),
        env=env,
    )


def _tool_result_to_text(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    content = getattr(result, "content", None)
    if content is None and isinstance(result, dict):
        content = result.get("content")
    if not content:
        return str(result)
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict):
            text = block.get("text") or block.get("data")
            if text:
                parts.append(str(text))
        else:
            text = getattr(block, "text", None)
            if text:
                parts.append(str(text))
    return "\n".join(parts)


async def _run_session(
    spec: MCPServerSpec,
    tool_name: str,
    arguments: dict[str, Any],
) -> tuple[bool, str]:
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        return False, "未安装 mcp 包，请 pip install mcp"

    params = StdioServerParameters(
        command=spec.command,
        args=spec.args,
        env=spec.env or None,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            return True, _tool_result_to_text(result)


async def _call_tool_async(
    spec: MCPServerSpec,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    timeout: float,
) -> tuple[bool, str]:
    try:
        return await asyncio.wait_for(
            _run_session(spec, tool_name, arguments),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning("MCP %s.%s 超时", spec.name, tool_name)
        return False, f"MCP 超时 ({spec.name}.{tool_name})"
    except Exception as e:
        logger.warning("MCP %s.%s 失败: %s", spec.name, tool_name, e)
        return False, str(e)


def call_mcp_tool(
    spec: MCPServerSpec | None,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    timeout: float | None = None,
) -> tuple[bool, str]:
    """同步调用 MCP 工具；失败返回 (False, error_message)。"""
    if spec is None:
        return False, "MCP server 未启用"
    if not cfg.MCP_ENABLED:
        return False, "MCP_ENABLED=false"
    t = timeout if timeout is not None else cfg.MCP_TOOL_TIMEOUT_SEC
    try:
        return asyncio.run(_call_tool_async(spec, tool_name, arguments, timeout=t))
    except RuntimeError:
        # 已在 event loop 内（如 Streamlit）时新建 loop
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                _call_tool_async(spec, tool_name, arguments, timeout=t)
            )
        finally:
            loop.close()


def parse_jsonish(text: str) -> Any:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text
