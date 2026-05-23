"""认证服务层"""
from typing import Optional

class AuthService:
    def register(self, username: str, password: str, email: str) -> dict:
        return {"id": 1, "username": username, "email": email}

    def login(self, username: str, password: str) -> Optional[dict]:
        if not username or not password:
            return None
        return {"token": "demo-token", "username": username}
