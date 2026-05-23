from dataclasses import dataclass
from datetime import datetime

@dataclass
class User:
    id: str
    username: str
    email: str
    created_at: datetime
    updated_at: datetime
    password_hash: str
    is_active: bool = True

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())
        if not self.created_at:
            self.created_at = datetime.now()
        if not self.updated_at:
            self.updated_at = datetime.now()
