import pytest
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

def test_calculate_fibonacci():
    response = client.post("/api/fib/calculate", json={"n": 10})
    assert response.status_code == 200
    assert response.json() == {"ok": True, "data": {"n": 10, "result": 55}}

def test_negative_n():
    response = client.post("/api/fib/calculate", json={"n": -5})
    assert response.status_code == 400
    assert response.json() == {"ok": False, "message": "n must be non-negative", "code": "ERR_INVALID_INPUT"}
