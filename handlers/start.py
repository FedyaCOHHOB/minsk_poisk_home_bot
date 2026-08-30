from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import async_sessionmaker

from database import crud
from database.database import session_scope
from keyboards.main import (
    BTN_HELP,
    BTN_PROFILE,
    main_menu_kb,
)
from utils.helpers import format_profile_summary

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, session_factory: async_sessionmaker) -> None:
    async with session_scope(session_factory) as session:
        await crud.get_or_create_user(
            session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )

    await message.answer(
        "Привет! Я помогу найти подселение, комнату или квартиру в Минске.\n\n"
        "Сначала заполни анкету — это займёт пару минут.",
        reply_markup=main_menu_kb(),
    )


@router.message(F.text == BTN_PROFILE)
async def show_profile(message: Message, session_factory: async_sessionmaker, state: FSMContext) -> None:
    async with session_scope(session_factory) as session:
        profile = await crud.get_profile_by_telegram_id(session, message.from_user.id)

        if profile is None:
            await message.answer(
                "У тебя пока нет анкеты. Давай заполним — отправь /profile"
            )
            return

        districts = [pd.district for pd in profile.districts]
        text = format_profile_summary(profile, districts)

    await message.answer(text + "\n\nЧтобы изменить анкету — отправь /profile", parse_mode="HTML")


@router.message(F.text == BTN_HELP)
async def help_handler(message: Message) -> None:
    await message.answer(
        "🏠 Найти жильё — поиск подходящих объявлений с Kufar по твоей анкете\n"
        "👤 Моя анкета — посмотреть/заполнить анкету\n"
        "❤️ Сохранённые — то, что ты сохранил во время поиска\n"
        "🔔 Уведомления — присылать новые подходящие варианты автоматически\n\n"
        "Команда /profile — заполнить или пересоздать анкету.\n"
        "Команда /quicksearch — разовый быстрый поиск (3 вопроса), "
        "не трогая сохранённую анкету.\n"
        "Команда /privacy — какие данные храню и как их удалить."
    )


@router.message(Command("privacy"))
async def privacy_handler(message: Message) -> None:
    await message.answer(
        "🔒 <b>Приватность</b>\n\n"
        "Что храню:\n"
        "• Из анкеты — пол, возраст, бюджет, районы, тип жилья, "
        "предпочтения по соседям, привычки и текст «о себе» (если указал)\n"
        "• Технически — твой Telegram ID и username\n"
        "• Что сохранил (❤️) и подписан ли на уведомления — чтобы "
        "показывать это тебе же\n\n"
        "Кому передаю: никому. Объявления беру с открытых страниц "
        "Kufar.by — твои личные данные туда не уходят, поиск идёт локально "
        "в моей базе.\n\n"
        "Как удалить:\n"
        "⚙️ Настройки → 🗑 Удалить анкету — удаляет только анкету, "
        "сохранённое остаётся\n"
        "⚙️ Настройки → ⚠️ Удалить все мои данные — удаляет вообще всё "
        "безвозвратно"
    )
