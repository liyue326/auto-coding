from pydantic import BaseModel

class HealthCheck(BaseModel):
    status: str

    class Config:
        orm_mode = True
