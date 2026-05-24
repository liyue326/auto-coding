---
name: conversation-memory
description: 多轮对话记忆（LangGraph Checkpoint 为主）
---

# 多轮对话记忆

## 主存储：LangGraph Checkpoint

- 技术：`SqliteSaver`（`langgraph-checkpoint-sqlite`）
- 库文件：`data/checkpoints/langgraph.db`
- 线程键：`config={"configurable": {"thread_id": "<对话线程ID>"}}`
- 状态字段：`conversation_turns`（`Annotated[list, append]`），Deliver 时追加一轮

## 流程

1. `reset_run`：新需求清空上一轮 `backend_files` 等，**保留** Checkpoint 里已有 `conversation_turns`
2. `_build_initial_state`：`get_state(thread_id)` 读出历史 → 格式化为 Prompt
3. `invoke/stream`：带同一 `thread_id` 写 Checkpoint
4. `Deliver`：追加 `conversation_turns`（自动持久化）

## 可选 JSONL

- `CONVERSATION_USE_JSONL=true` 时双写 `data/conversations/*.jsonl`（调试/导出）

## 配置

- `LANGGRAPH_CHECKPOINT_ENABLED=true`
- `CONVERSATION_USE_CHECKPOINT=true`
- `CONVERSATION_DEFAULT_THREAD=default`

## 与 Chroma 区别

- Checkpoint：整图状态 + 对话轮次（用户说了什么、交付摘要）
- Chroma：仅成功 BugFix 的向量案例
