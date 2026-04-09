from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine

from backend.config import get_settings


def get_engine():
    settings = get_settings()
    # Ensure the directory exists before creating the DB
    import os

    db_path = settings.database_url.removeprefix("sqlite:///")
    os.makedirs(os.path.dirname(db_path), exist_ok=True) if os.path.dirname(db_path) else None
    return create_engine(settings.database_url, connect_args={"check_same_thread": False})


engine = get_engine()


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
