---
name: memory-fix-rag
description: Chroma 修复经验 RAG 使用说明
---

# 修复经验向量库

## 入库条件（仅成功修复）
- `test_passed=true`
- 经历过至少一轮 `BugFix`（`fix_experiences` 非空）
- Deliver 时写入**最后一轮**修复记录

## BugFix 检索
- 按 `requirement + dev_scope + defects` 检索 Top-K
- Prompt 中标注：仅参考修复手法，不得改变用户业务需求

## 配置
- `MEMORY_ENABLED=true`
- `CHROMA_PERSIST_DIR=data/chroma`
- `EMBEDDING_MODEL=text-embedding-v3`（DashScope）
