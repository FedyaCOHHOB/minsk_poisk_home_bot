from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import async_sessionmaker

from database import crud
from database.database import session_scope
from handlers.profile import start_profile
from keyboards.inline import confirm_delete_all_kb, confirm_delete_profile_kb, settings_kb
from keyboards.main import BTN_SETTINGS, main_menu_kb

router = Router(name="settings")


@router.message(F.text == BTN_SETTINGS)
async def show_settings(message: Message) -> None:
    await message.answer("⚙️ Настройки", reply_markup=settings_kb())


@router.callback_query(F.data == "settings:edit_profile")
async def edit_profile(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    await start_profile(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "settings:delete_profile")
async def ask_delete_profile(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "Точно удалить анкету? Сохранённые объявления (❤️) не пострадают — "
        "их можно посмотреть в «Сохранённых» и без анкеты.",
        reply_markup=confirm_delete_profile_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "settings:delete_profile:confirm")
async def delete_profile_confirmed(
    callback: CallbackQuery, session_factory: async_sessionmaker
) -> None:
    async with session_scope(session_factory) as session:
        deleted = await crud.delete_profile(session, callback.from_user.id)

    text = (
        "Анкета удалена. Заполнить новую можно через /profile."
        if deleted
        else "У тебя и так не было анкеты."
    )
    await callback.message.edit_text(text)
    await callback.message.answer("Возвращаемся в меню 🙂", reply_markup=main_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "settings:delete_profile:cancel")
async def delete_profile_cancelled(callback: CallbackQuery) -> None:
    await callback.message.edit_text("⚙️ Настройки", reply_markup=settings_kb())
    await callback.answer("Хорошо, ничего не трогаю")


@router.callback_query(F.data == "settings:delete_all")
async def ask_delete_all(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "⚠️ Это удалит АБСОЛЮТНО ВСЁ: анкету, сохранённые объявления и "
        "подписку на уведомления. Отменить нельзя. Точно?",
        reply_markup=confirm_delete_all_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "settings:delete_all:confirm")
async def delete_all_confirmed(callback: CallbackQuery, session_factory: async_sessionmaker) -> None:
    async with session_scope(session_factory) as session:
        await crud.delete_user_completely(session, callback.from_user.id)

    await callback.message.edit_text("Все твои данные удалены.")
    await callback.message.answer(
        "Если захочешь начать заново — просто напиши /start.", reply_markup=main_menu_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "settings:delete_all:cancel")
async def delete_all_cancelled(callback: CallbackQuery) -> None:
    await callback.message.edit_text("⚙️ Настройки", reply_markup=settings_kb())
    await callback.answer("Хорошо, ничего не трогаю")
