import pytest

def test_login_requires_password():
    from services.auth_service import AuthService
    svc = AuthService()
    assert svc.login("alice", "") is None

def test_register_returns_user():
    from services.auth_service import AuthService
    svc = AuthService()
    r = svc.register("alice", "secret123", "a@b.com")
    assert r["username"] == "alice"
