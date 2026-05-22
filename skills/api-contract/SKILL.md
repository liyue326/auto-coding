---
name: api-contract
description: REST API 契约规范，Supervisor 定义、前后端与评审共同遵循
---

# API 契约规范

## 路径约定
- 统一前缀 `/api/`
- 资源名小写复数，如 `/api/users`、`/api/auth/login`
- 鉴权接口放 `/api/auth/`

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
- 成功: `{"ok": true, "data": {...}}` 或直接返回业务对象
- 失败: `{"ok": false, "message": "...", "code": "ERR_XXX"}`

## 契约条目格式（Supervisor 输出）
```json
"POST /api/auth/login": {
  "body": {"username": "string", "password": "string"},
  "response": {"token": "string"}
}
```

## 前后端一致性
- 路径、方法、字段名必须完全一致
- 前端 `src/api/*.js` 中的 URL 与契约逐条对应
