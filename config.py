"""
多智能体协作开发系统 — 全局配置
可通过环境变量覆盖，便于面试演示与本地调试。
"""
from __future__ import annotations

import os
from pathlib import Path

# 优先加载项目根目录 .env（本地密钥，勿提交 Git）
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
except ImportError:
    pass

# ── 路径 ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output"
DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── LLM ─────────────────────────────────────────────────────────────────
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()
LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o-mini").strip()

_mock_env = os.getenv("USE_MOCK_LLM", "auto").strip().lower()
if _mock_env in ("0", "false", "no"):
    USE_MOCK_LLM = False
elif _mock_env in ("1", "true", "yes"):
    USE_MOCK_LLM = True
else:
    # auto: 有 Key 则走真实 API，无 Key 才 Mock
    USE_MOCK_LLM = not bool(OPENAI_API_KEY)

# ── 流程控制 ────────────────────────────────────────────────────────────
MAX_FIX_ROUNDS: int = int(os.getenv("MAX_FIX_ROUNDS", "3"))
MAX_REVIEW_RETRIES: int = int(os.getenv("MAX_REVIEW_RETRIES", "2"))
NODE_RETRY_ATTEMPTS: int = int(os.getenv("NODE_RETRY_ATTEMPTS", "2"))

# 代码评审通过阈值（0-100）
REVIEW_PASS_SCORE: int = int(os.getenv("REVIEW_PASS_SCORE", "75"))

# ── 存量项目扫描 ────────────────────────────────────────────────────────
LEGACY_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".vue",
    ".java", ".go", ".json", ".yaml", ".yml", ".sql",
}
LEGACY_MAX_FILES: int = int(os.getenv("LEGACY_MAX_FILES", "80"))
LEGACY_MAX_FILE_BYTES: int = int(os.getenv("LEGACY_MAX_FILE_BYTES", "120000"))

# ── 合并到主项目目录（交付后拷贝前后端代码）────────────────────────────
# 示例: MERGE_TARGET_ROOT=/Users/liyue/Desktop/all
MERGE_TARGET_ROOT: str = os.getenv(
    "MERGE_TARGET_ROOT",
    str(Path.home() / "Desktop" / "all"),
).strip()
MERGE_BACKEND_SUBDIR: str = os.getenv("MERGE_BACKEND_SUBDIR", "backend").strip()
MERGE_FRONTEND_SUBDIR: str = os.getenv("MERGE_FRONTEND_SUBDIR", "frontend").strip()
MERGE_ENABLED: bool = os.getenv("MERGE_ENABLED", "true").strip().lower() in (
    "1",
    "true",
    "yes",
)
MERGE_OVERWRITE: bool = os.getenv("MERGE_OVERWRITE", "true").strip().lower() in (
    "1",
    "true",
    "yes",
)


def resolve_merge_target(path_str: str = "") -> Path:
    """解析合并目标根目录（支持 ~ 与相对路径）。"""
    raw = (path_str or MERGE_TARGET_ROOT).strip()
    if not raw:
        return Path()
    return Path(raw).expanduser().resolve()


# ── 日志 ────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# ── Streamlit ───────────────────────────────────────────────────────────
STREAMLIT_PAGE_TITLE = "多智能体协作开发流水线"
STREAMLIT_PAGE_ICON = "🤖"
