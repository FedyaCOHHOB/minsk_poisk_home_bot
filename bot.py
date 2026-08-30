import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import config
from database.database import init_db, make_engine, make_session_factory
from handlers import admin, notifications, profile, search, settings, start
from services.notifications import CHECK_INTERVAL_MINUTES, run_notification_cycle

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    engine = make_engine(config.db_path)
    await init_db(engine)
    session_factory = make_session_factory(engine)

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(start.router)
    dp.include_router(profile.router)
    dp.include_router(search.router)
    dp.include_router(settings.router)
    dp.include_router(notifications.router)
    dp.include_router(admin.router)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_notification_cycle,
        "interval",
        minutes=CHECK_INTERVAL_MINUTES,
        args=[bot, session_factory],
        id="notification_cycle",
    )
    scheduler.start()

    logger.info("Бот запускается... (проверка уведомлений каждые %s мин)", CHECK_INTERVAL_MINUTES)
    try:
        await dp.start_polling(bot, session_factory=session_factory)
    finally:
        scheduler.shutdown(wait=False)
        await engine.dispose()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
