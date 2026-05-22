---
name: legacy-refactor
description: 存量老项目读取、分析与兼容改造策略
---

# 存量项目改造规范

## 分析原则
- 只读扫描外部目录，不修改原仓库文件
- 识别技术栈: `.py` → Python, `.vue` → Vue, `package.json` → Node

## 输出到独立目录
- 所有生成代码写入 `output/run_<时间戳>/`
- 原项目仅作参考，交付物在 output 下

## 改造策略
1. 保留现有 API 路径，新增接口走版本前缀 `/api/v2/`（若需破坏兼容）
2. 数据库变更用迁移 SQL，不直接删列
3. 前端逐步替换：先新增 Vue 页面，再改路由

## Supervisor 注意事项
- tasks 中标注 `legacy_compat: true` 若涉及老接口
- api_contract 与老项目路径冲突时，在 notes 说明迁移方案
