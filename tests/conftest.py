import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Тестам не нужен реальный .env — подставляем безопасные заглушки до
# импорта config.py (он читает переменные окружения при импорте).
os.environ.setdefault("BOT_TOKEN", "123456789:AATestTokenForPytestOnly1234567")
os.environ.setdefault("ADMIN_ID", "987654321")
os.environ.setdefault("DB_PATH", "unused-see-fixture.db")

import pytest

from database.database import init_db, make_engine, make_session_factory, session_scope


@pytest.fixture
async def engine(tmp_path):
    """Свежая SQLite-база на файловой системе для каждого теста —
    чтобы тесты не видели данные друг друга и не мешали параллельному
    запуску."""
    db_path = tmp_path / "test.db"
    eng = make_engine(str(db_path))
    await init_db(eng)
    yield eng
    await eng.dispose()


@pytest.fixture
def session_factory(engine):
    return make_session_factory(engine)


@pytest.fixture
def session_scope_fixture(session_factory):
    """Даёт сам session_scope с уже подставленной фабрикой — тесты просто
    делают `async with session_scope_fixture() as session:`."""
    def _scope():
        return session_scope(session_factory)
    return _scope
