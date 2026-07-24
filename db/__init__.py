import os
from pathlib import Path
from sqlmodel import SQLModel, create_engine
from db.models.message import Message

DATA_DIR = Path("/app/data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_PATH = DATA_DIR / "database.db"
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

def init():
    SQLModel.metadata.create_all(engine)