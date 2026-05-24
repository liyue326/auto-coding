#!/usr/bin/env bash
# 创建 Python 3.12 虚拟环境并安装依赖（mcp 包需 Python 3.10+）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY312=""
for candidate in \
  python3.12 \
  /opt/homebrew/bin/python3.12 \
  /usr/local/bin/python3.12; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PY312="$candidate"
    break
  fi
done

if [[ -z "$PY312" ]]; then
  echo "未找到 Python 3.12，正在通过 Homebrew 安装…"
  if ! command -v brew >/dev/null 2>&1; then
    echo "错误: 请先安装 Homebrew https://brew.sh" >&2
    exit 1
  fi
  brew install python@3.12
  for candidate in /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12; do
    if [[ -x "$candidate" ]]; then
      PY312="$candidate"
      break
    fi
  done
fi

if [[ -z "$PY312" ]]; then
  echo "错误: 安装后仍找不到 python3.12" >&2
  exit 1
fi

echo "使用: $($PY312 --version) ($PY312)"
"$PY312" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "虚拟环境已就绪。启动 Streamlit:"
echo "  source .venv/bin/activate && streamlit run app.py"
