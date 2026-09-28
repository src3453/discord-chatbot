from __future__ import annotations

import asyncio
import io
import logging

import discord
from discord import app_commands

from bot.conversation import ConversationManager
from database.database import Database, ForgetWordPlan
from knowledge.graph import GraphRenderError, render_knowledge_graph

logger = logging.getLogger(__name__)


def _safe_label(value: str) -> str:
    return discord.utils.escape_mentions(discord.utils.escape_markdown(value))


def _forget_effect(plan: ForgetWordPlan) -> str:
    word = _safe_label(plan.word)
    if not plan.is_canonical:
        return f"`{word}` の表記だけを削除し、概念・他の語彙・関係は保持します。"
    if plan.replacement_word is not None:
        replacement = _safe_label(plan.replacement_word)
        return f"代表語 `{word}` を削除し、`{replacement}` を代表語に変更します。概念と関係は保持します。"
    return f"`{word}` の概念、別名、およびその概念に接続するすべての関係を削除します。"


def create_discord_client(
    conversation: ConversationManager, database: Database
) -> discord.Client:
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)
    command_tree = app_commands.CommandTree(client)
    commands_synced = False

    @command_tree.command(
        name="knowledge_graph", description="知識データベースをネットワーク図で表示します"
    )
    async def knowledge_graph(interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        snapshot = database.graph_snapshot()
        try:
            image_bytes = await asyncio.to_thread(render_knowledge_graph, snapshot)
        except GraphRenderError as error:
            logger.exception("Could not render knowledge graph")
            await interaction.followup.send(f"図を作成できませんでした: {error}", ephemeral=True)
            return
        await interaction.followup.send(
            file=discord.File(io.BytesIO(image_bytes), filename="knowledge_graph.png")
        )

    @command_tree.command(
        name="reaction_channel", description="このチャンネルでBotのメッセージ反応を切り替えます"
    )
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.describe(enabled="このチャンネルでのメッセージ反応を有効にする")
    async def reaction_channel(
        interaction: discord.Interaction, enabled: bool
    ) -> None:
        permissions = getattr(interaction.user, "guild_permissions", None)
        if (
            interaction.guild_id is None
            or interaction.channel_id is None
            or not getattr(permissions, "manage_channels", False)
        ):
            await interaction.response.send_message(
                "サーバー内でチャンネル管理権限を持つユーザーのみ設定できます。",
                ephemeral=True,
            )
            return
        database.set_reaction_channel(
            interaction.guild_id, interaction.channel_id, enabled
        )
        status = "有効" if enabled else "無効"
        await interaction.response.send_message(
            f"このチャンネルのメッセージ反応を{status}にしました。", ephemeral=True
        )

    @command_tree.command(
        name="forget_word", description="共有知識から特定の語彙を忘れさせます"
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(
        word="忘れさせる登録済み語彙",
        confirm="削除内容を確認した後に true を指定します",
    )
    async def forget_word(
        interaction: discord.Interaction, word: str, confirm: bool = False
    ) -> None:
        permissions = getattr(interaction.user, "guild_permissions", None)
        if (
            interaction.guild_id is None
            or not getattr(permissions, "manage_guild", False)
        ):
            await interaction.response.send_message(
                "サーバー管理権限を持つユーザーのみ実行できます。", ephemeral=True
            )
            return
        plan = database.preview_forget_word(word)
        if plan is None:
            await interaction.response.send_message(
                f"`{_safe_label(word)}` は登録されていません。", ephemeral=True
            )
            return
        if plan.is_protected:
            await interaction.response.send_message(
                f"`{_safe_label(plan.word)}` はシステム定義語のため削除できません。",
                ephemeral=True,
            )
            return
        if not confirm:
            await interaction.response.send_message(
                f"この操作は全サーバーで共有する知識に適用されます。{_forget_effect(plan)} "
                "実行するには同じコマンドを `confirm: true` で再度呼び出してください。",
                ephemeral=True,
            )
            return

        result = database.forget_word(word)
        if result is None:
            message = f"`{_safe_label(word)}` は既に登録されていません。"
        elif result.is_protected:
            message = f"`{_safe_label(result.word)}` はシステム定義語のため削除できません。"
        else:
            message = f"削除しました。{_forget_effect(result)}"
        await interaction.response.send_message(message, ephemeral=True)

    client.command_tree = command_tree

    @client.event
    async def on_ready() -> None:
        nonlocal commands_synced
        if not commands_synced:
            synced_commands = await command_tree.sync()
            commands_synced = True
            logger.info("Synced %d Discord application commands", len(synced_commands))
        logger.info("Discord connected as %s", client.user)

    @client.event
    async def on_message(message: discord.Message) -> None:
        if message.author.bot:
            return
        if message.guild is None or not database.is_reaction_channel_enabled(
            message.guild.id, message.channel.id
        ):
            return
        logger.info("Message received")
        response = await conversation.process_message(
            guild_id=message.guild.id,
            channel_id=message.channel.id,
            user_id=message.author.id,
            text=message.content,
        )
        if response:
            await message.channel.send(response)

    return client
