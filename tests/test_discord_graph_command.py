from __future__ import annotations

import unittest
from io import BytesIO

import discord
from PIL import Image

from bot.discord_bot import create_discord_client
from database.database import Database
from bot.conversation import ConversationManager
from knowledge.inference import InferenceEngine
from knowledge.ontology import Ontology
from knowledge.vocabulary import VocabularyManager
from nlp.parser import JapaneseParser
from rules.engine import RuleEngine


class _FakeResponse:
    def __init__(self) -> None:
        self.deferred = False
        self.message = ""
        self.ephemeral = False

    async def defer(self, *, thinking: bool = False) -> None:
        self.deferred = thinking

    async def send_message(self, content: str, *, ephemeral: bool = False) -> None:
        self.message = content
        self.ephemeral = ephemeral


class _FakeFollowup:
    def __init__(self) -> None:
        self.filename = ""
        self.image = b""

    async def send(self, *, file: discord.File, ephemeral: bool = False) -> None:
        self.filename = file.filename
        self.image = file.fp.getvalue()


class _FakeGuildPermissions:
    def __init__(self, *, manage_channels: bool, manage_guild: bool) -> None:
        self.manage_channels = manage_channels
        self.manage_guild = manage_guild


class _FakeUser:
    def __init__(self, permissions: _FakeGuildPermissions) -> None:
        self.guild_permissions = permissions


class _FakeInteraction:
    def __init__(
        self,
        *,
        guild_id: int | None = 123,
        channel_id: int | None = 456,
        manage_channels: bool = True,
        manage_guild: bool = True,
    ) -> None:
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.user = _FakeUser(
            _FakeGuildPermissions(
                manage_channels=manage_channels, manage_guild=manage_guild
            )
        )
        self.response = _FakeResponse()
        self.followup = _FakeFollowup()


class _FakeAuthor:
    id = 789
    bot = False


class _FakeGuild:
    id = 123


class _FakeChannel:
    id = 456

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, content: str) -> None:
        self.sent.append(content)


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content
        self.author = _FakeAuthor()
        self.guild = _FakeGuild()
        self.channel = _FakeChannel()
class DiscordGraphCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.database = Database(":memory:")
        self.database.learn_relation("猫", "IS_A", "動物")
        self.client = create_discord_client(None, self.database)

    async def asyncTearDown(self) -> None:
        await self.client.close()
        self.database.close()

    async def test_message_reaction_stays_off_until_channel_is_enabled(self) -> None:
        conversation = ConversationManager(
            parser=JapaneseParser(),
            vocabulary=VocabularyManager(self.database),
            ontology=Ontology(self.database),
            inference=InferenceEngine(self.database),
            rules=RuleEngine(),
        )
        client = create_discord_client(conversation, self.database)
        message = _FakeMessage("動物")
        try:
            await client.on_message(message)
            self.assertEqual(message.channel.sent, [])

            self.database.set_reaction_channel(123, 456, True)
            await client.on_message(message)
            self.assertEqual(message.channel.sent, ["動物は生き物ですね。"])
        finally:
            await client.close()

    async def test_slash_command_sends_a_rendered_png_attachment(self) -> None:
        command = self.client.command_tree.get_command("knowledge_graph")
        self.assertIsNotNone(command)
        interaction = _FakeInteraction()

        await command.callback(interaction)

        self.assertTrue(interaction.response.deferred)
        self.assertEqual(interaction.followup.filename, "knowledge_graph.png")
        image = Image.open(BytesIO(interaction.followup.image))
        image.load()
        self.assertEqual(image.format, "PNG")



    async def test_reaction_channel_command_toggles_current_channel(self) -> None:
        command = self.client.command_tree.get_command("reaction_channel")
        self.assertFalse(self.database.is_reaction_channel_enabled(123, 456))

        enabled = _FakeInteraction()
        await command.callback(enabled, True)
        self.assertTrue(self.database.is_reaction_channel_enabled(123, 456))
        self.assertTrue(enabled.response.ephemeral)

        disabled = _FakeInteraction()
        await command.callback(disabled, False)
        self.assertFalse(self.database.is_reaction_channel_enabled(123, 456))

    async def test_reaction_channel_command_rejects_users_without_permission(self) -> None:
        command = self.client.command_tree.get_command("reaction_channel")
        interaction = _FakeInteraction(manage_channels=False)

        await command.callback(interaction, True)

        self.assertFalse(self.database.is_reaction_channel_enabled(123, 456))
        self.assertTrue(interaction.response.ephemeral)

    async def test_forget_command_previews_then_confirms_shared_knowledge_change(self) -> None:
        self.database.learn_relation("猫", "IS_A", "動物")
        self.database.learn_synonym("ねこ", "猫")
        command = self.client.command_tree.get_command("forget_word")

        preview = _FakeInteraction()
        await command.callback(preview, "猫", False)
        self.assertIsNotNone(self.database.lookup_word("猫"))
        self.assertIn("confirm: true", preview.response.message)
        self.assertIn("全サーバー", preview.response.message)

        confirmation = _FakeInteraction()
        await command.callback(confirmation, "猫", True)
        self.assertIsNone(self.database.lookup_word("猫"))
        self.assertEqual(self.database.lookup_word("ねこ").canonical_name, "ねこ")
        self.assertEqual(
            self.database.get_relation_status("ねこ", "IS_A", "動物"), "ACTIVE"
        )
        self.assertTrue(confirmation.response.ephemeral)

    async def test_forget_command_requires_manage_server_permission(self) -> None:
        command = self.client.command_tree.get_command("forget_word")
        interaction = _FakeInteraction(manage_guild=False)

        await command.callback(interaction, "猫", True)

        self.assertIsNotNone(self.database.lookup_word("猫"))
        self.assertTrue(interaction.response.ephemeral)


if __name__ == "__main__":
    unittest.main()
