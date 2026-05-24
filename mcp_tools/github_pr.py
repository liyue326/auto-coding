"""GitHub MCP：Deliver 后 push 生成代码并创建 Pull Request。"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import config as cfg
from mcp_tools.client import call_mcp_tool, github_spec, parse_jsonish

logger = logging.getLogger("multi-agent.mcp")


def parse_github_repo(repo: str = "", url: str = "") -> tuple[str, str]:
    """解析 owner/repo。"""
    raw = (repo or cfg.GITHUB_REPO or "").strip()
    if not raw and url:
        raw = url.strip()
    if raw.startswith("http"):
        m = re.search(r"github\.com[:/]+([^/]+)/([^/.]+)", raw)
        if m:
            return m.group(1), m.group(2).replace(".git", "")
    if "/" in raw:
        owner, name = raw.split("/", 1)
        return owner.strip(), name.strip().replace(".git", "")
    return cfg.GITHUB_OWNER.strip(), raw.replace(".git", "")


def _github_api(
    method: str,
    path: str,
    payload: dict | None = None,
) -> dict[str, Any]:
    token = cfg.GITHUB_TOKEN
    if not token:
        return {"ok": False, "error": "missing GITHUB_TOKEN"}
    url = f"https://api.github.com{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "multi-agent-pipeline",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8")
            if not body:
                return {"ok": True}
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                parsed["ok"] = True
                return parsed
            return {"ok": True, "data": parsed}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        try:
            err_json = json.loads(err_body)
            msg = err_json.get("message", err_body[:200])
        except json.JSONDecodeError:
            msg = err_body[:200] or f"HTTP {e.code}"
        return {"ok": False, "error": msg, "status": e.code}
    except OSError as e:
        return {"ok": False, "error": str(e)}


def collect_files_for_push(
    output_dir: str | Path,
    state: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """从 output/run_xxx 收集 backend/ frontend/ 下文件；磁盘为空时回退 state。"""
    root = Path(output_dir)
    out: list[dict[str, str]] = []
    max_files = cfg.GITHUB_MCP_MAX_FILES
    max_chars = cfg.GITHUB_MCP_MAX_FILE_CHARS
    sub = (cfg.GITHUB_REPO_SUBDIR or "").strip().strip("/")

    def _add(side: str, rel: str, text: str) -> None:
        if len(out) >= max_files:
            return
        path = rel.replace("\\", "/")
        if not path.startswith(f"{side}/"):
            path = f"{side}/{path.lstrip('/')}"
        if sub:
            path = f"{sub}/{path}"
        if len(text) > max_chars:
            text = text[:max_chars] + "\n/* truncated */\n"
        out.append({"path": path, "content": text})

    for side in ("backend", "frontend"):
        base = root / side
        if base.is_dir():
            for fp in sorted(base.rglob("*")):
                if not fp.is_file():
                    continue
                if fp.name.startswith(".") or fp.suffix in (".pyc", ".DS_Store"):
                    continue
                rel = f"{side}/{fp.relative_to(base)}".replace("\\", "/")
                try:
                    text = fp.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                _add(side, rel, text)
                if len(out) >= max_files:
                    return out

    if out or not state:
        return out

    # 回退：从 state 内存中的 files 字典收集（防止 output_dir 路径未更新）
    for side, key in (("backend", "backend_files"), ("frontend", "frontend_files")):
        for rel, content in (state.get(key) or {}).items():
            if content is None:
                continue
            norm = rel.replace("\\", "/")
            if norm.startswith("tests/"):
                _add("backend", norm, str(content))
            else:
                _add(side, norm, str(content))
            if len(out) >= max_files:
                return out
    return out


def build_pr_body(state: dict[str, Any], code_changes: dict | None = None) -> str:
    req = state.get("requirement") or ""
    review = state.get("review_result") or {}
    test = state.get("test_result") or {}
    changes = code_changes or state.get("code_changes") or {}
    summary = changes.get("text_summary") or "—"
    lines = [
        "## 多智能体流水线交付",
        "",
        f"**需求:** {req[:500]}",
        "",
        f"**代码变更:** {summary}",
        "",
        f"**评审得分:** {review.get('score', '—')} · **测试:** "
        f"{'通过' if state.get('test_passed') else '未通过'} · "
        f"**缺陷:** {len(state.get('defects') or [])}",
        "",
        f"**输出目录:** `{state.get('output_dir', '')}`",
        "",
    ]
    for item in (changes.get("files") or [])[:12]:
        if item.get("status") in ("modified", "new", "generated"):
            lines.append(f"- `{item.get('side')}/{item.get('path')}` — {item.get('summary', '')}")
    patches_dir = Path(state.get("output_dir") or "") / "reports" / "patches"
    if patches_dir.is_dir():
        lines.extend(["", "本地 diff 见 `reports/patches/` 与 `reports/changes.json`。"])
    return "\n".join(lines)


def _get_branch_sha(owner: str, repo: str, branch: str) -> str | None:
    ref = f"heads/{branch}"
    resp = _github_api("GET", f"/repos/{owner}/{repo}/git/ref/{ref}")
    if resp.get("ok") is False:
        return None
    return (resp.get("object") or {}).get("sha")


def _api_push_files(
    owner: str,
    repo: str,
    branch: str,
    files: list[dict[str, str]],
    message: str,
) -> tuple[bool, str, dict]:
    """GitHub Git Data API 推送（不依赖 mcp 包 / npx）。"""
    base = cfg.GITHUB_BASE_BRANCH or "main"
    parent_sha = _get_branch_sha(owner, repo, branch) or _get_branch_sha(owner, repo, base)
    if not parent_sha:
        return False, f"无法读取分支 {branch} 或 {base} 的 commit", {}

    commit_resp = _github_api("GET", f"/repos/{owner}/{repo}/git/commits/{parent_sha}")
    if commit_resp.get("ok") is False:
        return False, commit_resp.get("error", "读取 commit 失败"), {}
    base_tree_sha = (commit_resp.get("tree") or {}).get("sha")
    if not base_tree_sha:
        return False, "commit 无 tree sha", {}

    tree_entries = [
        {
            "path": f["path"],
            "mode": "100644",
            "type": "blob",
            "content": f["content"],
        }
        for f in files
    ]
    tree_resp = _github_api(
        "POST",
        f"/repos/{owner}/{repo}/git/trees",
        {"base_tree": base_tree_sha, "tree": tree_entries},
    )
    if tree_resp.get("ok") is False:
        return False, tree_resp.get("error", "创建 tree 失败"), {}
    new_tree_sha = tree_resp.get("sha")
    if not new_tree_sha:
        return False, "tree 无 sha", {}

    new_commit = _github_api(
        "POST",
        f"/repos/{owner}/{repo}/git/commits",
        {"message": message, "tree": new_tree_sha, "parents": [parent_sha]},
    )
    if new_commit.get("ok") is False:
        return False, new_commit.get("error", "创建 commit 失败"), {}
    new_sha = new_commit.get("sha")
    if not new_sha:
        return False, "commit 无 sha", {}

    if _get_branch_sha(owner, repo, branch):
        ref_resp = _github_api(
            "PATCH",
            f"/repos/{owner}/{repo}/git/refs/heads/{branch}",
            {"sha": new_sha, "force": False},
        )
    else:
        ref_resp = _github_api(
            "POST",
            f"/repos/{owner}/{repo}/git/refs",
            {"ref": f"refs/heads/{branch}", "sha": new_sha},
        )
    if ref_resp.get("ok") is False:
        return False, ref_resp.get("error", "更新 ref 失败"), {}
    return True, new_sha, {"commit": new_sha, "branch": branch}


def _push_files(
    owner: str,
    repo: str,
    branch: str,
    files: list[dict[str, str]],
    message: str,
) -> tuple[bool, str, str, dict]:
    """MCP push_files → 失败则 GitHub REST API。"""
    if cfg.GITHUB_MCP_PUSH:
        ok, detail, data = _mcp_push_files(owner, repo, branch, files, message)
        if ok:
            return True, detail, "github_mcp", data
        logger.warning("GitHub MCP push 失败，回退 REST API: %s", detail[:200])
    ok2, detail2, data2 = _api_push_files(owner, repo, branch, files, message)
    if ok2:
        return True, detail2, "github_api", data2
    return False, detail2, "failed", data2


def _mcp_push_files(
    owner: str,
    repo: str,
    branch: str,
    files: list[dict[str, str]],
    message: str,
) -> tuple[bool, str, dict]:
    spec = github_spec()
    if not spec:
        return False, "GitHub MCP 未启用", {}
    ok, raw = call_mcp_tool(
        spec,
        "push_files",
        {
            "owner": owner,
            "repo": repo,
            "branch": branch,
            "files": files,
            "message": message,
        },
        timeout=max(cfg.MCP_TOOL_TIMEOUT_SEC, 120),
    )
    data = parse_jsonish(raw) if ok else None
    if isinstance(data, dict):
        return True, raw[:500], data
    return ok, raw[:500], {}


def _mcp_create_pr(
    owner: str,
    repo: str,
    title: str,
    body: str,
    head: str,
    base: str,
    *,
    draft: bool = False,
) -> tuple[bool, str, dict]:
    spec = github_spec()
    if not spec:
        return False, "GitHub MCP 未启用", {}
    ok, raw = call_mcp_tool(
        spec,
        "create_pull_request",
        {
            "owner": owner,
            "repo": repo,
            "title": title,
            "body": body,
            "head": head,
            "base": base,
            "draft": draft,
        },
        timeout=cfg.MCP_TOOL_TIMEOUT_SEC,
    )
    data = parse_jsonish(raw) if ok else None
    if isinstance(data, dict):
        return True, raw[:800], data
    # MCP 有时返回 markdown 文本，尝试提取 html_url
    if ok and "http" in raw:
        m = re.search(r"https://github\.com/[^\s\)]+", raw)
        if m:
            return True, raw[:800], {"html_url": m.group(0)}
    return ok, raw[:800], {}


def _api_create_pr(
    owner: str,
    repo: str,
    title: str,
    body: str,
    head: str,
    base: str,
    *,
    draft: bool = False,
) -> tuple[bool, dict]:
    resp = _github_api(
        "POST",
        f"/repos/{owner}/{repo}/pulls",
        {
            "title": title,
            "body": body,
            "head": head,
            "base": base,
            "draft": draft,
        },
    )
    if resp.get("ok") is False or resp.get("error"):
        return False, resp
    return True, resp


def _extract_pr_url(data: dict) -> str:
    return str(
        data.get("html_url")
        or (data.get("pull_request") or {}).get("html_url")
        or data.get("url")
        or ""
    )


def create_github_pr_from_deliver(
    state: dict[str, Any],
    code_changes: dict | None = None,
    *,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """
    Deliver 完成后：push_files → create_pull_request。
    需配置 GITHUB_TOKEN、GITHUB_OWNER、GITHUB_REPO。
    """
    meta: dict[str, Any] = {"enabled": cfg.GITHUB_MCP_ENABLED}
    if not cfg.GITHUB_MCP_ENABLED:
        return {**meta, "skipped": True, "reason": "GITHUB_MCP_ENABLED=false"}
    if not cfg.GITHUB_TOKEN:
        return {**meta, "skipped": True, "reason": "未配置 GITHUB_TOKEN"}

    owner, repo = parse_github_repo(cfg.GITHUB_REPO, cfg.GITHUB_REPO_URL)
    if not owner or not repo:
        return {**meta, "ok": False, "error": "未配置 GITHUB_OWNER/GITHUB_REPO"}

    out_path = Path(output_dir or state.get("output_dir") or "")
    if not out_path.is_dir():
        return {**meta, "ok": False, "error": f"输出目录无效: {out_path}"}

    run_name = out_path.name
    if run_name == "output" or not run_name.startswith("run_"):
        # 若仍是 output 根目录，取最新 run_* 子目录
        runs = sorted(out_path.glob("run_*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if runs:
            out_path = runs[0]
            run_name = out_path.name
            meta["output_dir_resolved"] = str(out_path)

    branch = f"{cfg.GITHUB_BRANCH_PREFIX}/{run_name}"
    base = cfg.GITHUB_BASE_BRANCH or "main"
    meta.update({"owner": owner, "repo": repo, "branch": branch, "base": base, "output_dir": str(out_path)})

    files = collect_files_for_push(out_path, state)
    if not files:
        return {**meta, "ok": False, "error": "无可推送文件（backend/frontend 为空）"}
    meta["files_count"] = len(files)

    req_short = (state.get("requirement") or "流水线交付")[:80]
    title = f"[Agent] {req_short}"
    body = build_pr_body(state, code_changes)
    commit_msg = f"agent: {req_short} ({run_name})"

    if cfg.GITHUB_MCP_PUSH:
        push_ok, push_detail, push_via, _ = _push_files(
            owner, repo, branch, files, commit_msg
        )
        meta["push_via"] = push_via
        meta["push_detail"] = push_detail
        if not push_ok:
            return {
                **meta,
                "ok": False,
                "error": f"push_files 失败: {push_detail}",
            }
    else:
        meta["push_skipped"] = True

    head = branch
    pr_ok, pr_detail, pr_data = _mcp_create_pr(
        owner, repo, title, body, head, base, draft=cfg.GITHUB_PR_DRAFT
    )
    meta["pr_detail"] = pr_detail

    if not pr_ok or not _extract_pr_url(pr_data):
        api_ok, api_data = _api_create_pr(
            owner, repo, title, body, head, base, draft=cfg.GITHUB_PR_DRAFT
        )
        if api_ok:
            pr_data = api_data
            pr_ok = True
            meta["pr_via"] = "github_api"
        else:
            err = api_data.get("error", pr_detail)
            return {**meta, "ok": False, "error": f"create_pull_request 失败: {err}"}
    else:
        meta["pr_via"] = "github_mcp"

    pr_url = _extract_pr_url(pr_data)
    pr_number = pr_data.get("number")
    meta.update({"ok": True, "pr_url": pr_url, "pr_number": pr_number})
    return meta
