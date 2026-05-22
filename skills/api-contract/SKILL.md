---
name: api-contract
description: REST API 契约规范（仅当需求需要前后端协作时使用）
---

# API 契约规范

## 何时填写
- 用户需求涉及前后端数据交互时，由编排阶段定义 `api_contract`
- 纯前端 UI、静态页、绘图 demo 等：**可为空对象 `{}`**

## 路径约定
- 统一前缀 `/api/`
- 资源名小写、语义清晰，如 `/api/items`、`/api/counter`

## 方法
| 操作 | 方法 |
|------|------|
| 查询 | GET |
| 创建 | POST |
| 全量更新 | PUT |
| 部分更新 | PATCH |
| 删除 | DELETE |

## 请求 / 响应
- Content-Type: `application/json`
- 成功: 返回业务对象或 `{"ok": true, "data": {...}}`
- 失败: HTTP 4xx/5xx + 明确 detail/message

## 契约条目格式（编排阶段输出示例）
```json
"GET /api/items": {
  "response": [{"id": 1, "title": "string"}]
}
```

## 前后端一致性
- 路径、方法、字段名与契约一致
- 前端仅在需要时增加 `src/api/*.js`，URL 与契约逐条对应
