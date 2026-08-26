from aiogram.fsm.state import State, StatesGroup


class ProfileForm(StatesGroup):
    gender = State()
    age = State()
    budget = State()
    districts = State()
    housing_type = State()
    roommate_gender = State()
    pets = State()
    smoking = State()
    bad_habits = State()
    occupation = State()
    description = State()
