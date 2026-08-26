from aiogram.fsm.state import State, StatesGroup


class SearchSession(StatesGroup):
    browsing = State()
