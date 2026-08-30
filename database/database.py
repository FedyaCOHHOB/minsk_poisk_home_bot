"""Настройка асинхронного движка SQLAlchemy и фабрики сессий."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from database.models import Base


def make_engine(db_path: str):
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)

    # Раньше в базу писали только по одной операции за раз — реакция на
    # действия пользователя. С появлением фонового шедулера уведомлений
    # (services/notifications.py, раз в 20 минут) конкурентный доступ стал
    # реальным сценарием: фоновая проверка может пересечься по времени с
    # обычным поиском пользователя или ручным /update у админа.
    # Дефолтный journal_mode SQLite (DELETE) блокирует читателей на время
    # записи БЕЗ ожидания — сразу падает с "database is locked". WAL
    # позволяет читать во время записи, а busy_timeout заставляет SQLite
    # немного подождать перед тем как сдаться, вместо мгновенного отказа.
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        # SQLite по умолчанию НЕ проверяет внешние ключи, даже если в схеме
        # написано ondelete="CASCADE" (это известная особенность SQLite, не
        # баг SQLAlchemy) — без этой строки все cascade-правила в моделях
        # были объявлены, но никогда не применялись на уровне БД. Схема в
        # уже существующих bot.db уже содержит "ON DELETE CASCADE" (это
        # часть DDL, а не рантайм-настройка) — пересоздавать базу не нужно,
        # просто начинаем реально проверять то, что там уже написано.
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


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
