import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


os.environ.setdefault("DISCORD_TOKEN", "test")
os.environ.setdefault("CLICKUP_TOKEN", "test")
os.environ.setdefault("CLICKUP_LIST_ID", "test")

import bot


class FakeMember:
    def __init__(self, member_id, name, *, joined_at=None, bot_user=False):
        self.id = member_id
        self.name = name
        self.display_name = name
        self.joined_at = joined_at
        self.bot = bot_user


class FakeOverwrite:
    def __init__(self, view_channel):
        self.view_channel = view_channel


class FakeChannel:
    def __init__(self, name, overwrites=None, category=None):
        self.name = name
        self.overwrites = overwrites or {}
        self.category = category
        self.send = AsyncMock()


class FakeGuild:
    def __init__(self, members, channels):
        self.id = 777
        self.members = members
        self.text_channels = channels

    def get_member(self, member_id):
        return next((member for member in self.members if member.id == member_id), None)


def active_record(**overrides):
    record = {
        "name": "Example Member",
        "task_id": "task-1",
        "status": "active",
        "program": "Accelerate",
        "discord_username": "example",
        "discord_username_key": "example",
        "store_url": "",
    }
    record.update(overrides)
    return record


class CanonicalEligibilityTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 3, tzinfo=timezone.utc)
        self.member = FakeMember(
            123,
            "example",
            joined_at=self.now - timedelta(weeks=3),
        )
        self.empty_stage_index = {"by_user_id": {}, "by_username": {}}

    def evaluate(self, record, **kwargs):
        return bot.evaluate_checkin_eligibility(
            self.member,
            record,
            self.empty_stage_index,
            now_utc=self.now,
            **kwargs,
        )

    def test_active_accelerate_member_is_eligible(self):
        self.assertTrue(self.evaluate(active_record())["eligible"])

    def test_active_accelerate_plus_member_is_eligible(self):
        self.assertTrue(
            self.evaluate(active_record(program="Accelerate Plus"))["eligible"]
        )

    def test_non_member_is_blocked(self):
        result = self.evaluate(None)
        self.assertFalse(result["eligible"])
        self.assertIn("not_member", {reason["code"] for reason in result["reasons"]})

    def test_paused_and_inactive_members_are_blocked(self):
        for status in ("paused", "inactive", "refunded", "complete"):
            with self.subTest(status=status):
                result = self.evaluate(active_record(status=status))
                self.assertFalse(result["eligible"])
                self.assertIn(
                    "inactive_status",
                    {reason["code"] for reason in result["reasons"]},
                )

    def test_member_outside_join_window_is_blocked(self):
        self.member.joined_at = self.now - timedelta(weeks=13)
        result = self.evaluate(active_record())
        self.assertFalse(result["eligible"])
        self.assertIn("outside_window", {reason["code"] for reason in result["reasons"]})

    def test_already_checked_in_member_is_blocked(self):
        result = self.evaluate(active_record(), already_checked_in=True)
        self.assertFalse(result["eligible"])
        self.assertIn(
            "already_checked_in",
            {reason["code"] for reason in result["reasons"]},
        )


class AdvancedStageTests(unittest.TestCase):
    def task(self, *, created, stage, username="example", user_id=None):
        tags = [] if user_id is None else [{"name": f"uid:{user_id}"}]
        return {
            "date_created": str(created),
            "description": f"**Discord Username:** {username}\n",
            "tags": tags,
            "custom_fields": [{"id": bot.CI_FIELD_STAGE, "value": stage}],
        }

    def test_latest_legacy_username_stage_controls_exclusion(self):
        index = bot._build_stage_exclusion_index([
            self.task(created=100, stage="5. Making Sales"),
            self.task(created=200, stage="3. Creating Ads"),
        ])
        member = FakeMember(123, "example")
        self.assertFalse(bot.is_advanced_stage(member, index))

    def test_legacy_advanced_stage_is_repaired_without_uid_tag(self):
        index = bot._build_stage_exclusion_index([
            self.task(created=100, stage="5. Making Sales"),
        ])
        member = FakeMember(123, "example")
        self.assertTrue(bot.is_advanced_stage(member, index))

    def test_legacy_clickup_username_survives_discord_rename(self):
        index = bot._build_stage_exclusion_index([
            self.task(created=100, stage="5. Making Sales", username="oldname"),
        ])
        member = FakeMember(123, "renamed-user")
        record = active_record(discord_username_key="oldname")
        self.assertTrue(bot.is_advanced_stage(member, index, record))

    def test_stable_user_id_takes_priority_over_old_username(self):
        index = bot._build_stage_exclusion_index([
            self.task(created=100, stage="5. Making Sales", username="example"),
            self.task(
                created=200,
                stage="3. Creating Ads",
                username="renamed-user",
                user_id="123",
            ),
        ])
        member = FakeMember(123, "example")
        self.assertFalse(bot.is_advanced_stage(member, index))

    def test_new_checkins_include_stable_discord_id(self):
        member = FakeMember(123, "example")
        self.assertEqual(
            bot.checkin_task_tags(member),
            ["check-in", "example", "uid:123"],
        )


class StableTicketRoutingTests(unittest.TestCase):
    def test_explicit_member_permission_wins_over_username_slug(self):
        member = FakeMember(123, "current-name")
        owned = FakeChannel(
            "896-old-family-name",
            {member: FakeOverwrite(True)},
        )
        slug_only = FakeChannel("897-current-name")
        guild = FakeGuild([member], [owned, slug_only])

        self.assertEqual(bot._ticket_channels_for_member(guild, member), [owned])

    def test_username_slug_remains_a_migration_fallback(self):
        member = FakeMember(123, "current.name")
        slug = FakeChannel("897-currentname")
        guild = FakeGuild([member], [slug])

        self.assertEqual(bot._ticket_channels_for_member(guild, member), [slug])

    def test_clickup_record_can_bind_through_ticket_owner_id(self):
        member = FakeMember(123, "renamed-user")
        owned = FakeChannel("896-oldname", {member: FakeOverwrite(True)})
        guild = FakeGuild([member], [owned])
        record = active_record(
            discord_username="oldname",
            discord_username_key="oldname",
        )
        old_cache = dict(bot._accelerate_cache)
        try:
            bot._accelerate_cache["records"] = [record]
            bot._accelerate_cache["records_by_user_id"] = {}
            bot._accelerate_cache["bindings_guild_id"] = None
            self.assertIs(bot.checkin_member_record_for(guild, member), record)
        finally:
            bot._accelerate_cache.clear()
            bot._accelerate_cache.update(old_cache)


class ReminderEligibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_reminders_send_only_after_canonical_eligibility_passes(self):
        now = datetime.now(timezone.utc)
        active = FakeMember(1, "active", joined_at=now - timedelta(weeks=2))
        paused = FakeMember(2, "paused", joined_at=now - timedelta(weeks=2))
        outsider = FakeMember(3, "outsider", joined_at=now - timedelta(weeks=2))
        active.mention = "<@1>"
        paused.mention = "<@2>"
        outsider.mention = "<@3>"
        active_channel = FakeChannel("1-active", {active: FakeOverwrite(True)})
        paused_channel = FakeChannel("2-paused", {paused: FakeOverwrite(True)})
        guild = FakeGuild([active, paused, outsider], [active_channel, paused_channel])
        records = {
            active.id: active_record(discord_username_key="active"),
            paused.id: active_record(
                status="paused",
                discord_username="paused",
                discord_username_key="paused",
            ),
        }
        fake_client = SimpleNamespace(guilds=[guild])

        with (
            patch.object(bot, "client", fake_client),
            patch.object(bot, "fetch_accelerate_usernames", new=AsyncMock(return_value={"active"})),
            patch.object(
                bot,
                "fetch_stage_exclusions",
                new=AsyncMock(return_value={"by_user_id": {}, "by_username": {}}),
            ),
            patch.object(bot, "_bind_checkin_records_to_guild", return_value={}),
            patch.object(
                bot,
                "checkin_member_record_for",
                side_effect=lambda _guild, member: records.get(member.id),
            ),
            patch.object(bot, "load_pending", return_value={}),
            patch.object(bot, "has_checked_in", return_value=False),
            patch.object(bot.asyncio, "sleep", new=AsyncMock()),
        ):
            await bot._send_checkin_dms("test", "Hello {mention}", "Hello")

        active_channel.send.assert_awaited_once()
        paused_channel.send.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
