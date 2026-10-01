from collections.abc import Generator

from sqlalchemy.orm import Session

from app.core.db import SessionLocal


def get_db() -> Generator[Session, None, None]:
    """FastAPI Depends 用：每個request一個獨立DB session，測試時可用
    app.dependency_overrides[get_db] 替換成測試用DB。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
