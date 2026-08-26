"""Настройка асинхронного движка SQLAlchemy и фабрики сессий."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from database.models import Base


def make_engine(db_path: str):
    return create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)


def make_session_factory(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine) -> None:
    """Создаёт таблицы, если их ещё нет. Для MVP без Alembic-миграций —
    при изменении схемы модели нужно будет пересоздать файл БД."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def session_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Контекстный менеджер: коммит при успехе, rollback при исключении."""
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
