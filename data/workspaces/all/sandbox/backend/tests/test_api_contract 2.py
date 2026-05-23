def test_routes_define_login():
    content = open("api/routes.py", encoding="utf-8").read()
    assert "/login" in content
    assert "HTTPException" in content
