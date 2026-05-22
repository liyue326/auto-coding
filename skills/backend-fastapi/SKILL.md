---
name: backend-fastapi
description: Python FastAPI 后端结构与编码规范（按需求选用，非固定 CRUD）
---

# Python FastAPI 后端规范

## 原则
- **以用户原文需求为准**，不要默认做成登录/笔记/待办等业务
- 需要 HTTP API 时用 FastAPI；纯脚本/工具类需求可用 `scripts/` 或单文件模块

## 常见目录（按需创建）
```
backend/
├── models/          # 数据模型（需要时）
├── services/        # 业务逻辑（需要时）
├── api/routes.py    # HTTP 路由（需要时）
├── schema.sql       # SQLite DDL（需要持久化时）
└── tests/           # pytest（需要时）
```

## 编码要求
- 使用 `APIRouter`，按模块 `prefix="/api/xxx"`
- 请求体用 `BaseModel`；校验失败 `raise HTTPException(status_code=400, detail="...")`
- 若涉及密码：仅存 `password_hash`，禁止明文落库
- 服务层与路由层分离（复杂业务时）

## 依赖建议
- fastapi, uvicorn, pydantic（Web API 场景）
