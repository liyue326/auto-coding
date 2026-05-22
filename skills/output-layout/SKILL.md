---
name: output-layout
description: 流水线交付物目录结构，禁止覆盖原项目
---

# 交付目录规范

```
output/run_YYYYMMDD_HHMMSS/
├── backend/           # Python 后端
├── frontend/          # Vue 前端
├── reports/
│   └── summary.json   # 评审、测试、缺陷摘要
└── legacy_snapshot.txt  # 存量分析快照（可选）
```

## 规则
- 每次运行新建 run 目录，不覆盖历史 run
- 绝不写入用户指定的 legacy_path 原目录
- summary.json 包含 requirement、review、test、defects、delivered

## 合并到主项目（可配置）
- 环境变量 `MERGE_TARGET_ROOT` 指向主仓库根目录（如 `~/Desktop/all`）
- 后端合并到 `{MERGE_TARGET_ROOT}/{MERGE_BACKEND_SUBDIR}/`
- 前端合并到 `{MERGE_TARGET_ROOT}/{MERGE_FRONTEND_SUBDIR}/`
- `MERGE_ENABLED=true` 时 Deliver 节点自动拷贝；Streamlit 侧边栏可覆盖
