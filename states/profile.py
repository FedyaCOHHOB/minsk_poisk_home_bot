from aiogram.fsm.state import State, StatesGroup


class ProfileForm(StatesGroup):
    gender = State()
    age = State()
    budget = State()
    districts = State()
    housing_type = State()
    # Уточняющий шаг ПОСЛЕ housing_type, только если там выбрали "комната" —
    # своя комната или подселение/койко-место (Kufar их не различает как
    # категории, см. sources/kufar.py, но для пользователя разница важная).
    room_type = State()
    roommate_gender = State()
    pets = State()
    smoking = State()
    bad_habits = State()
    occupation = State()
    description = State()
