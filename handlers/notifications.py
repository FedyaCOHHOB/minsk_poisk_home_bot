from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import async_sessionmaker

from database import crud
from database.database import session_scope
from keyboards.inline import notifications_kb
from keyboards.main import BTN_NOTIFICATIONS

router = Router(name="notifications")


@router.message(F.text == BTN_NOTIFICATIONS)
async def show_notifications(message: Message, session_factory: async_sessionmaker) -> None:
    async with session_scope(session_factory) as session:
        profile = await crud.get_profile_by_telegram_id(session, message.from_user.id)
        if profile is None:
            await message.answer(
                "Уведомления работают по сохранённой анкете — сначала заполни "
                "её через /profile, а потом возвращайся сюда."
            )
            return

        user = await crud.get_or_create_user(
            session, telegram_id=message.from_user.id, username=None, first_name=None
        )
        sub = await crud.get_subscription(session, user.id)

    is_active = sub is not None and sub.is_active
    text = (
        "🔔 Уведомления включены — как только появится новый вариант с "
        "хорошим совпадением по твоей анкете, пришлю его сюда."
        if is_active
        else "🔕 Уведомления выключены.\n\n"
        "Включи — и не придётся заходить и искать вручную: как только на "
        "Kufar появится новое подходящее объявление, я пришлю его сам."
    )
    await message.answer(text, reply_markup=notifications_kb(is_active))


@router.callback_query(F.data == "notif:enable")
async def enable_notifications(callback: CallbackQuery, session_factory: async_sessionmaker) -> None:
    async with session_scope(session_factory) as session:
        profile = await crud.get_profile_by_telegram_id(session, callback.from_user.id)
        if profile is None:
            await callback.answer("Сначала заполни анкету через /profile", show_alert=True)
            return

        user = await crud.get_or_create_user(
            session, telegram_id=callback.from_user.id, username=None, first_name=None
        )
        await crud.set_subscription_active(session, user.id, True)

    await callback.message.edit_text(
        "🔔 Уведомления включены — пришлю новые подходящие варианты, как "
        "только появятся.",
        reply_markup=notifications_kb(True),
    )
    await callback.answer()


@router.callback_query(F.data == "notif:disable")
async def disable_notifications(callback: CallbackQuery, session_factory: async_sessionmaker) -> None:
    async with session_scope(session_factory) as session:
        user = await crud.get_or_create_user(
            session, telegram_id=callback.from_user.id, username=None, first_name=None
        )
        await crud.set_subscription_active(session, user.id, False)

    await callback.message.edit_text("🔕 Уведомления выключены", reply_markup=notifications_kb(False))
    await callback.answer()
