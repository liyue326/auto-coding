"""
Streamlit 可视化操作界面
展示: 流程步骤、各 Agent 产出、Mermaid 流程图、运行日志
启动: streamlit run app.py
"""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

import config as cfg
from pipeline import get_mermaid_diagram, run_pipeline_stream, scan_legacy_project

st.set_page_config(
    page_title=cfg.STREAMLIT_PAGE_TITLE,
    page_icon=cfg.STREAMLIT_PAGE_ICON,
    layout="wide",
)

# ── 样式 ────────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
    .phase-badge { padding:4px 10px; border-radius:6px; background:#1e3a5f; color:#93c5fd; font-size:0.85rem; }
    .log-box { font-family: monospace; font-size: 0.82rem; background: #0f172a; color: #e2e8f0;
               padding: 12px; border-radius: 8px; max-height: 360px; overflow-y: auto; }
    </style>
    """,
    unsafe_allow_html=True,
)

AGENT_META = {
    "Supervisor": ("🎯", "任务拆分 · 流程管控"),
    "BackendDev": ("⚙️", "数据表 · API · 服务层"),
    "FrontendDev": ("🖥️", "Vue3 页面 · 路由 · API"),
    "CodeReview": ("🔍", "规范 · 一致性 · 安全"),
    "TestAgent": ("🧪", "单元/接口测试"),
    "BugFix": ("🔧", "缺陷修复"),
    "Deliver": ("📦", "独立目录交付"),
    "Join": ("🔗", "并行汇合"),
}


def render_flowchart():
    st.subheader("项目运行流程图")
    st.markdown(get_mermaid_diagram())
    st.caption("上方为 Mermaid 语法流程图；也可在支持 Mermaid 的编辑器中渲染。")


def render_agent_cards(outputs: dict):
    st.subheader("各 Agent 产出")
    if not outputs:
        st.info("运行流水线后在此展示各角色产出摘要。")
        return
    cols = st.columns(2)
    for i, (name, data) in enumerate(outputs.items()):
        icon, desc = AGENT_META.get(name, ("🤖", ""))
        with cols[i % 2]:
            with st.expander(f"{icon} **{name}** — {desc}", expanded=(name in ("Supervisor", "Deliver"))):
                st.json(data)


def render_code_preview(result: dict):
    st.subheader("生成代码预览")
    tab_be, tab_fe = st.tabs(["后端文件", "前端文件"])
    with tab_be:
        for path, code in (result.get("backend_files") or {}).items():
            st.markdown(f"**`{path}`**")
            st.code(code, language="python" if path.endswith(".py") else "sql")
    with tab_fe:
        for path, code in (result.get("frontend_files") or {}).items():
            st.markdown(f"**`{path}`**")
            if path.endswith(".vue"):
                lang = "html"
            elif path.endswith(".js"):
                lang = "javascript"
            else:
                lang = "text"
            st.code(code, language=lang)


# ── 侧边栏 ──────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚙️ 运行配置")
    st.caption(f"Mock 模式: **{'开启' if cfg.USE_MOCK_LLM else '关闭'}**")
    st.caption(f"模型: `{cfg.LLM_MODEL}`")
    output_dir = st.text_input("输出根目录", value=str(cfg.DEFAULT_OUTPUT_DIR))

    st.markdown("**合并到主项目**")
    merge_enabled = st.checkbox(
        "交付后自动合并代码",
        value=cfg.MERGE_ENABLED,
        help="将生成的 backend/、frontend/ 拷贝到你指定的主项目目录",
    )
    merge_target = st.text_input(
        "主项目根目录",
        value=cfg.MERGE_TARGET_ROOT,
        placeholder="/Users/liyue/Desktop/all",
        disabled=not merge_enabled,
    )
    mc1, mc2 = st.columns(2)
    with mc1:
        merge_be = st.text_input(
            "后端子目录名",
            value=cfg.MERGE_BACKEND_SUBDIR,
            disabled=not merge_enabled,
        )
    with mc2:
        merge_fe = st.text_input(
            "前端子目录名",
            value=cfg.MERGE_FRONTEND_SUBDIR,
            disabled=not merge_enabled,
        )
    default_merge_mode = "overwrite" if cfg.MERGE_OVERWRITE else cfg.MERGE_CONFLICT_MODE
    merge_mode = st.selectbox(
        "已存在文件如何处理",
        options=["overwrite", "manual", "skip", "backup"],
        index=["overwrite", "manual", "skip", "backup"].index(default_merge_mode)
        if default_merge_mode in ("overwrite", "manual", "skip", "backup")
        else 0,
        format_func=lambda m: {
            "overwrite": "覆盖（推荐，新代码写入主项目）",
            "manual": "人工对比（不覆盖，导出 .current/.incoming）",
            "skip": "跳过已存在文件",
            "backup": "先备份 .bak 再覆盖",
        }.get(m, m),
        disabled=not merge_enabled,
        help="此前「新文件能进、老文件进不去」多为 manual 模式：只合并新路径，已存在且内容不同的文件不会覆盖",
    )
    if merge_enabled and merge_target:
        st.caption(
            f"将合并到：`{merge_target}/{merge_be}` 与 `{merge_target}/{merge_fe}` · 策略 `{merge_mode}`"
        )

    legacy_path = st.text_input(
        "存量项目路径（可选，任意本地目录）",
        placeholder="/path/to/old-project",
    )
    if legacy_path:
        if st.button("预览存量扫描", use_container_width=True):
            with st.spinner("扫描中…"):
                info = scan_legacy_project(legacy_path)
            st.json(info)

    st.divider()
    st.markdown("**流程说明**")
    st.markdown(
        """
        1. Supervisor 拆分任务（识别 scope）  
        2. 按 scope **并行** 开发（可仅前端或仅后端）  
        3. 代码评审 → 条件分支  
        4. 自动化测试  
        5. 有 BUG → **修复子图** 循环  
        6. 通过后 **独立目录** 交付  
        """
    )

# ── 主区域 ──────────────────────────────────────────────────────────────
st.title("🤖 多工程师多智能体协作开发系统")
st.markdown(
    "基于 **LangGraph** 的自研调度编排 · 区别于 IDE 内置单点生成，支持流程自定义、存量改造、协作管控"
)

render_flowchart()

st.divider()

requirement = st.text_area(
    "业务需求",
    height=140,
    placeholder="自然语言描述任意需求，例如：画一个圆只要前端、做一个计数器、实现某某 API…",
    value="",
)

col_run, col_clear = st.columns([1, 4])
with col_run:
    run_btn = st.button("▶ 启动流水线", type="primary", use_container_width=True)

if "last_result" not in st.session_state:
    st.session_state.last_result = None

if run_btn:
    if not requirement.strip():
        st.error("请填写业务需求")
    else:
        st.subheader("实时执行日志（流式）")
        log_live = st.empty()
        metric_live = st.empty()
        progress = st.progress(0, text="启动中…")

        all_logs: list[str] = []
        result = None
        phase_weights = {
            "Supervisor": 10,
            "BackendDev": 30,
            "FrontendDev": 30,
            "Join": 45,
            "CodeReview": 60,
            "TestAgent": 80,
            "BugFix": 85,
            "Deliver": 100,
        }

        for event in run_pipeline_stream(
            requirement=requirement,
            legacy_path=legacy_path or "",
            output_dir=output_dir,
            merge_target=merge_target if merge_enabled else "",
            merge_enabled=merge_enabled,
            merge_backend_subdir=merge_be,
            merge_frontend_subdir=merge_fe,
            merge_conflict_mode=merge_mode if merge_enabled else "",
        ):
            etype = event.get("type")
            if etype == "start":
                all_logs.append(f"▶ {event.get('message')}")
                log_live.code("\n".join(all_logs))
                continue

            if etype == "progress":
                state = event.get("state") or {}
                phase = event.get("phase") or state.get("phase") or ""
                new_logs = event.get("logs") or []
                all_logs.extend(new_logs)
                log_live.code("\n".join(all_logs))

                pct = phase_weights.get(phase, 0)
                if pct:
                    progress.progress(min(pct, 99) / 100.0, text=f"{phase or '执行中'}…")

                review = event.get("review_result") or state.get("review_result")
                test = event.get("test_result") or state.get("test_result")
                if review or test:
                    c1, c2, c3 = metric_live.columns(3)
                    with c1:
                        static_s = review.get("static_score", "-") if review else "-"
                        final_s = review.get("score", "-") if review else "-"
                        st.metric("评审得分", final_s, delta=f"静态{static_s}")
                    with c2:
                        st.metric("测试缺陷", len(state.get("defects") or []))
                    with c3:
                        st.metric("修复轮次", state.get("fix_round", 0))
                continue

            if etype == "done":
                result = event.get("state")
                progress.progress(1.0, text="完成")
                all_logs.append("■ 流水线执行完毕")
                log_live.code("\n".join(all_logs))
                break

            if etype == "error":
                st.error(event.get("message", "执行失败"))
                result = event.get("state")
                log_live.code("\n".join(all_logs + [f"✖ {event.get('message')}"]))
                break

        st.session_state.last_result = result

if col_clear.button("清空结果"):
    st.session_state.last_result = None
    st.rerun()

result = st.session_state.last_result

if result:
    st.success(
        f"流水线完成 · 交付: **{result.get('delivered')}** · "
        f"输出: `{result.get('output_dir', '-')}`"
    )

    # 流程步骤时间线
    st.subheader("流程步骤")
    logs = result.get("logs") or []
    for line in logs:
        agent = line.split("]")[0].replace("[", "") if "]" in line else ""
        icon = AGENT_META.get(agent, ("•", ""))[0]
        st.markdown(f"{icon} `{line}`")

    st.markdown('<div class="log-box">' + "<br>".join(logs) + "</div>", unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    review = result.get("review_result") or {}
    test = result.get("test_result") or {}
    with c1:
        final_s = review.get("score", "-")
        static_s = review.get("static_score")
        st.metric(
            "评审得分",
            final_s,
            delta=f"静态{static_s}" if static_s is not None else None,
        )
    with c2:
        st.metric("测试缺陷", len(result.get("defects") or []))
    with c3:
        st.metric("修复轮次", result.get("fix_round", 0))

    scope = result.get("dev_scope") or (result.get("agent_outputs") or {}).get("Supervisor", {}).get("dev_scope")
    if scope:
        st.info(f"本次开发范围：**{scope}**（fullstack=全栈 · frontend_only=仅前端 · backend_only=仅后端）")
    render_agent_cards(result.get("agent_outputs") or {})

    if result.get("legacy_analysis"):
        with st.expander("存量项目分析"):
            st.json(result["legacy_analysis"])

    if review:
        with st.expander("评审详情"):
            st.json(review)
    if test:
        with st.expander("测试结果 / 缺陷清单"):
            st.json(test)

    render_code_preview(result)

    out = result.get("output_dir")
    if out and Path(out).exists():
        st.info(f"代码已写入独立目录: `{out}`")

    merge = result.get("merge_result") or {}
    if merge.get("needs_manual_resolution"):
        st.warning(
            f"部分文件未覆盖（模式 `{merge.get('conflict_mode')}`）："
            f"{len(merge.get('conflicts') or [])} 个冲突。"
            f"新文件已合并；已存在文件见 `{merge.get('conflicts_report', '')}`"
        )
        for c in merge.get("conflicts") or []:
            st.markdown(
                f"- `{c.get('path')}` → 对比 `{c.get('current_copy')}` 与 `{c.get('incoming_copy')}`"
            )
        st.caption(
            "若要直接覆盖主项目：侧边栏选「覆盖」后重跑，或执行 "
            "`python3 pipeline.py --merge-run output/run_xxx --merge-mode overwrite`"
        )
    elif merge.get("ok"):
        ow = len(merge.get("overwritten") or [])
        st.success(
            f"已合并到主项目 · backend `{merge.get('backend_dir')}` · "
            f"frontend `{merge.get('frontend_dir')}`"
            + (f" · 覆盖 {ow} 个已存在文件" if ow else "")
        )
    elif merge and not merge.get("skipped"):
        st.warning(f"合并未成功: {merge.get('error', '未知原因')}")

else:
    st.info("填写需求后点击「启动流水线」。终端会打印各节点 DEBUG 日志。")

st.divider()
st.caption("CLI 启动: `python pipeline.py -r \"你的需求\" -l /path/to/legacy` · UI: `streamlit run app.py`")
