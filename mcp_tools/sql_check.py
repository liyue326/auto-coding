"""SQL 校验：本地 SQLite 执行 DDL + 可选 Postgres MCP。"""
from __future__ import annotations

import logging
import re
import sqlite3
from typing import Any

import config as cfg
from mcp_tools.client import call_mcp_tool, postgres_spec

logger = logging.getLogger("multi-agent.mcp")


def _extract_schema_sql(backend_files: dict[str, str]) -> tuple[str, str]:
    for path, content in (backend_files or {}).items():
        norm = path.replace("\\", "/").lower()
        if norm.endswith("schema.sql") or norm.endswith(".sql"):
            return path, content or ""
    return "", ""


def _split_sql_statements(sql: str) -> list[str]:
    """粗略拆分 DDL 语句（按 ; 结尾）。"""
    parts: list[str] = []
    buf: list[str] = []
    for line in (sql or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        buf.append(line)
        if ";" in line:
            stmt = "\n".join(buf).strip()
            if stmt:
                parts.append(stmt)
            buf = []
    tail = "\n".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _sqlite_validate_ddl(schema_sql: str) -> tuple[list[dict], dict[str, Any]]:
    issues: list[dict] = []
    report: dict[str, Any] = {"engine": "sqlite", "statements": 0, "ok": True}
    if not schema_sql.strip():
        return issues, {**report, "skipped": "no schema.sql"}

    conn = sqlite3.connect(":memory:")
    try:
        stmts = _split_sql_statements(schema_sql)
        report["statements"] = len(stmts)
        for i, stmt in enumerate(stmts, 1):
            try:
                conn.executescript(stmt if stmt.rstrip().endswith(";") else stmt + ";")
            except sqlite3.Error as e:
                report["ok"] = False
                issues.append(
                    {
                        "id": f"SQL-sqlite-{i}",
                        "module": "backend",
                        "desc": f"schema.sql 第 {i} 条 DDL 在 SQLite 校验失败: {e}",
                        "severity": "high",
                        "source": "sqlite_validate",
                    }
                )
        if report["ok"]:
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            report["tables"] = [r[0] for r in cur.fetchall()]
    finally:
        conn.close()
    return issues, report


def _postgres_mcp_validate(schema_sql: str) -> tuple[list[dict], dict[str, Any]]:
    spec = postgres_spec()
    report: dict[str, Any] = {"engine": "postgres_mcp", "ok": True}
    if not spec:
        return [], {**report, "skipped": "postgres_mcp_disabled"}

    issues: list[dict] = []
    # 在临时 schema 中试跑（若 MCP 支持 query）
    ok, result = call_mcp_tool(
        spec,
        "query",
        {"sql": "SELECT current_database() AS db, version() AS ver LIMIT 1"},
        timeout=cfg.MCP_SQL_TIMEOUT_SEC,
    )
    report["connect"] = ok
    report["connect_detail"] = (result or "")[:400]
    if not ok:
        issues.append(
            {
                "id": "SQL-pg-connect",
                "module": "backend",
                "desc": f"Postgres MCP 连接失败: {result[:200]}",
                "severity": "medium",
                "source": "postgres_mcp",
            }
        )
        report["ok"] = False
        return issues, report

    stmts = [s for s in _split_sql_statements(schema_sql) if s.strip()]
    report["statements"] = len(stmts)
    for i, stmt in enumerate(stmts, 1):
        upper = stmt.upper()
        if not any(
            upper.lstrip().startswith(k)
            for k in ("CREATE", "ALTER", "DROP", "INSERT", "UPDATE", "DELETE")
        ):
            continue
        ok2, msg = call_mcp_tool(
            spec,
            "query",
            {"sql": stmt},
            timeout=cfg.MCP_SQL_TIMEOUT_SEC,
        )
        if not ok2:
            report["ok"] = False
            issues.append(
                {
                    "id": f"SQL-pg-{i}",
                    "module": "backend",
                    "desc": f"Postgres MCP 执行 DDL 失败（语句 {i}）: {msg[:200]}",
                    "severity": "high",
                    "source": "postgres_mcp",
                }
            )
    return issues, report


def _review_schema_quality(schema_sql: str, path: str) -> list[dict]:
    """轻量静态质量检查（评审用）。"""
    issues: list[dict] = []
    if not schema_sql.strip():
        return issues
    if "CREATE TABLE" not in schema_sql.upper() and "create table" not in schema_sql.lower():
        issues.append(
            {
                "id": "SQL-review-empty",
                "severity": "medium",
                "msg": f"{path} 未包含 CREATE TABLE 语句",
                "source": "sql_review",
            }
        )
    if re.search(r"password\s+\w+\s*[^,\n]*(?<!hashed)(?<!hash)", schema_sql, re.I):
        if "hash" not in schema_sql.lower():
            issues.append(
                {
                    "id": "SQL-review-pwd",
                    "severity": "medium",
                    "msg": f"{path} 可能存在明文 password 字段，建议 hash",
                    "source": "sql_review",
                }
            )
    return issues


def validate_backend_schema(
    backend_files: dict[str, str],
    *,
    for_review: bool = False,
) -> tuple[list[dict], dict[str, Any]]:
    """
    校验 backend schema.sql。
    for_review=True 时返回 review issues（含 msg 字段）；否则返回 test defects。
    """
    path, sql = _extract_schema_sql(backend_files)
    meta: dict[str, Any] = {"schema_path": path, "enabled": cfg.MCP_SQL_ENABLED}
    if not cfg.MCP_SQL_ENABLED:
        return [], {**meta, "skipped": "MCP_SQL_ENABLED=false"}
    if not sql:
        return [], {**meta, "skipped": "no schema.sql in backend_files"}

    all_issues: list[dict] = []
    sqlite_issues, sqlite_report = _sqlite_validate_ddl(sql)
    meta["sqlite"] = sqlite_report
    all_issues.extend(sqlite_issues)

    if cfg.MCP_POSTGRES_ENABLED and cfg.MCP_POSTGRES_URI:
        pg_issues, pg_report = _postgres_mcp_validate(sql)
        meta["postgres"] = pg_report
        all_issues.extend(pg_issues)

    if for_review:
        review = _review_schema_quality(sql, path)
        for i in all_issues:
            review.append(
                {
                    "severity": i.get("severity", "high"),
                    "msg": i.get("desc", ""),
                    "source": i.get("source", "sql_validate"),
                }
            )
        return review, meta

    return all_issues, meta
