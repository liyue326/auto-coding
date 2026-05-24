"""从老项目快照加载待修改源文件，供 Dev Agent 在原文件上改动。"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger("multi-agent.legacy")

# 需求关键词 → 相对路径（相对 backend/ 或 frontend/）
_KEYWORD_PATHS: list[tuple[str, str, str]] = [
    (r"登录|login", "frontend", "src/views/LoginView.vue"),
    (r"注销|登出|logout", "frontend", "src/views/LoginView.vue"),
    (r"注销|登出|logout", "frontend", "src/api/auth.js"),
    (r"注册|register", "frontend", "src/views/LoginView.vue"),
    (r"笔记|notes", "frontend", "src/views/NotesView.vue"),
    (r"路由|router", "frontend", "src/router/index.js"),
    (r"auth|认证", "backend", "api/routes.py"),
    (r"注销|登出|logout", "backend", "api/routes.py"),
    (r"用户|user", "backend", "models/user.py"),
]


def wants_modify_existing(requirement: str) -> bool:
    """用户是否表达在原有代码/页面上改。"""
    req = requirement or ""
    patterns = (
        r"原有|现有|原来|当前",
        r"改|修改|调整|加上|增加|补充|扩展",
        r"在.{0,12}页面",
        r"页面.{0,8}(加|改)",
    )
    return any(re.search(p, req) for p in patterns)


def _normalize_rel(path: str, side: str) -> str:
    p = path.strip().replace("\\", "/").lstrip("/")
    while p.startswith(f"{side}/"):
        p = p[len(side) + 1 :]
    if p.startswith("frontend/"):
        p = p[len("frontend") + 1 :]
    if p.startswith("backend/"):
        p = p[len("backend") + 1 :]
    return p


def infer_touch_paths(
    requirement: str,
    report: dict[str, Any] | None = None,
    index: dict[str, Any] | None = None,
    side: str = "frontend",
) -> list[str]:
    """推断本次应修改的文件（相对 backend/ 或 frontend/）。"""
    paths: list[str] = []
    seen: set[str] = set()

    def add(p: str) -> None:
        norm = _normalize_rel(p, side)
        if norm and norm not in seen:
            seen.add(norm)
            paths.append(norm)

    report = report or {}
    for raw in report.get("suggested_touch_paths") or []:
        s = str(raw)
        if side == "frontend" and ("frontend" in s or s.endswith(".vue") or "src/" in s):
            add(s)
        elif side == "backend" and ("backend" in s or s.endswith(".py") or "api/" in s):
            add(s)

    req = requirement or ""
    for pattern, path_side, rel in _KEYWORD_PATHS:
        if path_side != side:
            continue
        if re.search(pattern, req, re.I):
            add(rel)

    index = index or {}
    for f in index.get("files_sample") or []:
        p = f.get("path", "")
        if not p.startswith(f"{side}/"):
            continue
        rel = _normalize_rel(p, side)
        name = Path(rel).name.lower()
        if any(k in req for k in ("登录", "login")) and "login" in name:
            add(rel)
        if any(k in req for k in ("笔记", "note")) and "note" in name:
            add(rel)

    return paths[:12]


def load_source_files(
    workspace: dict[str, Any],
    rel_paths: list[str],
    side: str,
    *,
    max_file_chars: int = 6000,
) -> dict[str, str]:
    """从 snapshot 读取源文件全文。"""
    if not workspace.get("ok") or not rel_paths:
        return {}
    snapshot = Path(workspace["snapshot_path"])
    if not snapshot.is_dir():
        return {}

    out: dict[str, str] = {}
    for rel in rel_paths:
        norm = _normalize_rel(rel, side)
        full = snapshot / side / norm
        if not full.is_file():
            # 兼容索引里 frontend/src/... 写法
            alt = snapshot / norm
            full = alt if alt.is_file() else full
        if not full.is_file():
            logger.warning("快照中无文件: %s/%s", side, norm)
            continue
        try:
            text = full.read_text(encoding="utf-8", errors="ignore")
        except OSError as e:
            logger.warning("读取失败 %s: %s", full, e)
            continue
        out[norm] = text[:max_file_chars]
    return out


def _baseline_markers(content: str) -> list[str]:
    """提取应用作「保留校验」的特征串。"""
    markers: list[str] = []
    for m in re.finditer(
        r"(function\s+\w+|async\s+function\s+\w+|const\s+\w+\s*=|class\s+\w+|"
        r"onLogin|onRegister|login-page|LoginView)",
        content,
    ):
        markers.append(m.group(0))
    for m in re.finditer(r"<[a-zA-Z][^>]{0,40}>", content[:2000]):
        tag = m.group(0)
        if tag not in ("<template>", "<script", "<style"):
            markers.append(tag)
    return list(dict.fromkeys(markers))[:25]


def preserves_baseline(baseline: str, modified: str, min_ratio: float = 0.35) -> bool:
    """修改稿是否仍像「在原文上改」而非整页重写。"""
    if not baseline or not modified:
        return False
    markers = _baseline_markers(baseline)
    if not markers:
        return len(modified) >= len(baseline) * 0.5
    hit = sum(1 for m in markers if m in modified)
    return hit / len(markers) >= min_ratio


def apply_requirement_on_baseline(
    baseline: str, requirement: str, rel_path: str
) -> str:
    """LLM 整页重写时，在快照基线上做确定性增改（常见存量场景）。"""
    req = requirement or ""
    path = rel_path.replace("\\", "/")

    if path.endswith("LoginView.vue") and re.search(r"注销|登出|logout", req, re.I):
        out = baseline
        if "handleLogout" not in out and "logout" not in out.lower():
            if 'from "../api/auth.js"' in out or 'from "../api/auth"' in out:
                out = out.replace(
                    'import { login, register } from "../api/auth.js";',
                    'import { login, register, logout } from "../api/auth.js";',
                )
                out = out.replace(
                    'import { login, register } from "../api/auth";',
                    'import { login, register, logout } from "../api/auth";',
                )
            elif "import" in out and "auth" in out:
                out = re.sub(
                    r'(import\s+\{[^}]+)(\})',
                    lambda m: m.group(1) + ", logout" + m.group(2)
                    if "logout" not in m.group(1)
                    else m.group(0),
                    out,
                    count=1,
                )
            if "useRouter" not in out:
                out = out.replace(
                    'import { ref } from "vue";',
                    'import { ref } from "vue";\nimport { useRouter } from "vue-router";',
                )
            if "const router" not in out:
                out = out.replace(
                    "const loading = ref(false);",
                    "const loading = ref(false);\nconst router = useRouter();",
                )
            btn = (
                '\n    <button type="button" :disabled="loading" @click="handleLogout">'
                "注销</button>"
            )
            if "</template>" in out and btn.strip() not in out:
                out = out.replace("</template>", btn + "\n  </template>", 1)
            if "async function handleLogout" not in out and "function handleLogout" not in out:
                fn = """
async function handleLogout() {
  loading.value = true;
  try {
    await logout();
    msg.value = "已注销";
    router.push("/login");
  } catch (e) {
    msg.value = String(e);
  } finally {
    loading.value = false;
  }
}
"""
                out = out.replace("</script>", fn + "\n</script>", 1)
        return out

    if path.endswith("auth.js") and re.search(r"注销|登出|logout", req, re.I):
        if "export async function logout" in baseline or "export function logout" in baseline:
            return baseline
        extra = """
export async function logout() {
  const res = await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
  if (!res.ok) throw new Error("logout failed");
  return res.json();
}
"""
        return baseline.rstrip() + "\n" + extra

    return baseline


def coalesce_with_baseline(
    llm_files: dict[str, str],
    baseline_files: dict[str, str],
    requirement: str,
) -> tuple[dict[str, str], list[str]]:
    """若 LLM 输出不像「在原文上改」，回退为基线 + 规则补丁。"""
    out = dict(llm_files)
    notes: list[str] = []
    for path, base in baseline_files.items():
        llm = out.get(path)
        if not llm:
            out[path] = apply_requirement_on_baseline(base, requirement, path)
            notes.append(f"{path}: LLM 未返回，已用快照基线+规则补丁")
            continue
        if not preserves_baseline(base, llm):
            patched = apply_requirement_on_baseline(base, requirement, path)
            out[path] = patched
            notes.append(f"{path}: LLM 未保留原逻辑，已回退快照并注入需求")
    return out, notes


def parse_existing_files_from_prompt(user: str) -> dict[str, str]:
    """从 Prompt 里「待修改已有文件」区块解析基线（供 Mock LLM）。"""
    files: dict[str, str] = {}
    for m in re.finditer(
        r"### 文件:\s*([^\n]+)\n```\n([\s\S]*?)```",
        user or "",
    ):
        path = m.group(1).strip()
        files[path] = m.group(2)
    return files


def format_existing_files_block(files: dict[str, str], side: str) -> str:
    if not files:
        return "（无：未匹配到需修改的已有文件，请根据项目上下文选择正确路径）"
    lines = [
        f"## 必须在以下已有 {side} 文件上修改（禁止新建替代页面）",
        "输出 JSON 的 files 键必须使用下列路径；内容为修改后的**完整文件**，保留原有功能。",
    ]
    for path, content in files.items():
        lines.append(f"\n### 文件: {path}\n```\n{content}\n```")
    return "\n".join(lines)[:14000]
