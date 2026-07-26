from sqlmodel import SQLModel, Field
from datetime import datetime

class Message(SQLModel, table=True):
    __tablename__ = "message_cache"
    
    id: int | None = Field(default=None, primary_key=True)
    unique_id: str = Field(index=True)
    chat_id: int
    message_id: int
    user_id: int
    from_user_id: int
    from_username: str | None = None
    from_full_name: str | None = None
    content: str
    caption: str | None = None
    type: str
    latitude: float | None = None
    longitude: float | None = None
    contact_user_id: int | None = None
    contact_first_name: str | None = None
    contact_phone: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)