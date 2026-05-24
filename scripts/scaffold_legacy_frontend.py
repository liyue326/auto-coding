#!/usr/bin/env python3
"""为老项目 frontend/ 补齐 Vite 开发环境（index.html / package.json / main.js）。"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config as cfg  # noqa: E402

TEMPLATES = Path(__file__).resolve().parent / "templates" / "frontend-dev"


def scaffold(legacy_root: Path, *, npm_install: bool = False) -> list[str]:
    fe = legacy_root / "frontend"
    if not fe.is_dir():
        fe.mkdir(parents=True, exist_ok=True)
    logs: list[str] = []

    for name in ("package.json", "vite.config.js", "index.html"):
        src = TEMPLATES / name
        dst = fe / name
        if not dst.exists():
            shutil.copy2(src, dst)
            logs.append(f"已创建 {dst}")

    main_js = fe / "src" / "main.js"
    if not main_js.exists():
        main_js.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(TEMPLATES / "main.js", main_js)
        logs.append(f"已创建 {main_js}")

    router_js = fe / "src" / "router" / "index.js"
    router_tpl = TEMPLATES / "router" / "index.js"
    if router_tpl.exists() and router_js.exists():
        # 仅当路由只有 /login、无根路径重定向时，写入标准路由
        try:
            text = router_js.read_text(encoding="utf-8")
            if "redirect" not in text and "path: '/login'" in text:
                shutil.copy2(router_tpl, router_js)
                logs.append(f"已更新路由（/ → /login）: {router_js}")
        except OSError:
            pass
    elif router_tpl.exists() and not router_js.exists():
        router_js.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(router_tpl, router_js)
        logs.append(f"已创建 {router_js}")

    if npm_install and (fe / "package.json").exists():
        if shutil.which("npm") is None:
            logs.append("未找到 npm，跳过 npm install")
        elif not (fe / "node_modules").is_dir():
            logs.append(f"正在 {fe} 执行 npm install …")
            subprocess.run(
                ["npm", "install", "--no-audit", "--no-fund"],
                cwd=str(fe),
                check=False,
            )
            logs.append("npm install 完成（若失败请手动在该目录重试）")
        else:
            logs.append("node_modules 已存在，跳过 npm install")

    return logs


def main() -> int:
    parser = argparse.ArgumentParser(description="补齐老项目 frontend Vite 开发环境")
    parser.add_argument(
        "-l",
        "--legacy",
        default=cfg.DEFAULT_LEGACY_PATH,
        help="老项目根目录",
    )
    parser.add_argument(
        "--npm-install",
        action="store_true",
        help="脚手架后执行 npm install",
    )
    args = parser.parse_args()
    legacy = Path(args.legacy).expanduser().resolve()
    logs = scaffold(legacy, npm_install=args.npm_install)
    if not logs:
        print(f"frontend 开发环境已就绪: {legacy / 'frontend'}")
    else:
        for line in logs:
            print(line)
    print(f"\n启动 dev server:\n  cd {legacy / 'frontend'} && npm run dev")
    print("E2E 地址: http://127.0.0.1:5173")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
