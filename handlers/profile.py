from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import async_sessionmaker

from database import crud
from database.database import session_scope
from database.models import District, Gender, HousingType, RoommateGender
from keyboards.inline import (
    districts_kb,
    gender_kb,
    housing_type_kb,
    roommate_gender_kb,
    skip_kb,
    yes_no_kb,
)
from keyboards.main import main_menu_kb
from states.profile import ProfileForm
from utils.helpers import format_profile_summary, parse_positive_int

router = Router(name="profile")


# --------------------------------------------------------------------------
# Старт анкеты
# --------------------------------------------------------------------------

@router.message(Command("profile"))
async def start_profile(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(ProfileForm.gender)
    await message.answer("Начнём 🙂\n\nТы — девушка или мужчина?", reply_markup=gender_kb())


# --------------------------------------------------------------------------
# Пол
# --------------------------------------------------------------------------

@router.callback_query(ProfileForm.gender, F.data.startswith("gender:"))
async def process_gender(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    await state.update_data(gender=value)
    await state.set_state(ProfileForm.age)

    await callback.message.edit_text(
        f"Пол: {'Девушка' if value == 'female' else 'Мужчина'} ✅"
    )
    await callback.message.answer("Сколько тебе лет?")
    await callback.answer()


# --------------------------------------------------------------------------
# Возраст
# --------------------------------------------------------------------------

@router.message(ProfileForm.age)
async def process_age(message: Message, state: FSMContext) -> None:
    age = parse_positive_int(message.text or "", min_value=14, max_value=100)
    if age is None:
        await message.answer("Введи возраст числом, например: 22")
        return

    await state.update_data(age=age)
    await state.set_state(ProfileForm.budget)
    await message.answer("Какой у тебя максимальный бюджет в долларах?")


# --------------------------------------------------------------------------
# Бюджет
# --------------------------------------------------------------------------

@router.message(ProfileForm.budget)
async def process_budget(message: Message, state: FSMContext) -> None:
    budget = parse_positive_int(message.text or "", min_value=10, max_value=5000)
    if budget is None:
        await message.answer("Введи бюджет числом, например: 150")
        return

    await state.update_data(budget=budget, selected_districts=[])
    await state.set_state(ProfileForm.districts)
    await message.answer(
        "Выбери районы (можно несколько), затем нажми «Готово»:",
        reply_markup=districts_kb(set()),
    )


# --------------------------------------------------------------------------
# Районы (мультивыбор)
# --------------------------------------------------------------------------

@router.callback_query(ProfileForm.districts, F.data.startswith("district:toggle:"))
async def toggle_district(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 2)[2]
    data = await state.get_data()
    selected = set(data.get("selected_districts", []))

    if value == "any":
        selected = set() if "any" in selected else {"any"}
    else:
        selected.discard("any")
        if value in selected:
            selected.discard(value)
        else:
            selected.add(value)

    await state.update_data(selected_districts=list(selected))

    selected_enum = {District(v) for v in selected}
    await callback.message.edit_reply_markup(reply_markup=districts_kb(selected_enum))
    await callback.answer()


@router.callback_query(ProfileForm.districts, F.data == "district:done")
async def finish_districts(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    selected = data.get("selected_districts", [])

    if not selected:
        await callback.answer("Выбери хотя бы один район (или «Любой»)", show_alert=True)
        return

    await state.set_state(ProfileForm.housing_type)
    await callback.message.edit_text("Районы выбраны ✅")
    await callback.message.answer("Что ты ищешь?", reply_markup=housing_type_kb())
    await callback.answer()


# --------------------------------------------------------------------------
# Тип жилья
# --------------------------------------------------------------------------

@router.callback_query(ProfileForm.housing_type, F.data.startswith("housing:"))
async def process_housing_type(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    await state.update_data(housing_type=value)
    await callback.message.edit_text("Тип жилья выбран ✅")

    if value == "apartment":
        # При квартире вопрос "к кому подселиться" не имеет смысла — там
        # не подселяются к соседям, снимают жильё целиком.
        await state.update_data(roommate_gender=RoommateGender.ANY.value)
        await state.set_state(ProfileForm.pets)
        await callback.message.answer("Есть животные?", reply_markup=yes_no_kb("pets"))
    else:
        await state.set_state(ProfileForm.roommate_gender)
        await callback.message.answer(
            "К кому готов(а) подселиться?", reply_markup=roommate_gender_kb()
        )
    await callback.answer()


# --------------------------------------------------------------------------
# Пол соседей
# --------------------------------------------------------------------------

@router.callback_query(ProfileForm.roommate_gender, F.data.startswith("roommate:"))
async def process_roommate_gender(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    await state.update_data(roommate_gender=value)
    await state.set_state(ProfileForm.pets)

    await callback.message.edit_text("Записал ✅")
    await callback.message.answer("Есть животные?", reply_markup=yes_no_kb("pets"))
    await callback.answer()


# --------------------------------------------------------------------------
# Животные / курение / вредные привычки — общий обработчик yesno:*
# --------------------------------------------------------------------------

@router.callback_query(ProfileForm.pets, F.data.startswith("yesno:pets:"))
async def process_pets(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.endswith(":yes")
    await state.update_data(pets=value)
    await state.set_state(ProfileForm.smoking)

    await callback.message.edit_text(f"Животные: {'да' if value else 'нет'} ✅")
    await callback.message.answer("Куришь?", reply_markup=yes_no_kb("smoking"))
    await callback.answer()


@router.callback_query(ProfileForm.smoking, F.data.startswith("yesno:smoking:"))
async def process_smoking(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.endswith(":yes")
    await state.update_data(smoking=value)
    await state.set_state(ProfileForm.bad_habits)

    await callback.message.edit_text(f"Курение: {'да' if value else 'нет'} ✅")
    await callback.message.answer(
        "Есть другие вредные привычки?", reply_markup=yes_no_kb("bad_habits")
    )
    await callback.answer()


@router.callback_query(ProfileForm.bad_habits, F.data.startswith("yesno:bad_habits:"))
async def process_bad_habits(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.endswith(":yes")
    await state.update_data(bad_habits=value)
    await state.set_state(ProfileForm.occupation)

    await callback.message.edit_text(f"Вредные привычки: {'да' if value else 'нет'} ✅")
    await callback.message.answer(
        "Работаешь или учишься? Напиши коротко (или пропусти).",
        reply_markup=skip_kb("occupation"),
    )
    await callback.answer()


# --------------------------------------------------------------------------
# Работа/учёба (текст или пропуск)
# --------------------------------------------------------------------------

@router.message(ProfileForm.occupation)
async def process_occupation_text(message: Message, state: FSMContext) -> None:
    await state.update_data(occupation=message.text)
    await _ask_description(message, state)


@router.callback_query(ProfileForm.occupation, F.data == "skip:occupation")
async def process_occupation_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(occupation=None)
    await callback.message.edit_text("Ок, пропускаем")
    await _ask_description(callback.message, state)
    await callback.answer()


async def _ask_description(message: Message, state: FSMContext) -> None:
    await state.set_state(ProfileForm.description)
    await message.answer(
        "Расскажи немного о себе (необязательно):",
        reply_markup=skip_kb("description"),
    )


# --------------------------------------------------------------------------
# О себе (текст или пропуск) — финальный шаг, сохраняем анкету
# --------------------------------------------------------------------------

@router.message(ProfileForm.description)
async def process_description_text(
    message: Message, state: FSMContext, session_factory: async_sessionmaker
) -> None:
    await _finish_profile(message, state, session_factory, description=message.text)


@router.callback_query(ProfileForm.description, F.data == "skip:description")
async def process_description_skip(
    callback: CallbackQuery, state: FSMContext, session_factory: async_sessionmaker
) -> None:
    await callback.message.edit_text("Ок, пропускаем")
    await _finish_profile(callback.message, state, session_factory, description=None)
    await callback.answer()


async def _finish_profile(
    message: Message,
    state: FSMContext,
    session_factory: async_sessionmaker,
    *,
    description: str | None,
) -> None:
    data = await state.get_data()

    selected_districts = [District(v) for v in data["selected_districts"]]

    async with session_scope(session_factory) as session:
        user = await crud.get_or_create_user(
            session,
            telegram_id=message.chat.id,
            username=None,
            first_name=None,
        )
        profile = await crud.upsert_profile(
            session,
            user,
            gender=Gender(data["gender"]),
            age=data["age"],
            max_budget=data["budget"],
            housing_type=HousingType(data["housing_type"]),
            preferred_roommate_gender=RoommateGender(data["roommate_gender"]),
            pets=data["pets"],
            smoking=data["smoking"],
            bad_habits=data["bad_habits"],
            occupation=data.get("occupation"),
            description=description,
            districts=selected_districts,
        )
        summary = format_profile_summary(profile, selected_districts)

    await state.clear()
    await message.answer(
        "Анкета готова ✅\n\n" + summary,
        parse_mode="HTML",
        reply_markup=main_menu_kb(),
    )
