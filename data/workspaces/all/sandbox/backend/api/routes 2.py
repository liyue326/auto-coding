"""REST 路由 — 与 api_contract 对齐"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/auth")

class RegisterBody(BaseModel):
    username: str
    password: str
    email: str

class LoginBody(BaseModel):
    username: str
    password: str

@router.post("/register")
def register(body: RegisterBody):
    return {"ok": True, "user": body.username}

@router.post("/login")
def login(body: LoginBody):
    if len(body.password) < 6:
        raise HTTPException(400, "密码过短")
    return {"token": "demo-token"}
# modified locally
