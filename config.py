"""Загрузка конфигурации из переменных окружения (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_id: int
    db_path: str


def load_config() -> Config:
    bot_token = os.getenv("BOT_TOKEN")
    admin_id_raw = os.getenv("ADMIN_ID")
    db_path = os.getenv("DB_PATH", "bot.db")

    if not bot_token:
        raise RuntimeError(
            "BOT_TOKEN не найден. Скопируй .env.example в .env и впиши токен бота."
        )
    if not admin_id_raw or not admin_id_raw.isdigit():
        raise RuntimeError(
            "ADMIN_ID не найден или не является числом. Проверь .env."
        )

    return Config(bot_token=bot_token, admin_id=int(admin_id_raw), db_path=db_path)


config = load_config()
