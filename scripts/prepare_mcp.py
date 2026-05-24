#!/usr/bin/env python3
"""MCP 环境准备与自检：依赖、老项目 dev server、MCP Server 探活。"""
from __future__ import annotations

import argparse
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config as cfg  # noqa: E402


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _warn(msg: str) -> None:
    print(f"  ⚠ {msg}")


def _fail(msg: str) -> None:
    print(f"  ✗ {msg}")


def check_python_deps() -> bool:
    print("\n[1/5] Python 依赖")
    ok = True
    ver = sys.version_info
    if ver < (3, 10):
        _fail(f"Python {ver.major}.{ver.minor} 过低，mcp 包需 3.10+，请运行: bash scripts/setup_venv.sh")
        ok = False
    else:
        _ok(f"Python {ver.major}.{ver.minor}.{ver.micro}")
    for pkg in ("mcp", "langgraph", "langchain_openai", "streamlit"):
        if importlib.util.find_spec(pkg.replace("-", "_").split(".")[0]) is None:
            _fail(f"缺少 {pkg}，请 pip install -r requirements.txt")
            ok = False
        else:
            _ok(pkg)
    return ok


def check_node() -> bool:
    print("\n[2/5] Node.js / npx（MCP Server 通过 npx 启动）")
    node = shutil.which("node")
    npx = shutil.which("npx")
    if not node or not npx:
        _fail("未安装 node/npx，Playwright/Context7/Fetch MCP 不可用")
        return False
    try:
        ver = subprocess.check_output([node, "--version"], text=True).strip()
        _ok(f"node {ver}")
        major = int(ver.lstrip("v").split(".")[0])
        if major < 18:
            _warn("Node < 18，部分 MCP 包可能报错，建议升级到 Node 18+")
    except Exception as e:
        _warn(f"无法读取 node 版本: {e}")
    _ok("npx 可用")
    return True


def check_sql_module() -> bool:
    print("\n[3/5] SQL 校验（本地 SQLite，无需 MCP Server）")
    try:
        from mcp_tools.sql_check import validate_backend_schema

        issues, meta = validate_backend_schema(
            {"schema.sql": "CREATE TABLE t (id INTEGER PRIMARY KEY);"}
        )
        if meta.get("sqlite", {}).get("ok"):
            _ok("SQLite DDL 校验正常")
            return True
        _fail(f"SQLite 校验异常: {meta}")
        return False
    except Exception as e:
        _fail(str(e))
        return False


def probe_mcp_server(label: str, command: str, args: list[str], env: dict | None = None) -> None:
    """尝试 import mcp 并短超时连接（仅打印结果，不阻断）。"""
    try:
        from mcp_tools.client import MCPServerSpec, call_mcp_tool

        spec = MCPServerSpec(label, command, args, env or {})
        ok, msg = call_mcp_tool(spec, "list_tools_probe", {}, timeout=8)
        # list_tools 不是标准工具名，会失败；改用各 server 已知工具
        if label == "fetch":
            ok, msg = call_mcp_tool(
                spec, "fetch", {"url": "https://example.com", "max_length": 200}, timeout=20
            )
        elif label == "context7":
            ok, msg = call_mcp_tool(
                spec, "resolve-library-id", {"libraryName": "vue"}, timeout=25
            )
        elif label == "playwright":
            _warn("Playwright 探活跳过（启动慢）；请手动 npx @playwright/mcp@latest")
            return
        elif label == "postgres":
            _warn("Postgres 探活跳过（需 MCP_POSTGRES_URI）")
            return
        if ok:
            _ok(f"{label} MCP 响应正常 ({len(msg)} 字符)")
        else:
            _warn(f"{label} MCP: {msg[:160]}")
    except Exception as e:
        _warn(f"{label} MCP 探活失败: {e}")


def check_mcp_servers(*, probe: bool) -> None:
    print("\n[4/5] MCP Server 配置")
    if not cfg.MCP_ENABLED:
        _warn("MCP_ENABLED=false")
        return
    flags = {
        "Playwright E2E": cfg.MCP_PLAYWRIGHT_ENABLED,
        "Context7 文档": cfg.MCP_CONTEXT7_ENABLED,
        "Fetch 文档": cfg.MCP_FETCH_ENABLED,
        "SQL SQLite": cfg.MCP_SQL_ENABLED,
        "Postgres MCP": cfg.MCP_POSTGRES_ENABLED and bool(cfg.MCP_POSTGRES_URI),
    }
    for name, on in flags.items():
        (_ok if on else _warn)(f"{name}: {'开' if on else '关'}")
    if cfg.MCP_E2E_BASE_URL:
        _ok(f"E2E 地址: {cfg.MCP_E2E_BASE_URL}")
    else:
        _warn("未设置 MCP_E2E_BASE_URL，E2E 将用静态 .vue 检查")

    if not probe:
        _warn("加 --probe 可探测 Context7/Fetch（需网络，首次 npx 较慢）")
        return

    print("  探测 MCP（首次可能下载 npm 包）…")
    if cfg.MCP_FETCH_ENABLED:
        args = [a.strip() for a in cfg.MCP_FETCH_ARGS.split(",") if a.strip()]
        probe_mcp_server("fetch", cfg.MCP_FETCH_COMMAND, args)
    if cfg.MCP_CONTEXT7_ENABLED:
        import os

        env = dict(os.environ)
        if cfg.CONTEXT7_API_KEY:
            env["CONTEXT7_API_KEY"] = cfg.CONTEXT7_API_KEY
        args = [a.strip() for a in cfg.MCP_CONTEXT7_ARGS.split(",") if a.strip()]
        probe_mcp_server("context7", cfg.MCP_CONTEXT7_COMMAND, args, env)


def check_legacy_frontend(*, scaffold: bool, npm_install: bool) -> None:
    print("\n[5/5] 老项目 frontend dev 环境")
    legacy = Path(cfg.DEFAULT_LEGACY_PATH).expanduser()
    fe = legacy / "frontend"
    if not fe.is_dir():
        _warn(f"无 frontend 目录: {fe}")
        return

    pkg = fe / "package.json"
    if not pkg.exists():
        if scaffold:
            import importlib.util

            spec = importlib.util.spec_from_file_location(
                "scaffold_legacy_frontend",
                ROOT / "scripts" / "scaffold_legacy_frontend.py",
            )
            mod = importlib.util.module_from_spec(spec)
            assert spec.loader
            spec.loader.exec_module(mod)
            for line in mod.scaffold(legacy, npm_install=npm_install):
                print(f"  · {line}")
        else:
            _warn("缺少 package.json，请运行: python3 scripts/prepare_mcp.py --scaffold")
            return
    else:
        _ok(f"package.json 存在: {pkg}")

    if (fe / "index.html").exists():
        _ok("index.html 存在")
    else:
        _warn("缺少 index.html")

    if (fe / "node_modules").is_dir():
        _ok("node_modules 已安装")
    elif npm_install and pkg.exists():
        subprocess.run(
            ["npm", "install", "--no-audit", "--no-fund"],
            cwd=str(fe),
            check=False,
        )
        if (fe / "node_modules").is_dir():
            _ok("npm install 完成")
        else:
            _warn("npm install 未成功，请手动: cd frontend && npm install")
    else:
        _warn("未安装 node_modules，请: cd frontend && npm install")


def main() -> int:
    parser = argparse.ArgumentParser(description="MCP 环境准备与自检")
    parser.add_argument("--scaffold", action="store_true", help="补齐老项目 Vite 脚手架")
    parser.add_argument("--npm-install", action="store_true", help="在 frontend 执行 npm install")
    parser.add_argument("--probe", action="store_true", help="探测 Context7/Fetch MCP（需网络）")
    parser.add_argument("--playwright-install", action="store_true", help="npx playwright install chromium")
    args = parser.parse_args()

    print("=" * 50)
    print("MCP 环境准备 / 自检")
    print("=" * 50)

    ok = check_python_deps() and check_node()
    ok = check_sql_module() and ok
    check_mcp_servers(probe=args.probe)
    check_legacy_frontend(scaffold=args.scaffold, npm_install=args.npm_install)

    if args.playwright_install and shutil.which("npx"):
        print("\n[可选] Playwright 浏览器安装")
        subprocess.run(["npx", "playwright", "install", "chromium"], check=False)

    print("\n" + "=" * 50)
    if ok:
        print("准备完成。下一步:")
        print("  1. 终端 A: cd <老项目>/frontend && npm run dev")
        print("  2. 终端 B: streamlit run app.py")
        print("  3. .env 确认 MCP_E2E_BASE_URL=http://127.0.0.1:5173")
    else:
        print("存在缺失项，请按上方提示修复后重跑本脚本。")
    print("=" * 50)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
