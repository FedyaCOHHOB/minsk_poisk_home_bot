from __future__ import annotations

from datetime import timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import async_sessionmaker

from config import config
from database import crud
from database.database import session_scope
from services.listings import update_all_listings
from utils.helpers import utcnow

router = Router(name="admin")
# Все хендлеры этого роутера доступны только администратору. Для всех
# остальных /update и /stats просто не сработают — бот их проигнорирует
# как неизвестную команду, ничего не выдавая посторонним.
router.message.filter(lambda message: message.from_user is not None and message.from_user.id == config.admin_id)


@router.message(Command("update"))
async def cmd_update(message: Message, session_factory: async_sessionmaker) -> None:
    status = await message.answer(
        "Обновляю базу объявлений по всем районам — это может занять около минуты…"
    )
    async with session_scope(session_factory) as session:
        count = await update_all_listings(session)

    await status.edit_text(f"Готово ✅ Обработано объявлений: {count}")


@router.message(Command("stats"))
async def cmd_stats(message: Message, session_factory: async_sessionmaker) -> None:
    async with session_scope(session_factory) as session:
        users = await crud.count_users(session)
        profiles = await crud.count_profiles(session)
        listings = await crud.count_listings(session)
        favorites = await crud.count_favorites(session)
        active_7d = await crud.count_active_users_since(
            session, since=utcnow() - timedelta(days=7)
        )

    text = (
        "📊 <b>Статистика бота</b>\n\n"
        f"👤 Пользователей всего: {users}\n"
        f"🏃 Активных за 7 дней: {active_7d}\n"
        f"📝 Анкет заполнено: {profiles}\n"
        f"🏠 Объявлений в базе: {listings}\n"
        f"❤️ Сохранений (избранное): {favorites}\n"
    )
    await message.answer(text)
