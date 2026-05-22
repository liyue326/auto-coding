---
name: backend-fastapi
description: Python FastAPI 后端结构与编码规范
---

# Python FastAPI 后端规范

## 目录结构
```
backend/
├── models/          # 数据模型 / dataclass
├── services/        # 业务逻辑，不直接处理 HTTP
├── api/routes.py    # 路由与 Pydantic 请求体
├── schema.sql       # SQLite DDL
└── tests/           # pytest
```

## 编码要求
- 使用 `APIRouter`，按模块 `prefix="/api/xxx"`
- 请求体用 `BaseModel`，返回 dict 或 Pydantic 模型
- 密码仅存 `password_hash`，禁止明文落库
- 校验失败 `raise HTTPException(status_code=400, detail="...")`
- 服务层函数应有类型注解

## 依赖建议
- fastapi, uvicorn, pydantic
- 密码: passlib[bcrypt] 或 hashlib（演示可用简化 hash）

## 示例路由
```python
@router.post("/register")
def register(body: RegisterBody):
    ...
```
