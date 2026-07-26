from sqlmodel import SQLModel, Field
from datetime import datetime

class Usage(SQLModel, table=True):
    __tablename__ = "usage"
    
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    request_time: datetime = Field(default_factory=datetime.now)
    type: str = Field(default="groq")