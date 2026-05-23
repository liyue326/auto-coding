from unittest.mock import AsyncMock, patch
from services.user_service import delete_user
from models.user import User
from database import get_db

async def test_delete_user_success():
    mock_db = AsyncMock()
    mock_user = User(id="123", username="test", email="test@example.com", password_hash="hash")
    mock_db.query.return_value.filter.return_value.first.return_value = mock_user
    
    result = await delete_user(mock_db, "123")
    assert result == {"ok": True, "message": "Account deleted successfully"}
    assert mock_db.delete.called_with(mock_user)
    assert mock_db.commit.called

async def test_delete_user_not_found():
    mock_db = AsyncMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None
    
    with pytest.raises(HTTPException) as exc_info:
        await delete_user(mock_db, "123")
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "User not found"
