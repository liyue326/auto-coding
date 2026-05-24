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
# 单次流水线最多执行节点步数（防止 Checkpoint 续跑或路由死循环）
MAX_PIPELINE_STEPS: int = int(os.getenv("MAX_PIPELINE_STEPS", "40"))
# LangGraph 图级递归上限（与 MAX_PIPELINE_STEPS 双保险）
LANGGRAPH_RECURSION_LIMIT: int = int(os.getenv("LANGGRAPH_RECURSION_LIMIT", "45"))

# 结构化输出（Function Calling / JSON Schema，减少 JSON 解析失败与重试）
USE_STRUCTURED_OUTPUT: bool = os.getenv(
    "USE_STRUCTURED_OUTPUT", "true"
).strip().lower() in ("1", "true", "yes")
# function_calling | json_schema | json_mode
STRUCTURED_OUTPUT_METHOD: str = os.getenv(
    "STRUCTURED_OUTPUT_METHOD", "function_calling"
).strip().lower()

# 代码评审通过阈值（0-100）
REVIEW_PASS_SCORE: int = int(os.getenv("REVIEW_PASS_SCORE", "75"))

# ── 老项目（默认 Desktop/all）──────────────────────────────────────────
DEFAULT_LEGACY_PATH: str = os.getenv(
    "DEFAULT_LEGACY_PATH",
    str(Path.home() / "Desktop" / "all"),
).strip()
WORKSPACES_DIR: Path = Path(
    os.getenv("WORKSPACES_DIR", str(PROJECT_ROOT / "data" / "workspaces"))
).expanduser()

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
# 有 legacy_path 时默认不自动写回老项目，需人工确认（见 export_approved）
MERGE_ENABLED: bool = os.getenv("MERGE_ENABLED", "false").strip().lower() in (
    "1",
    "true",
    "yes",
)
MERGE_OVERWRITE: bool = os.getenv("MERGE_OVERWRITE", "true").strip().lower() in (
    "1",
    "true",
    "yes",
)
# 冲突策略（仅当 MERGE_OVERWRITE=false 时作为默认）:
#   overwrite — 直接覆盖已存在文件
#   manual    — 有差异则导出 .current/.incoming，不覆盖主项目
#   skip      — 已存在则跳过 | backup — 先 .bak 再覆盖
MERGE_CONFLICT_MODE: str = os.getenv("MERGE_CONFLICT_MODE", "overwrite").strip().lower()
if MERGE_CONFLICT_MODE not in ("overwrite", "skip", "backup", "manual"):
    MERGE_CONFLICT_MODE = "overwrite"

MERGE_IGNORE_NAMES = frozenset({".DS_Store", "Thumbs.db", ".gitkeep"})


def resolve_merge_target(path_str: str = "") -> Path:
    """解析合并目标根目录（支持 ~ 与相对路径）。"""
    raw = (path_str or MERGE_TARGET_ROOT).strip()
    if not raw:
        return Path()
    return Path(raw).expanduser().resolve()


# ── 修复经验向量库（Chroma，仅入库成功修复）────────────────────────────
MEMORY_ENABLED: bool = os.getenv("MEMORY_ENABLED", "true").strip().lower() in (
    "1",
    "true",
    "yes",
)
CHROMA_PERSIST_DIR: Path = Path(
    os.getenv("CHROMA_PERSIST_DIR", str(PROJECT_ROOT / "data" / "chroma"))
).expanduser()
CHROMA_COLLECTION: str = os.getenv("CHROMA_COLLECTION", "fix_experiences").strip()
MEMORY_TOP_K: int = int(os.getenv("MEMORY_TOP_K", "3"))

# ── 多轮对话记忆（JSONL 持久化，注入 Planner / Dev Prompt）──────────────
CONVERSATION_MEMORY_ENABLED: bool = os.getenv(
    "CONVERSATION_MEMORY_ENABLED", "true"
).strip().lower() in ("1", "true", "yes")
CONVERSATION_PERSIST_DIR: Path = Path(
    os.getenv(
        "CONVERSATION_PERSIST_DIR",
        str(PROJECT_ROOT / "data" / "conversations"),
    )
).expanduser()
CONVERSATION_MAX_TURNS: int = int(os.getenv("CONVERSATION_MAX_TURNS", "8"))
CONVERSATION_MAX_CHARS: int = int(os.getenv("CONVERSATION_MAX_CHARS", "3500"))
CONVERSATION_DEFAULT_THREAD: str = os.getenv(
    "CONVERSATION_DEFAULT_THREAD", "default"
).strip() or "default"
# 多轮记忆主存储：checkpoint=LangGraph SqliteSaver；jsonl=旧版 JSONL（可双写）
CONVERSATION_USE_CHECKPOINT: bool = os.getenv(
    "CONVERSATION_USE_CHECKPOINT", "true"
).strip().lower() in ("1", "true", "yes")
CONVERSATION_USE_JSONL: bool = os.getenv(
    "CONVERSATION_USE_JSONL", "true"
).strip().lower() in ("1", "true", "yes")

# ── LangGraph Checkpoint（流水线状态 + 对话 thread 持久化）────────────
LANGGRAPH_CHECKPOINT_ENABLED: bool = os.getenv(
    "LANGGRAPH_CHECKPOINT_ENABLED", "true"
).strip().lower() in ("1", "true", "yes")
LANGGRAPH_CHECKPOINT_SQLITE: bool = os.getenv(
    "LANGGRAPH_CHECKPOINT_SQLITE", "true"
).strip().lower() in ("1", "true", "yes")
LANGGRAPH_CHECKPOINT_DB: Path = Path(
    os.getenv(
        "LANGGRAPH_CHECKPOINT_DB",
        str(PROJECT_ROOT / "data" / "checkpoints" / "langgraph.db"),
    )
).expanduser()
# DashScope 兼容接口常用 text-embedding-v3；OpenAI 官方可用 text-embedding-3-small
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "text-embedding-v3").strip()

# ── 日志 ────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# ── Streamlit ───────────────────────────────────────────────────────────
STREAMLIT_PAGE_TITLE = "多智能体协作开发流水线"
STREAMLIT_PAGE_ICON = "🤖"

# ── MCP 集成（Playwright E2E / Context7+Fetch 文档 / SQL 校验）────────
MCP_ENABLED: bool = os.getenv("MCP_ENABLED", "true").strip().lower() in (
    "1",
    "true",
    "yes",
)
MCP_TOOL_TIMEOUT_SEC: float = float(os.getenv("MCP_TOOL_TIMEOUT_SEC", "90"))
MCP_DOCS_TIMEOUT_SEC: float = float(os.getenv("MCP_DOCS_TIMEOUT_SEC", "45"))
MCP_E2E_TIMEOUT_SEC: float = float(os.getenv("MCP_E2E_TIMEOUT_SEC", "120"))
MCP_SQL_TIMEOUT_SEC: float = float(os.getenv("MCP_SQL_TIMEOUT_SEC", "60"))
MCP_DOCS_MAX_CHARS: int = int(os.getenv("MCP_DOCS_MAX_CHARS", "6000"))

# Playwright MCP — E2E（需先启动前端 dev server，如 npm run dev）
MCP_PLAYWRIGHT_ENABLED: bool = os.getenv(
    "MCP_PLAYWRIGHT_ENABLED", "true"
).strip().lower() in ("1", "true", "yes")
MCP_PLAYWRIGHT_COMMAND: str = os.getenv("MCP_PLAYWRIGHT_COMMAND", "npx").strip()
MCP_PLAYWRIGHT_ARGS: str = os.getenv(
    "MCP_PLAYWRIGHT_ARGS", "-y,@playwright/mcp@latest"
).strip()
MCP_E2E_BASE_URL: str = os.getenv("MCP_E2E_BASE_URL", "").strip()
MCP_E2E_STATIC_FALLBACK: bool = os.getenv(
    "MCP_E2E_STATIC_FALLBACK", "true"
).strip().lower() in ("1", "true", "yes")

# Context7 + Fetch MCP — Dev/BugFix 框架文档
MCP_DOCS_ENABLED: bool = os.getenv("MCP_DOCS_ENABLED", "true").strip().lower() in (
    "1",
    "true",
    "yes",
)
MCP_CONTEXT7_ENABLED: bool = os.getenv(
    "MCP_CONTEXT7_ENABLED", "true"
).strip().lower() in ("1", "true", "yes")
MCP_CONTEXT7_COMMAND: str = os.getenv("MCP_CONTEXT7_COMMAND", "npx").strip()
MCP_CONTEXT7_ARGS: str = os.getenv(
    "MCP_CONTEXT7_ARGS", "-y,@upstash/context7-mcp@latest"
).strip()
CONTEXT7_API_KEY: str = os.getenv("CONTEXT7_API_KEY", "").strip()
MCP_FETCH_ENABLED: bool = os.getenv("MCP_FETCH_ENABLED", "true").strip().lower() in (
    "1",
    "true",
    "yes",
)
MCP_FETCH_COMMAND: str = os.getenv("MCP_FETCH_COMMAND", "npx").strip()
MCP_FETCH_ARGS: str = os.getenv(
    "MCP_FETCH_ARGS", "-y,@modelcontextprotocol/server-fetch@latest"
).strip()

# SQL 校验 — 本地 SQLite + 可选 Postgres MCP
MCP_SQL_ENABLED: bool = os.getenv("MCP_SQL_ENABLED", "true").strip().lower() in (
    "1",
    "true",
    "yes",
)
MCP_POSTGRES_ENABLED: bool = os.getenv(
    "MCP_POSTGRES_ENABLED", "false"
).strip().lower() in ("1", "true", "yes")
MCP_POSTGRES_URI: str = os.getenv("MCP_POSTGRES_URI", "").strip()
MCP_POSTGRES_COMMAND: str = os.getenv("MCP_POSTGRES_COMMAND", "npx").strip()
MCP_POSTGRES_ARGS: str = os.getenv(
    "MCP_POSTGRES_ARGS", "-y,@modelcontextprotocol/server-postgres@latest"
).strip()
