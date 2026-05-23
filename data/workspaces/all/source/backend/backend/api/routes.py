from fastapi import APIRouter, Depends, HTTPException
from services.user_service import delete_user
from database import get_db
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api/v2")

@router.post("/users/{user_id}/delete")
async def delete_user_route(user_id: str, db: Session = Depends(get_db)):
    return await delete_user(db, user_id)
