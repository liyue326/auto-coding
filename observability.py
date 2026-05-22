"""
LangSmith 观测：链路追踪、多维度标签与流水线指标
文档: https://docs.smith.langchain.com/
"""
from __future__ import annotations

import logging
import os
from typing import Any

import config as cfg

logger = logging.getLogger("multi-agent.observability")

# 6 个 Agent + 交付/合并
AGENT_NAMES = (
    "Supervisor",
    "BackendDev",
    "FrontendDev",
    "CodeReview",
    "TestAgent",
    "BugFix",
    "Deliver",
    "Merge",
)


def setup_langsmith() -> bool:
    """
    启用 LangSmith 追踪（需在 .env 配置 API Key）。
    返回是否已成功开启。
    """
    if not cfg.LANGSMITH_TRACING:
        return False

    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_PROJECT"] = cfg.LANGSMITH_PROJECT

    api_key = cfg.LANGSMITH_API_KEY
    if not api_key:
        logger.warning(
            "已设置 LANGCHAIN_TRACING_V2=true，但未配置 LANGSMITH_API_KEY / LANGCHAIN_API_KEY"
        )
        return False
    os.environ["LANGCHAIN_API_KEY"] = api_key
    if cfg.LANGSMITH_ENDPOINT:
        os.environ["LANGCHAIN_ENDPOINT"] = cfg.LANGSMITH_ENDPOINT

    logger.info(
        "LangSmith 已开启 · project=%s · endpoint=%s",
        cfg.LANGSMITH_PROJECT,
        cfg.LANGSMITH_ENDPOINT or "default",
    )
    return True


def llm_run_config(agent: str, **metadata: Any) -> dict:
    """传给 ChatOpenAI.invoke/stream 的 RunnableConfig（标签 + 元数据）。"""
    meta = {
        "agent": agent,
        "model": cfg.LLM_MODEL,
        "mock": cfg.USE_MOCK_LLM,
        **{k: v for k, v in metadata.items() if v is not None},
    }
    return {
        "run_name": f"LLM:{agent}",
        "tags": [
            "multi-agent",
            f"agent:{agent}",
            f"model:{cfg.LLM_MODEL}",
            "mock" if cfg.USE_MOCK_LLM else "live",
        ],
        "metadata": meta,
    }


def graph_run_config(state: dict | None = None) -> dict:
    """LangGraph 整图 invoke/stream 的 config。"""
    state = state or {}
    return {
        "run_name": "multi-agent-pipeline",
        "tags": ["multi-agent", "langgraph", "pipeline"],
        "metadata": {
            "requirement_preview": (state.get("requirement") or "")[:300],
            "legacy_path": state.get("legacy_path") or "",
            "merge_enabled": state.get("merge_enabled"),
            "merge_target": state.get("merge_target") or cfg.MERGE_TARGET_ROOT,
        },
    }


def extract_pipeline_metrics(state: dict) -> dict[str, Any]:
    """从最终 state 抽取可在 LangSmith 面板筛选的指标。"""
    review = state.get("review_result") or {}
    test = state.get("test_result") or {}
    merge = state.get("merge_result") or {}
    return {
        "delivered": bool(state.get("delivered")),
        "review_score": review.get("score"),
        "review_static_score": review.get("static_score"),
        "review_passed": review.get("passed"),
        "review_round": state.get("review_round", 0),
        "test_passed": state.get("test_passed"),
        "test_failed_cases": test.get("failed"),
        "defect_count": len(state.get("defects") or []),
        "fix_round": state.get("fix_round", 0),
        "merge_ok": merge.get("ok"),
        "merge_conflict_mode": merge.get("conflict_mode"),
        "merge_conflict_count": len(merge.get("conflicts") or []),
        "merge_needs_manual": merge.get("needs_manual_resolution"),
        "backend_file_count": len(state.get("backend_files") or {}),
        "frontend_file_count": len(state.get("frontend_files") or {}),
        "output_dir": state.get("output_dir"),
        "error_count": len(state.get("errors") or []),
    }


def traceable_node(fn):
    """为 LangGraph 节点函数加上 LangSmith @traceable（未开启时原样返回）。"""
    if not cfg.LANGSMITH_TRACING:
        return fn
    try:
        from langsmith import traceable

        agent = fn.__name__.replace("node_", "").replace("_", " ").title().replace(" ", "")
        # node_backend_dev -> BackendDev
        name_map = {
            "supervisor": "Supervisor",
            "backenddev": "BackendDev",
            "frontenddev": "FrontendDev",
            "codereview": "CodeReview",
            "test": "TestAgent",
            "bugfix": "BugFix",
            "deliver": "Deliver",
        }
        key = fn.__name__.replace("node_", "").lower()
        run_name = name_map.get(key, fn.__name__)

        @traceable(name=run_name, run_type="chain")
        def wrapped(state):
            out = fn(state)
            try:
                from langsmith.run_helpers import get_current_run_tree

                run = get_current_run_tree()
                if run and isinstance(out, dict):
                    merged = {**state, **out}
                    metrics = {
                        "phase": out.get("phase") or run_name,
                        "log_count": len(merged.get("logs") or []),
                    }
                    if run_name == "CodeReview" and out.get("review_result"):
                        metrics["review_score"] = out["review_result"].get("score")
                    if run_name == "TestAgent" and out.get("test_result"):
                        metrics["test_passed"] = out["test_result"].get("passed")
                    if run_name == "Deliver" and out.get("merge_result"):
                        m = out["merge_result"]
                        metrics["merge_ok"] = m.get("ok")
                        metrics["merge_conflicts"] = len(m.get("conflicts") or [])
                    run.metadata.update(metrics)
            except Exception:
                pass
            return out

        wrapped.__name__ = fn.__name__
        return wrapped
    except ImportError:
        logger.warning("未安装 langsmith，跳过节点追踪")
        return fn


def traceable_tool(name: str, run_type: str = "tool"):
    """装饰工具函数（合并、扫描等）。"""
    if not cfg.LANGSMITH_TRACING:
        def passthrough(fn):
            return fn
        return passthrough
    try:
        from langsmith import traceable
        return traceable(name=name, run_type=run_type)
    except ImportError:
        def passthrough(fn):
            return fn
        return passthrough


def log_pipeline_run(state: dict, *, run_id: str = "") -> None:
    """流水线结束后写入汇总指标（显示在 LangSmith Run 的 outputs/metadata）。"""
    if not cfg.LANGSMITH_TRACING:
        return
    metrics = extract_pipeline_metrics(state)
    metrics["run_id"] = run_id
    try:
        from langsmith import traceable

        @traceable(name="pipeline_summary", run_type="chain")
        def _summary(m: dict):
            return m

        _summary(metrics)
        logger.info("LangSmith 指标已记录: %s", metrics)
    except Exception as e:
        logger.debug("LangSmith 指标记录跳过: %s", e)
