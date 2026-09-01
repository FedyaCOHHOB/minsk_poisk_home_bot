from datetime import timedelta

import pytest
from sqlalchemy import func, select

from database import crud
from database.models import (
    District,
    Favorite,
    Gender,
    HousingType,
    Listing,
    NotificationSubscription,
    Profile,
    ProfileDistrict,
    RoommateGender,
    User,
)
from sources.schemas import RawListing
from utils.helpers import utcnow


async def _make_profile(session, telegram_id=1, districts=None):
    user = await crud.get_or_create_user(session, telegram_id=telegram_id, username="t", first_name="T")
    await crud.upsert_profile(
        session, user,
        gender=Gender.FEMALE, age=22, max_budget=150,
        housing_type=HousingType.ANY, preferred_roommate_gender=RoommateGender.FEMALE,
        pets=False, smoking=False, bad_habits=False, occupation=None, description=None,
        districts=districts or [District.CENTRALNY],
    )
    return user


def _raw_listing(external_id="L1", **overrides):
    defaults = dict(
        source="kufar", title="Тест", description="Описание",
        price=300, currency="BYN", is_negotiable=False,
        url=f"https://x/{external_id}", district="central",
    )
    defaults.update(overrides)
    return RawListing(external_id=external_id, **defaults)


class TestUpsertProfile:
    async def test_creates_profile_with_districts(self, session_scope_fixture):
        async with session_scope_fixture() as session:
            user = await _make_profile(session, districts=[District.FRUNZENSKY, District.CENTRALNY])

        async with session_scope_fixture() as session:
            profile = await crud.get_profile_by_telegram_id(session, 1)
            assert profile is not None
            assert {pd.district for pd in profile.districts} == {District.FRUNZENSKY, District.CENTRALNY}

    async def test_repeated_upsert_replaces_not_duplicates(self, session_scope_fixture):
        async with session_scope_fixture() as session:
            user = await _make_profile(session, districts=[District.CENTRALNY])
            await crud.upsert_profile(
                session, user,
                gender=Gender.MALE, age=30, max_budget=300,
                housing_type=HousingType.ROOM, preferred_roommate_gender=RoommateGender.ANY,
                pets=True, smoking=True, bad_habits=True, occupation="Работаю", description=None,
                districts=[District.MOSKOVSKY],
            )

        async with session_scope_fixture() as session:
            profile = await crud.get_profile_by_telegram_id(session, 1)
            assert profile.age == 30
            assert {pd.district for pd in profile.districts} == {District.MOSKOVSKY}

            count = await session.execute(select(func.count()).select_from(Profile))
            assert count.scalar_one() == 1, "должен остаться один Profile, не два"


class TestUpsertListing:
    async def test_dedup_by_external_id_and_source(self, session_scope_fixture):
        async with session_scope_fixture() as session:
            await crud.upsert_listing(session, _raw_listing("DUP1", price=300))
            await crud.upsert_listing(session, _raw_listing("DUP1", price=350))  # тот же id — обновление

        async with session_scope_fixture() as session:
            count = await session.execute(select(func.count()).select_from(Listing))
            assert count.scalar_one() == 1
            result = await session.execute(select(Listing).where(Listing.external_id == "DUP1"))
            listing = result.scalar_one()
            assert listing.price == 350, "должна была обновиться цена, не создаться новая запись"

    async def test_parsed_at_not_touched_on_update(self, session_scope_fixture):
        """Критично для уведомлений: parsed_at должен оставаться моментом
        ПЕРВОГО появления, не обновляться при повторных upsert."""
        async with session_scope_fixture() as session:
            listing = await crud.upsert_listing(session, _raw_listing("STABLE1"))
            first_parsed_at = listing.parsed_at

        async with session_scope_fixture() as session:
            listing = await crud.upsert_listing(session, _raw_listing("STABLE1", price=999))

        async with session_scope_fixture() as session:
            result = await session.execute(select(Listing).where(Listing.external_id == "STABLE1"))
            listing = result.scalar_one()
            assert listing.parsed_at == first_parsed_at


class TestDeleteProfile:
    async def test_deletes_profile_and_districts_keeps_favorites(self, session_scope_fixture):
        async with session_scope_fixture() as session:
            user = await _make_profile(session, districts=[District.CENTRALNY, District.FRUNZENSKY])
            listing = await crud.upsert_listing(session, _raw_listing("KEEP1"))
            await crud.toggle_favorite(session, user.id, listing.id)

        async with session_scope_fixture() as session:
            deleted = await crud.delete_profile(session, 1)
            assert deleted is True

        async with session_scope_fixture() as session:
            profile = await crud.get_profile_by_telegram_id(session, 1)
            assert profile is None

            count = await session.execute(select(func.count()).select_from(ProfileDistrict))
            assert count.scalar_one() == 0

            favs = await crud.get_favorite_listings(session, user.id)
            assert len(favs) == 1, "избранное не должно пострадать от удаления анкеты"

    async def test_deleting_nonexistent_profile_returns_false(self, session_scope_fixture):
        async with session_scope_fixture() as session:
            deleted = await crud.delete_profile(session, telegram_id=999999)
            assert deleted is False


class TestDeleteUserCompletely:
    """Проверка того, что ON DELETE CASCADE реально работает — раньше не
    работал вообще, потому что PRAGMA foreign_keys не была включена."""

    async def test_cascades_through_all_related_tables(self, session_scope_fixture):
        async with session_scope_fixture() as session:
            user = await _make_profile(session, telegram_id=42, districts=[District.CENTRALNY, District.MOSKOVSKY])
            listing = await crud.upsert_listing(session, _raw_listing("CASCADE1"))
            await crud.toggle_favorite(session, user.id, listing.id)
            await crud.set_subscription_active(session, user.id, True)
            await crud.set_pending_notification(session, user.id, [listing.id], {str(listing.id): {"score": 90}}, summary_message_id=555)

        async with session_scope_fixture() as session:
            deleted = await crud.delete_user_completely(session, 42)
            assert deleted is True

        async with session_scope_fixture() as session:
            async def count(model, **where):
                q = select(func.count()).select_from(model)
                for k, v in where.items():
                    q = q.where(getattr(model, k) == v)
                return (await session.execute(q)).scalar_one()

            assert await count(User, id=user.id) == 0
            assert await count(Profile, user_id=user.id) == 0
            assert await count(ProfileDistrict) == 0
            assert await count(Favorite, user_id=user.id) == 0
            assert await count(NotificationSubscription, user_id=user.id) == 0

            # Само объявление — общие данные, не привязанные к пользователю,
            # удаляться не должно.
            listings_count = await count(Listing)
            assert listings_count == 1

    async def test_deleting_nonexistent_user_returns_false(self, session_scope_fixture):
        async with session_scope_fixture() as session:
            deleted = await crud.delete_user_completely(session, telegram_id=999999)
            assert deleted is False


class TestGetNewListingsSince:
    async def test_excludes_old_includes_new(self, session_scope_fixture):
        async with session_scope_fixture() as session:
            old = await crud.upsert_listing(session, _raw_listing("OLD1", district="central"))
            old.parsed_at = utcnow() - timedelta(hours=2)
            await session.flush()

        cutoff = utcnow() - timedelta(hours=1)

        async with session_scope_fixture() as session:
            new = await crud.upsert_listing(session, _raw_listing("NEW1", district="central"))

        async with session_scope_fixture() as session:
            found = await crud.get_new_listings_since(session, cutoff, ["central"])
            ext_ids = {l.external_id for l in found}
            assert "OLD1" not in ext_ids
            assert "NEW1" in ext_ids

    async def test_district_filter_applied(self, session_scope_fixture):
        cutoff = utcnow() - timedelta(hours=1)
        async with session_scope_fixture() as session:
            await crud.upsert_listing(session, _raw_listing("CTR1", district="central"))
            await crud.upsert_listing(session, _raw_listing("FRZ1", district="frunzensky"))

        async with session_scope_fixture() as session:
            found = await crud.get_new_listings_since(session, cutoff, ["central"])
            ext_ids = {l.external_id for l in found}
            assert "CTR1" in ext_ids
            assert "FRZ1" not in ext_ids

    async def test_no_district_filter_returns_all(self, session_scope_fixture):
        cutoff = utcnow() - timedelta(hours=1)
        async with session_scope_fixture() as session:
            await crud.upsert_listing(session, _raw_listing("CTR2", district="central"))
            await crud.upsert_listing(session, _raw_listing("FRZ2", district="frunzensky"))

        async with session_scope_fixture() as session:
            found = await crud.get_new_listings_since(session, cutoff, None)
            ext_ids = {l.external_id for l in found}
            assert {"CTR2", "FRZ2"}.issubset(ext_ids)

    async def test_new_listing_found_even_within_same_second_as_checkpoint(self, session_scope_fixture):
        """Реальный найденный баг: parsed_at раньше ставился через
        server_default=func.now() (у SQLite — точность до целых секунд),
        а last_checked_at генерируется в Python (микросекунды). Из-за
        рассинхрона объявление, вставленное в ту же секунду, что и
        обновление last_checked_at, могло ошибочно не засчитаться
        "новым", хотя физически появилось позже. Теперь оба используют
        Python-side default с одинаковой точностью — проверяем впритык,
        на границе в 1 микросекунду."""
        async with session_scope_fixture() as session:
            listing = await crud.upsert_listing(session, _raw_listing("PREC1"))

        cutoff = listing.parsed_at - timedelta(microseconds=1)

        async with session_scope_fixture() as session:
            found = await crud.get_new_listings_since(session, cutoff, ["central"])
            assert "PREC1" in {l.external_id for l in found}


class TestPendingNotification:
    async def test_set_get_clear_roundtrip(self, session_scope_fixture):
        async with session_scope_fixture() as session:
            user = await crud.get_or_create_user(session, telegram_id=5, username=None, first_name=None)
            await crud.set_pending_notification(session, user.id, [1, 2, 3], {"1": {"score": 80}}, summary_message_id=111)

        async with session_scope_fixture() as session:
            pending = await crud.get_pending_notification(session, user.id)
            assert pending is not None
            listing_ids, explanations = pending
            assert listing_ids == [1, 2, 3]
            assert explanations["1"]["score"] == 80

            await crud.clear_pending_notification(session, user.id)

        async with session_scope_fixture() as session:
            assert await crud.get_pending_notification(session, user.id) is None

    async def test_repeated_set_overwrites_not_duplicates(self, session_scope_fixture):
        async with session_scope_fixture() as session:
            user = await crud.get_or_create_user(session, telegram_id=6, username=None, first_name=None)
            await crud.set_pending_notification(session, user.id, [1], {"1": {}}, summary_message_id=222)
            await crud.set_pending_notification(session, user.id, [1, 2, 3], {"1": {}, "2": {}, "3": {}}, summary_message_id=333)

        async with session_scope_fixture() as session:
            from database.models import PendingNotification
            count = await session.execute(
                select(func.count()).select_from(PendingNotification).where(PendingNotification.user_id == user.id)
            )
            assert count.scalar_one() == 1

            pending = await crud.get_pending_notification(session, user.id)
            assert pending[0] == [1, 2, 3]

    async def test_get_returns_none_when_absent(self, session_scope_fixture):
        async with session_scope_fixture() as session:
            user = await crud.get_or_create_user(session, telegram_id=7, username=None, first_name=None)
            assert await crud.get_pending_notification(session, user.id) is None

    async def test_message_id_stored_and_updated(self, session_scope_fixture):
        async with session_scope_fixture() as session:
            user = await crud.get_or_create_user(session, telegram_id=9, username=None, first_name=None)
            await crud.set_pending_notification(session, user.id, [1], {"1": {}}, summary_message_id=1001)

        async with session_scope_fixture() as session:
            message_id = await crud.get_pending_message_id(session, user.id)
            assert message_id == 1001

        # повторная находка обновляет message_id (например, edit не удался
        # и пришлось отправить новое сообщение)
        async with session_scope_fixture() as session:
            await crud.set_pending_notification(session, user.id, [1, 2], {"1": {}, "2": {}}, summary_message_id=1002)

        async with session_scope_fixture() as session:
            message_id = await crud.get_pending_message_id(session, user.id)
            assert message_id == 1002

    async def test_message_id_none_when_no_pending(self, session_scope_fixture):
        async with session_scope_fixture() as session:
            user = await crud.get_or_create_user(session, telegram_id=10, username=None, first_name=None)
            assert await crud.get_pending_message_id(session, user.id) is None


class TestGetOrCreateUser:
    async def test_does_not_overwrite_with_none(self, session_scope_fixture):
        async with session_scope_fixture() as session:
            await crud.get_or_create_user(session, telegram_id=8, username="real_name", first_name="Real")

        async with session_scope_fixture() as session:
            user = await crud.get_or_create_user(session, telegram_id=8, username=None, first_name=None)
            assert user.username == "real_name", "username не должен затираться None"
            assert user.first_name == "Real"
