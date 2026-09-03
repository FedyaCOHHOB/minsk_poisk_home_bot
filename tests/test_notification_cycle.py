from datetime import timedelta
from unittest.mock import AsyncMock

from database import crud
from database.models import District, Gender, HousingType, RoommateGender
from services.notifications import NOTIFY_COOLDOWN_MINUTES, _check_one_subscription
from sources.schemas import RawListing
from utils.helpers import utcnow


def _raw_listing(external_id, **overrides):
    defaults = dict(
        source="kufar", title="Улица", description="хорошая комната",
        price=200, currency="BYN", is_negotiable=False,
        url=f"https://x/{external_id}", district="central",
    )
    defaults.update(overrides)
    return RawListing(external_id=external_id, **defaults)


class _FakeMessage:
    def __init__(self, message_id):
        self.message_id = message_id


async def _make_mock_bot():
    bot = AsyncMock()
    bot.send_message = AsyncMock(side_effect=lambda *a, **kw: _FakeMessage(9001))
    bot.edit_message_text = AsyncMock()
    return bot


async def _setup_subscriber(session_scope_fixture, telegram_id=42):
    async with session_scope_fixture() as session:
        user = await crud.get_or_create_user(session, telegram_id=telegram_id, username=None, first_name=None)
        await crud.upsert_profile(
            session, user,
            gender=Gender.FEMALE, age=22, max_budget=300,
            housing_type=HousingType.ANY, preferred_roommate_gender=RoommateGender.ANY,
            pets=False, smoking=False, bad_habits=False, occupation=None, description=None,
            districts=[District.CENTRALNY],
        )
        await crud.set_subscription_active(session, user.id, True)

    async with session_scope_fixture() as session:
        sub = await crud.get_subscription(session, user.id)
        await crud.update_subscription_checked(session, sub.id, utcnow() - timedelta(hours=2))

    return user


class TestNotificationAccumulation:
    """Реальный найденный баг: не ответившему на первое уведомление
    пользователю второй цикл молча ЗАМЕНЯЛ находку вместо того, чтобы
    добавить к ней — первая находка бесследно исчезала."""

    async def test_unanswered_notification_accumulates_not_replaces(
        self, session_factory, session_scope_fixture
    ):
        user = await _setup_subscriber(session_scope_fixture)
        bot = await _make_mock_bot()

        async with session_scope_fixture() as session:
            await crud.upsert_listing(session, _raw_listing("ACC1"))

        async with session_scope_fixture() as session:
            sub = await crud.get_subscription(session, user.id)
        await _check_one_subscription(
            bot, session_factory, sub.id, user.id, sub.last_checked_at, sub.min_score, sub.last_notified_at
        )
        assert bot.send_message.call_count == 1
        assert "1" in bot.send_message.call_args.args[1]

        # Пользователь ЕЩЁ НЕ ответил. Появляется второе объявление.
        async with session_scope_fixture() as session:
            sub = await crud.get_subscription(session, user.id)
            await crud.upsert_listing(session, _raw_listing("ACC2"))
        await _check_one_subscription(
            bot, session_factory, sub.id, user.id, sub.last_checked_at, sub.min_score, sub.last_notified_at
        )

        assert bot.send_message.call_count == 1, "второй цикл не должен слать новое сообщение"
        assert bot.edit_message_text.call_count == 1, "второй цикл должен редактировать существующее"
        edited_kwargs = bot.edit_message_text.call_args.kwargs
        assert edited_kwargs["message_id"] == 9001, "должно редактироваться то же самое сообщение"
        assert "2" in edited_kwargs["text"]

        async with session_scope_fixture() as session:
            pending = await crud.get_pending_notification(session, user.id)
            listing_ids, _ = pending
            assert len(listing_ids) == 2, "находка первого цикла не должна была потеряться"

    async def test_no_new_listings_does_not_touch_message(
        self, session_factory, session_scope_fixture
    ):
        user = await _setup_subscriber(session_scope_fixture)
        bot = await _make_mock_bot()

        async with session_scope_fixture() as session:
            sub = await crud.get_subscription(session, user.id)

        # ничего нового не появилось
        await _check_one_subscription(
            bot, session_factory, sub.id, user.id, sub.last_checked_at, sub.min_score, sub.last_notified_at
        )

        assert bot.send_message.call_count == 0
        assert bot.edit_message_text.call_count == 0


class TestNotifyCooldown:
    """Даже если пользователь отвечает на каждое уведомление мгновенно
    (значит, редактировать действительно нечего — предыдущее уже закрыто),
    частота РЕАЛЬНЫХ пингов не должна превышать раз в NOTIFY_COOLDOWN_MINUTES,
    иначе при высокой ротации объявлений на Kufar это ощущается как спам,
    даже когда каждое сообщение формально не дублирует предыдущее."""

    async def test_prompt_responses_still_get_throttled(
        self, session_factory, session_scope_fixture
    ):
        user = await _setup_subscriber(session_scope_fixture)
        bot = await _make_mock_bot()

        # Цикл 1: находит первое объявление, пингует.
        async with session_scope_fixture() as session:
            await crud.upsert_listing(session, _raw_listing("R1"))
        async with session_scope_fixture() as session:
            sub = await crud.get_subscription(session, user.id)
        await _check_one_subscription(
            bot, session_factory, sub.id, user.id, sub.last_checked_at, sub.min_score, sub.last_notified_at
        )
        assert bot.send_message.call_count == 1

        # Пользователь мгновенно отвечает — pending закрыт.
        async with session_scope_fixture() as session:
            await crud.clear_pending_notification(session, user.id)

        # Цикл 2, СРАЗУ следом (кулдаун ещё не прошёл): находит второе.
        async with session_scope_fixture() as session:
            sub = await crud.get_subscription(session, user.id)
            await crud.upsert_listing(session, _raw_listing("R2"))
        await _check_one_subscription(
            bot, session_factory, sub.id, user.id, sub.last_checked_at, sub.min_score, sub.last_notified_at
        )

        assert bot.send_message.call_count == 1, "кулдаун должен был предотвратить пинг так скоро"
        assert bot.edit_message_text.call_count == 0, "редактировать нечего — предыдущее уже закрыто пользователем"

        # Находка не потерялась — тихо копится.
        async with session_scope_fixture() as session:
            pending = await crud.get_pending_notification(session, user.id)
            assert pending is not None
            listing_ids, _ = pending
            assert len(listing_ids) == 1

    async def test_accumulated_finding_sent_once_cooldown_elapses(
        self, session_factory, session_scope_fixture
    ):
        from sqlalchemy import update as sa_update
        from database.models import NotificationSubscription
        from database.database import session_scope as db_session_scope

        user = await _setup_subscriber(session_scope_fixture)
        bot = await _make_mock_bot()

        async with session_scope_fixture() as session:
            await crud.upsert_listing(session, _raw_listing("R1"))
        async with session_scope_fixture() as session:
            sub = await crud.get_subscription(session, user.id)
        await _check_one_subscription(
            bot, session_factory, sub.id, user.id, sub.last_checked_at, sub.min_score, sub.last_notified_at
        )
        async with session_scope_fixture() as session:
            await crud.clear_pending_notification(session, user.id)

        async with session_scope_fixture() as session:
            sub = await crud.get_subscription(session, user.id)
            await crud.upsert_listing(session, _raw_listing("R2"))
        await _check_one_subscription(
            bot, session_factory, sub.id, user.id, sub.last_checked_at, sub.min_score, sub.last_notified_at
        )
        assert bot.send_message.call_count == 1  # накопилось молча, ещё не отправлено

        # "Проходит час" — искусственно состариваем last_notified_at.
        async with session_scope_fixture() as session:
            sub = await crud.get_subscription(session, user.id)
            await session.execute(
                sa_update(NotificationSubscription)
                .where(NotificationSubscription.id == sub.id)
                .values(last_notified_at=utcnow() - timedelta(minutes=NOTIFY_COOLDOWN_MINUTES + 1))
            )

        async with session_scope_fixture() as session:
            sub = await crud.get_subscription(session, user.id)
        await _check_one_subscription(
            bot, session_factory, sub.id, user.id, sub.last_checked_at, sub.min_score, sub.last_notified_at
        )

        assert bot.send_message.call_count == 2, "после истечения кулдауна накопленное должно уйти"
