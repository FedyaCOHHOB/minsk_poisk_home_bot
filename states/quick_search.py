from aiogram.fsm.state import State, StatesGroup


class QuickSearchForm(StatesGroup):
    budget = State()
    districts = State()
    roommate_gender = State()
