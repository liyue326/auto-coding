"""
Streamlit 可视化操作界面
展示: 流程步骤、各 Agent 产出、Mermaid 流程图、运行日志
启动: streamlit run app.py
"""
from __future__ import annotations

import json
import sys
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

# Session State 须在侧边栏之前初始化
if "last_result" not in st.session_state:
    st.session_state.last_result = None
if "conversation_thread_id" not in st.session_state:
    st.session_state.conversation_thread_id = cfg.CONVERSATION_DEFAULT_THREAD

AGENT_META = {
    "PrepareWorkspace": ("📂", "隔离导入 · 快照与索引"),
    "ProjectAnalyst": ("🔬", "结构扫描 · 风格 · 可复用组件"),
    "Supervisor": ("🎯", "Planner · 任务拆分"),
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


def render_code_changes(result: dict):
    """展示相对老项目快照的代码变更（unified diff）。"""
    changes = result.get("code_changes") or {}
    if not changes and result.get("output_dir"):
        path = Path(result["output_dir"]) / "reports" / "changes.json"
        if path.exists():
            try:
                changes = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                changes = {}

    if not changes:
        return

    st.subheader("代码变更")
    summary = changes.get("summary") or {}
    st.caption(changes.get("text_summary") or "")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("修改", summary.get("modified", 0))
    with c2:
        st.metric("新增", summary.get("added", 0))
    with c3:
        st.metric("测试文件", summary.get("generated", 0))
    with c4:
        st.metric("未变", summary.get("unchanged", 0))

    interesting = [
        f
        for f in (changes.get("files") or [])
        if f.get("status") in ("modified", "new", "generated")
    ]
    if not interesting:
        st.info("相对快照无实质变更（或无可对比基线）。")
        return

    for item in interesting:
        side = item.get("side", "")
        path = item.get("path", "")
        status = item.get("status", "")
        badge = {"modified": "修改", "new": "新建", "generated": "测试"}.get(status, status)
        title = f"`{side}/{path}` · **{badge}** · {item.get('summary', '')}"
        with st.expander(title, expanded=(status == "modified" and len(interesting) <= 3)):
            diff_text = item.get("unified_diff") or ""
            if diff_text:
                if item.get("truncated"):
                    st.caption("diff 过长，已截断；完整内容见输出目录 reports/patches/")
                st.code(diff_text, language="diff")
            elif status == "new":
                be = (result.get("backend_files") or {}).get(path)
                fe = (result.get("frontend_files") or {}).get(path)
                code = be or fe or ""
                if code:
                    lang = "python" if path.endswith(".py") else (
                        "javascript" if path.endswith(".js") else "html"
                    )
                    st.code(code, language=lang)
            else:
                st.caption("无 diff 文本")


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
    if cfg.USE_STRUCTURED_OUTPUT:
        st.caption(f"结构化输出: **{cfg.STRUCTURED_OUTPUT_METHOD}**")
    mem_on = st.checkbox(
        "修复经验库 (Chroma)",
        value=cfg.MEMORY_ENABLED,
        help="仅当：测试通过 + 本轮走过 BugFix 时，按修复轮次入库（每轮一条）；未进 BugFix 的 run 不会增加条数",
    )
    if mem_on:
        try:
            from memory.store import collection_count

            n = collection_count()
            st.caption(f"库内案例: **{n}** 条")
        except Exception:
            st.caption("库内案例: （未安装 chromadb 或尚未初始化）")
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

    st.markdown("**MCP 增强**")
    st.caption(f"总开关: **{'开' if cfg.MCP_ENABLED else '关'}**（`.env` 中 `MCP_ENABLED`）")
    mcp_e2e_url = st.text_input(
        "E2E 前端地址",
        value=cfg.MCP_E2E_BASE_URL,
        placeholder="http://localhost:5173",
        help="配置后 TestAgent 用 Playwright MCP 打开页面；需先 npm run dev",
    )
    if mcp_e2e_url != cfg.MCP_E2E_BASE_URL:
        st.caption("请在 .env 设置 MCP_E2E_BASE_URL 并重启 Streamlit 以持久生效")
    st.caption(
        f"文档 MCP: Context7={'开' if cfg.MCP_CONTEXT7_ENABLED else '关'} · "
        f"Fetch={'开' if cfg.MCP_FETCH_ENABLED else '关'} · "
        f"SQL={'开' if cfg.MCP_SQL_ENABLED else '关'}"
    )
    if cfg.GITHUB_MCP_ENABLED:
        gh = f"{cfg.GITHUB_OWNER}/{cfg.GITHUB_REPO}" if cfg.GITHUB_REPO else "未配置"
        gt = "已配置" if cfg.GITHUB_TOKEN else "未配置 GITHUB_TOKEN"
        st.caption(f"GitHub PR: `{gh}` → `{cfg.GITHUB_BASE_BRANCH}` · Token: {gt}")
    if st.button("运行 MCP 自检", help="等同 python3 scripts/prepare_mcp.py"):
        import subprocess

        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parent / "scripts" / "prepare_mcp.py")],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parent),
        )
        st.code(proc.stdout or proc.stderr or "(无输出)")

    st.markdown("**多轮对话记忆**")
    conv_on = st.checkbox(
        "启用对话记忆",
        value=cfg.CONVERSATION_MEMORY_ENABLED,
        help="默认用 LangGraph SqliteSaver Checkpoint 按 thread_id 持久化；可选 JSONL 双写",
    )
    thread_id = st.text_input(
        "对话线程 ID",
        value=st.session_state.conversation_thread_id,
        help="同一 ID 共享历史，例如 default / project-all",
    )
    st.session_state.conversation_thread_id = (thread_id or cfg.CONVERSATION_DEFAULT_THREAD).strip()
    if conv_on:
        try:
            from memory import load_turns

            from memory.checkpoint import load_conversation_turns
            from pipeline import PIPELINE

            tid = st.session_state.conversation_thread_id
            turns = []
            if cfg.CONVERSATION_USE_CHECKPOINT and cfg.LANGGRAPH_CHECKPOINT_ENABLED:
                turns = load_conversation_turns(PIPELINE, tid)
            if not turns and cfg.CONVERSATION_USE_JSONL:
                turns = load_turns(tid)
            st.caption(
                f"本线程 **{len(turns)}** 轮对话记忆（每次点「启动流水线」+1，与单次需求内节点次数无关）"
            )
            with st.expander("历史对话", expanded=False):
                for t in turns[-5:]:
                    st.markdown(f"**{t.get('timestamp', '')}** · {t.get('requirement', '')[:60]}")
                    st.caption(t.get("summary", ""))
            if st.button("清空本线程对话", use_container_width=True):
                from memory import clear_thread
                from memory.checkpoint import clear_thread_checkpoint
                from pipeline import PIPELINE

                tid = st.session_state.conversation_thread_id
                if cfg.CONVERSATION_USE_CHECKPOINT:
                    clear_thread_checkpoint(PIPELINE, tid)
                if cfg.CONVERSATION_USE_JSONL:
                    clear_thread(tid)
                st.success("已清空（Checkpoint + JSONL）")
                st.rerun()
            if cfg.LANGGRAPH_CHECKPOINT_ENABLED:
                st.caption(
                    f"Checkpoint: `{cfg.LANGGRAPH_CHECKPOINT_DB}` · "
                    f"thread_id = 对话线程 ID"
                )
        except Exception as e:
            st.caption(f"对话记忆不可用: {e}")

    legacy_path = st.text_input(
        "存量项目路径（可选，任意本地目录）",
        value=cfg.DEFAULT_LEGACY_PATH or "",
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
        0. PrepareWorkspace 隔离复制老项目（不改原目录）  
        1. **Project Analyst** 生成项目上下文报告（Planner 前置）  
        2. Supervisor 拆分任务（识别 scope）  
        3. 按 scope **并行** 开发（可仅前端或仅后端）  
        4. 代码评审 → 条件分支  
        5. 自动化测试  
        6. 有 BUG → **修复子图**（Chroma 检索历史成功案例）  
        7. 通过后生成导出包；在**主区域底部**点「确认写入老项目」才写回 Desktop  
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
            "PrepareWorkspace": 3,
            "ProjectAnalyst": 8,
            "Supervisor": 12,
            "BackendDev": 30,
            "FrontendDev": 30,
            "Join": 45,
            "CodeReview": 60,
            "TestAgent": 80,
            "BugFix": 85,
            "Deliver": 100,
        }

        conv_thread = (
            st.session_state.conversation_thread_id
            if conv_on
            else ""
        )
        for event in run_pipeline_stream(
            requirement=requirement,
            legacy_path=legacy_path or "",
            output_dir=output_dir,
            merge_target=merge_target if merge_enabled else "",
            merge_enabled=merge_enabled,
            merge_backend_subdir=merge_be,
            merge_frontend_subdir=merge_fe,
            merge_conflict_mode=merge_mode if merge_enabled else "",
            conversation_thread_id=conv_thread,
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
                if new_logs:
                    all_logs.extend(new_logs)
                    log_live.code("\n".join(all_logs[-80:]))
                    log_live.caption(
                        f"▶ 当前节点: **{phase or '…'}** · 本步新增 {len(new_logs)} 条 · 累计 {len(all_logs)} 条"
                    )
                else:
                    log_live.code("\n".join(all_logs[-80:]) if all_logs else "（等待日志…）")

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
        if conv_on and result:
            try:
                from memory import load_turns

                st.session_state.conversation_turn_count = len(
                    load_turns(st.session_state.conversation_thread_id)
                )
            except Exception:
                pass

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

    conv_hist = result.get("conversation_history") or []
    if conv_hist:
        with st.expander(f"多轮对话记忆（本线程 {len(conv_hist)} 轮）"):
            for t in conv_hist[-8:]:
                st.markdown(f"**{t.get('timestamp', '')}** — {t.get('requirement', '')}")
                st.caption(t.get("summary", ""))

    report = result.get("project_context_report") or {}
    if report.get("ok"):
        with st.expander("Project Analyst 项目上下文报告"):
            st.markdown(f"**摘要**：{report.get('summary', '')}")
            if report.get("report_path"):
                st.caption(f"报告文件：`{report['report_path']}`")
            st.json(report)
    elif result.get("legacy_analysis"):
        with st.expander("存量项目分析（索引）"):
            st.json(result["legacy_analysis"])

    if review:
        with st.expander("评审详情"):
            st.json(review)
    if test:
        with st.expander("测试结果 / 缺陷清单"):
            st.json(test)

    github_pr = result.get("github_pr") or (result.get("agent_outputs") or {}).get("Deliver", {}).get("github_pr") or {}
    if github_pr and github_pr.get("pr_url"):
        st.success(f"GitHub PR: [{github_pr.get('pr_url')}]({github_pr.get('pr_url')})")
    elif github_pr and not github_pr.get("skipped"):
        err = github_pr.get("error") or github_pr.get("push_detail")
        if err:
            st.caption(f"GitHub PR 未创建: {err}")

    mcp_results = result.get("mcp_results") or (test or {}).get("mcp") or {}
    if mcp_results:
        with st.expander("MCP 检测（E2E / SQL）"):
            st.json(mcp_results)

    render_code_changes(result)
    render_code_preview(result)

    out = result.get("output_dir")
    if out and Path(out).exists():
        st.info(f"代码已写入独立目录: `{out}`")
        summary_path = Path(out) / "reports" / "summary.json"
        if summary_path.exists():
            try:
                summ = json.loads(summary_path.read_text(encoding="utf-8"))
                mi = summ.get("memory_ingested", 0)
                test_ok = (summ.get("test") or {}).get("passed")
                if mi:
                    st.caption(f"本次已入库修复经验 **{mi}** 条")
                elif summ.get("fix_experiences") or result.get("fix_round"):
                    st.caption(
                        "本次 **未入库**（通常因最终测试未通过；详见上方日志 `[Deliver] 修复经验未入库`）"
                    )
                elif test_ok:
                    st.caption("本次测试通过但未经历 BugFix，修复经验库不增加条数")
            except Exception:
                pass

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

    # ── 人工确认写回老项目（默认不自动改原路径）────────────────────
    export_pkg = result.get("export_package") or {}
    legacy_target = (result.get("legacy_path") or legacy_path or cfg.DEFAULT_LEGACY_PATH).strip()
    merge = result.get("merge_result") or {}
    can_writeback = (
        result.get("delivered")
        and out
        and legacy_target
        and Path(out).exists()
        and not merge.get("ok")
    )
    if can_writeback or export_pkg.get("ok"):
        st.divider()
        st.subheader("写回老项目（需人工确认）")
        st.markdown(
            "流水线只把新代码放在 `output/run_xxx` 和 `data/workspaces/.../export/`。"
            "**不会**自动修改你 Desktop 上的老项目，避免误覆盖。"
        )
        if export_pkg.get("export_dir"):
            files_dir = export_pkg.get("manifest", {}).get("files_dir") or export_pkg.get(
                "export_dir"
            )
            st.caption(f"建议先审阅导出包: `{files_dir}`")
        if merge.get("reason") == "export_pending" or export_pkg.get("ok"):
            st.info("日志里的「未写回老项目原路径」表示在等待你在此确认。")

        wb_target = st.text_input(
            "写入目标（老项目根目录）",
            value=legacy_target,
            key="writeback_legacy_path",
        )
        wb_mode = st.selectbox(
            "已存在文件策略",
            options=["overwrite", "manual", "skip", "backup"],
            index=0,
            key="writeback_merge_mode",
            format_func=lambda m: {
                "overwrite": "覆盖",
                "manual": "人工对比（不覆盖）",
                "skip": "跳过已存在",
                "backup": "先 .bak 再覆盖",
            }.get(m, m),
        )
        st.caption(
            f"将 `{out}/backend` → `{wb_target}/{result.get('merge_backend_subdir', cfg.MERGE_BACKEND_SUBDIR)}`，"
            f"`{out}/frontend` → `{wb_target}/{result.get('merge_frontend_subdir', cfg.MERGE_FRONTEND_SUBDIR)}`"
        )
        if st.button("确认写入老项目", type="primary", key="btn_writeback_legacy"):
            if not wb_target.strip():
                st.error("请填写老项目路径")
            else:
                with st.spinner("正在写入老项目…"):
                    try:
                        from legacy import export_to_legacy

                        m = export_to_legacy(
                            Path(out),
                            wb_target.strip(),
                            approved=True,
                            backend_subdir=result.get("merge_backend_subdir")
                            or cfg.MERGE_BACKEND_SUBDIR,
                            frontend_subdir=result.get("merge_frontend_subdir")
                            or cfg.MERGE_FRONTEND_SUBDIR,
                            conflict_mode=wb_mode,
                        )
                        result["merge_result"] = m
                        st.session_state.last_result = result
                        if m.get("ok"):
                            st.success(f"已写入: {wb_target}")
                        else:
                            st.error(m.get("error", "写入失败"))
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))

else:
    st.info("填写需求后点击「启动流水线」。终端会打印各节点 DEBUG 日志。")

st.divider()
st.caption("CLI 启动: `python pipeline.py -r \"你的需求\" -l /path/to/legacy` · UI: `streamlit run app.py`")
