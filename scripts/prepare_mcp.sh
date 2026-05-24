#!/bin/bash
# MCP 一键准备：Python 依赖 + 老项目 frontend 脚手架 + npm install + 自检
set -euo pipefail
cd "$(dirname "$0")/.."

echo ">>> pip install -r requirements.txt"
python3 -m pip install -r requirements.txt

echo ">>> MCP 自检 + 脚手架 + npm install"
python3 scripts/prepare_mcp.py --scaffold --npm-install "$@"

echo ""
echo ">>> 启动方式（两个终端）"
echo "  终端1: cd ${DEFAULT_LEGACY_PATH:-/Users/liyue/Desktop/all}/frontend && npm run dev"
echo "  终端2: streamlit run app.py"
