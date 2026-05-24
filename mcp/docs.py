"""框架文档检索：Context7 MCP + Fetch MCP + 内置摘要回退。"""
from __future__ import annotations

import logging
import re
import urllib.error
import urllib.request
from typing import Any

import config as cfg
from mcp.client import call_mcp_tool, context7_spec, fetch_spec, parse_jsonish

logger = logging.getLogger("multi-agent.mcp")

_BUILTIN_SNIPPETS: dict[str, str] = {
    "vue": """Vue 3 要点（script setup）:
- 使用 <script setup>、ref/reactive、computed、onMounted
- 组件文件 .vue；路由 vue-router 4：createRouter + createWebHistory
- 模板事件 @click；v-model 绑定表单
- 勿使用 Vue 2 Options API 作为默认写法""",
    "fastapi": """FastAPI 要点:
- APIRouter + prefix；路由装饰器 @router.get/post
- 依赖注入 Depends；HTTPException 处理 4xx/5xx
- Pydantic BaseModel 做请求/响应体
- 异步路由用 async def""",
    "element-plus": """Element Plus 要点:
- 按需或全局注册；el-button el-form el-input
- el-form :model + :rules；@submit .prevent
- 中文项目可用 locale zh-cn""",
}

_DOC_URLS: dict[str, str] = {
    "vue": "https://vuejs.org/guide/introduction.html",
    "fastapi": "https://fastapi.tiangolo.com/tutorial/first-steps/",
    "element-plus": "https://element-plus.org/en-US/guide/quickstart.html",
}


def _detect_libraries(requirement: str, side: str, scope: str) -> list[str]:
    req = (requirement or "").lower()
    libs: list[str] = []
    if side == "frontend" or scope in ("fullstack", "frontend_only"):
        libs.append("vue")
        if any(k in req for k in ("element", "el-", "表单", "按钮")):
            libs.append("element-plus")
    if side == "backend" or scope in ("fullstack", "backend_only"):
        libs.append("fastapi")
    return libs


def _context7_docs(library: str, topic: str) -> tuple[str, str]:
    spec = context7_spec()
    if not spec:
        return "", "context7_disabled"
    ok, lib_raw = call_mcp_tool(
        spec,
        "resolve-library-id",
        {"libraryName": library},
        timeout=cfg.MCP_DOCS_TIMEOUT_SEC,
    )
    if not ok:
        return "", f"context7_resolve_fail:{lib_raw[:120]}"
    lib_id = lib_raw.strip()
    parsed = parse_jsonish(lib_raw)
    if isinstance(parsed, dict):
        lib_id = str(parsed.get("libraryId") or parsed.get("id") or lib_id)
    elif isinstance(parsed, list) and parsed:
        first = parsed[0]
        if isinstance(first, dict):
            lib_id = str(first.get("libraryId") or first.get("id") or lib_id)
    ok2, docs = call_mcp_tool(
        spec,
        "get-library-docs",
        {"context7CompatibleLibraryID": lib_id, "topic": topic[:200], "tokens": 2500},
        timeout=cfg.MCP_DOCS_TIMEOUT_SEC,
    )
    if ok2 and docs.strip():
        return docs[: cfg.MCP_DOCS_MAX_CHARS], "context7"
    return "", f"context7_docs_fail:{docs[:120]}"


def _fetch_url_docs(url: str) -> tuple[str, str]:
    spec = fetch_spec()
    if spec:
        ok, body = call_mcp_tool(
            spec,
            "fetch",
            {"url": url, "max_length": cfg.MCP_DOCS_MAX_CHARS},
            timeout=cfg.MCP_DOCS_TIMEOUT_SEC,
        )
        if ok and body.strip():
            return body[: cfg.MCP_DOCS_MAX_CHARS], "fetch_mcp"
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "multi-agent-pipeline/1.0"},
        )
        with urllib.request.urlopen(req, timeout=cfg.MCP_DOCS_TIMEOUT_SEC) as resp:
            raw = resp.read(cfg.MCP_DOCS_MAX_CHARS * 2)
        text = raw.decode("utf-8", errors="ignore")
        text = re.sub(r"<script[\s\S]*?</script>", "", text, flags=re.I)
        text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[: cfg.MCP_DOCS_MAX_CHARS], "urllib"
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return "", f"fetch_fail:{e}"


def fetch_framework_docs(
    requirement: str,
    side: str,
    scope: str = "fullstack",
) -> tuple[str, dict[str, Any]]:
    """
    为 Dev/BugFix Prompt 拉取框架文档摘要。
    返回 (markdown_block, meta)
    """
    meta: dict[str, Any] = {"libraries": [], "sources": [], "enabled": cfg.MCP_DOCS_ENABLED}
    if not cfg.MCP_DOCS_ENABLED:
        return "（MCP 文档检索未启用）", meta

    libs = _detect_libraries(requirement, side, scope)
    meta["libraries"] = libs
    sections: list[str] = []
    topic = (requirement or "")[:200]

    for lib in libs:
        chunk = ""
        source = ""
        if cfg.MCP_CONTEXT7_ENABLED:
            chunk, source = _context7_docs(lib, topic)
        if not chunk and cfg.MCP_FETCH_ENABLED and lib in _DOC_URLS:
            chunk, source = _fetch_url_docs(_DOC_URLS[lib])
        if not chunk:
            chunk = _BUILTIN_SNIPPETS.get(lib, "")
            source = "builtin"
        if chunk:
            sections.append(f"### {lib}（来源: {source}）\n{chunk}")
            meta["sources"].append({"library": lib, "source": source})

    if not sections:
        return "（未检索到框架文档，使用模型内置知识）", meta

    block = (
        "## 框架最新文档摘要（MCP Context7 / Fetch，编写时请遵循）\n"
        + "\n\n".join(sections)
    )
    return block[: cfg.MCP_DOCS_MAX_CHARS], meta
