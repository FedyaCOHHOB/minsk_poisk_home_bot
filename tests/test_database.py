from sqlalchemy import text

from database.database import init_db, make_engine
from database.models import Base


class TestPendingNotificationMigration:
    """Проверяет, что существующие базы (созданные до появления
    summary_message_id) получают колонку через ALTER TABLE, а не падают
    с 'no such column' и не требуют от пользователя вручную удалять bot.db."""

    async def test_column_added_to_preexisting_table(self, tmp_path):
        db_path = tmp_path / "old_schema.db"
        engine = make_engine(str(db_path))

        # Создаём таблицу БЕЗ новой колонки — эмулируем состояние базы,
        # созданной до этой правки.
        async with engine.begin() as conn:
            await conn.execute(text(
                "CREATE TABLE pending_notifications ("
                "id INTEGER PRIMARY KEY, user_id INTEGER, "
                "listing_ids_json TEXT, explanations_json TEXT, "
                "created_at DATETIME"
                ")"
            ))

        async with engine.connect() as conn:
            result = await conn.exec_driver_sql("PRAGMA table_info(pending_notifications)")
            columns_before = {row[1] for row in result.fetchall()}
        assert "summary_message_id" not in columns_before

        # init_db должен доставить недостающую колонку, не упасть
        await init_db(engine)

        async with engine.connect() as conn:
            result = await conn.exec_driver_sql("PRAGMA table_info(pending_notifications)")
            columns_after = {row[1] for row in result.fetchall()}
        assert "summary_message_id" in columns_after

        await engine.dispose()

    async def test_fresh_db_already_has_column(self, tmp_path):
        """На новой базе create_all уже создаёт колонку сразу — миграция
        просто ничего не делает, не должна падать при повторном вызове."""
        db_path = tmp_path / "fresh.db"
        engine = make_engine(str(db_path))
        await init_db(engine)
        await init_db(engine)  # повторный вызов не должен падать

        async with engine.connect() as conn:
            result = await conn.exec_driver_sql("PRAGMA table_info(pending_notifications)")
            columns = {row[1] for row in result.fetchall()}
        assert "summary_message_id" in columns

        await engine.dispose()
