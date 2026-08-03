import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


os.environ.setdefault("DISCORD_TOKEN", "test")
os.environ.setdefault("CLICKUP_TOKEN", "test")
os.environ.setdefault("CLICKUP_LIST_ID", "test")

import discord

import bot


class CheckinEntryTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_entry_surface_opens_the_same_private_form(self):
        for offset, channel_type in enumerate(
            (discord.ChannelType.text, discord.ChannelType.private),
        ):
            with self.subTest(channel_type=channel_type):
                user_id = 900_000 + offset
                response = SimpleNamespace(send_message=AsyncMock())
                interaction = SimpleNamespace(
                    user=SimpleNamespace(id=user_id),
                    channel=SimpleNamespace(type=channel_type),
                    response=response,
                )

                with (
                    patch.object(
                        bot,
                        "fetch_accelerate_usernames",
                        new=AsyncMock(return_value=set()),
                    ),
                    patch.object(bot, "has_checked_in", return_value=False),
                ):
                    await bot._dispatch_checkin_entry(interaction)
                    await asyncio.sleep(0)

                response.send_message.assert_awaited_once()
                call = response.send_message.await_args
                self.assertIn("private form", call.args[0])
                self.assertTrue(call.kwargs["ephemeral"])
                self.assertIsInstance(call.kwargs["view"], bot.StageSelectView)
                bot.release_checkin_lock(user_id)

    def test_public_conversational_flow_is_not_available(self):
        self.assertFalse(hasattr(bot, "run_conversational_checkin"))


class CheckinSummaryTests(unittest.TestCase):
    def test_completed_checkin_has_one_compact_canonical_summary(self):
        answers = {
            "stage": "3. Creating Ads",
            "roadmap_step": "3.2",
            "weekly_hours": "5–10 hours",
            "feeling": "Locked in",
            "weeks": "2",
            "blocker": "Waiting for creative feedback",
            "help_needed": "Review the first three ads",
            "next_steps": "Launch the winning creative",
        }
        summary = bot.format_ticket_checkin_summary(
            "<@123>",
            answers,
            {"product_name": "Example Product", "store_url": "https://example.com/"},
        )

        self.assertEqual(summary.count("Weekly check-in submitted"), 1)
        for expected in (
            "**Stage:** 3. Creating Ads",
            "**Roadmap step:** 3.2",
            "**Hours last week:** 5–10 hours",
            "**Feeling:** Locked in",
            "**Weeks in stage:** 2",
            "**Product:** Example Product",
            "**Store URL:** https://example.com/",
            "**Blocker:** Waiting for creative feedback",
            "**Support that would help:** Review the first three ads",
            "**ONE key thing this week:** Launch the winning creative",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, summary)


if __name__ == "__main__":
    unittest.main()
