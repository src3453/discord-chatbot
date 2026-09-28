from __future__ import annotations

import asyncio
import unittest

from bot.conversation import ConversationManager
from database.database import Database
from knowledge.embeddings import EmbeddingError, EmbeddingIndex
from knowledge.inference import InferenceEngine
from knowledge.ontology import Ontology
from knowledge.vocabulary import VocabularyManager
from nlp.parser import JapaneseParser
from rules.engine import RuleEngine
from tests.embedding_fixtures import SemanticFixtureProvider


class ConversationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.database = Database(":memory:")
        self.ontology = Ontology(self.database)
        self.inference = InferenceEngine(self.database)
        self.bot = ConversationManager(
            parser=JapaneseParser(),
            vocabulary=VocabularyManager(self.database),
            ontology=self.ontology,
            inference=self.inference,
            rules=RuleEngine(),
        )

    def tearDown(self) -> None:
        self.database.close()

    async def send(self, text: str, user_id: int = 10) -> str:
        return await self.bot.process_message(1, 2, user_id, text)

    async def test_unknown_definition_confirmation_and_hierarchy_queries(self) -> None:
        self.assertEqual(await self.send("猫飼いたい"), "猫って何？")
        self.assertEqual(await self.send("動物"), "猫は動物の一種ですか？")
        self.assertEqual(await self.send("はい"), "わかりました。")
        self.assertEqual(self.database.get_relation_status("猫", "IS_A", "動物"), "ACTIVE")
        self.assertEqual(await self.send("猫は動物？"), "はい。")
        self.assertEqual(await self.send("動物は猫？"), "いいえ。")
        self.assertIsNone(self.bot.get_state(1, 2, 10))

    async def test_cancel_commands_clear_active_conversation(self) -> None:
        commands = ("ｷｬﾝｾﾙ。", "やっぱりやめる", "会話を中断してください", "もういいです", "cancel")
        for user_id, command in enumerate(commands, start=20):
            with self.subTest(command=command):
                self.assertEqual(await self.send("猫飼いたい", user_id), "猫って何？")
                self.assertEqual(await self.send(command, user_id), "会話を中断しました。")
                self.assertIsNone(self.bot.get_state(1, 2, user_id))

    async def test_cancel_during_embedding_search_discards_stale_response(self) -> None:
        search_started = asyncio.Event()
        continue_search = asyncio.Event()

        async def blocked_search(*args, **kwargs):
            search_started.set()
            await continue_search.wait()
            return []

        self.bot.vocabulary.find_similar = blocked_search
        pending_message = asyncio.create_task(self.send("猫飼いたい"))
        await search_started.wait()
        self.assertEqual(self.bot.get_state(1, 2, 10).status, "EMBEDDING_SEARCH")

        self.assertEqual(await self.send("キャンセル"), "会話を中断しました。")
        continue_search.set()

        self.assertEqual(await pending_message, "")
        self.assertIsNone(self.bot.get_state(1, 2, 10))

    async def test_rejected_answer_changes_relation_status(self) -> None:
        self.ontology.learn_is_a("猫", "動物")
        self.assertEqual(await self.send("猫は動物？"), "はい。")
        self.assertEqual(await self.send("違う"), "では、猫と動物はどういう関係ですか？")
        self.assertEqual(self.database.get_relation_status("猫", "IS_A", "動物"), "REJECTED")
        self.assertIs(self.inference.check_is_a("猫", "動物"), False)

    async def test_synonym_confirmation_maps_to_existing_concept(self) -> None:
        self.assertEqual(await self.send("キャット"), "キャットって何？")
        self.assertEqual(await self.send("猫"), "キャットは猫の一種ですか？")
        self.assertEqual(await self.send("いいえ"), "「キャット」は「猫」と同じ意味ですか？")
        self.assertEqual(await self.send("そう"), "わかりました。")
        self.assertEqual(self.database.lookup_word("キャット"), self.database.lookup_word("猫"))

    async def test_conversation_state_is_scoped_to_user_and_channel(self) -> None:
        self.assertEqual(await self.send("猫飼いたい", user_id=10), "猫って何？")
        self.assertEqual(await self.send("はい", user_id=11), "はい。")
        other_channel_reply = await self.bot.process_message(1, 3, 10, "はい")
        self.assertEqual(other_channel_reply, "はい。")
        self.assertEqual(self.bot.get_state(1, 2, 10).status, "ASK_DEFINITION")
        self.assertIsNone(self.bot.get_state(1, 2, 11))

    async def test_explicit_negative_statement_rejects_active_relation(self) -> None:
        self.ontology.learn_is_a("猫", "動物")
        self.assertEqual(
            await self.send("猫は動物ではない"),
            "では、猫と動物はどういう関係ですか？",
        )
        self.assertEqual(self.database.get_relation_status("猫", "IS_A", "動物"), "REJECTED")

    async def test_known_hierarchy_is_reused_in_later_messages(self) -> None:
        self.ontology.learn_is_a("猫", "動物")
        self.assertEqual(await self.send("猫好き"), "猫は動物ですね。")

    async def test_only_confirmed_direct_statement_is_learned(self) -> None:
        self.assertEqual(
            await self.send("犬は動物"),
            "犬は動物ということで合っていますか？",
        )
        self.assertIsNone(self.database.lookup_word("犬"))
        self.assertEqual(await self.send("はい"), "わかりました。")
        self.assertEqual(self.database.get_relation_status("犬", "IS_A", "動物"), "ACTIVE")

    async def test_embedding_candidates_require_user_choice_and_relation_confirmation(self) -> None:
        self.database.learn_relation("犬", "IS_A", "動物")
        provider = SemanticFixtureProvider()
        vocabulary = VocabularyManager(
            self.database, EmbeddingIndex(self.database, provider)
        )
        self.bot.vocabulary = vocabulary

        prompt = await self.send("猫飼いたい")
        self.assertIn("1. 動物", prompt)
        self.assertIn("2. 犬", prompt)
        self.assertIsNone(self.database.lookup_word("猫"))

        self.assertEqual(
            await self.send("1"),
            "「猫」と「動物」は同じ意味ですか？",
        )
        self.assertIsNone(self.database.lookup_word("猫"))
        self.assertEqual(await self.send("いいえ"), "猫は動物の一種ですか？")
        self.assertIsNone(self.database.lookup_word("猫"))
        self.assertEqual(await self.send("はい"), "わかりました。")
        self.assertEqual(self.database.get_relation_status("猫", "IS_A", "動物"), "ACTIVE")

    async def test_no_matching_embedding_candidate_switches_to_definition_dialogue(self) -> None:
        self.database.learn_relation("犬", "IS_A", "動物")
        provider = SemanticFixtureProvider()
        self.bot.vocabulary = VocabularyManager(
            self.database, EmbeddingIndex(self.database, provider)
        )

        replies = ("該当しないと思います", "どの候補も違います", "いいえ")
        for user_id, reply in enumerate(replies, start=20):
            with self.subTest(reply=reply):
                self.assertIn("1. 動物", await self.send("猫飼いたい", user_id))
                self.assertEqual(await self.send(reply, user_id), "猫って何？")
                state = self.bot.get_state(1, 2, user_id)
                self.assertEqual(state.status, "ASK_DEFINITION")
                self.assertEqual(state.choices, ())
                self.assertFalse(state.embedding_candidate)

                self.assertEqual(
                    await self.send("猫は哺乳類", user_id),
                    "猫は哺乳類の一種ですか？",
                )
                self.assertEqual(
                    self.bot.get_state(1, 2, user_id).status,
                    "ASK_CONFIRMATION",
                )

    async def test_unknown_relation_question_uses_embedding_candidates(self) -> None:
        self.database.learn_relation("犬", "IS_A", "動物")
        provider = SemanticFixtureProvider()
        self.bot.vocabulary = VocabularyManager(
            self.database, EmbeddingIndex(self.database, provider)
        )
        prompt = await self.send("猫は動物？")
        self.assertIn("1. 動物", prompt)
        self.assertIsNone(self.database.lookup_word("猫"))

    async def test_similar_words_become_symmetric_related_to_not_is_a_or_same_as(self) -> None:
        self.ontology.learn_is_a("犬", "動物")
        self.assertEqual(await self.send("猫飼いたい"), "猫って何？")
        self.assertEqual(await self.send("犬"), "猫は犬の一種ですか？")
        self.assertEqual(await self.send("違う"), "「猫」は「犬」と同じ意味ですか？")
        self.assertEqual(
            await self.send("違う"), "では、猫と犬はどういう関係ですか？"
        )
        self.assertEqual(
            await self.send("似た言葉"),
            "「猫」と「犬」は似た言葉として関連していますか？",
        )
        self.assertIsNone(self.database.lookup_word("猫"))
        self.assertEqual(await self.send("はい"), "わかりました。")

        self.assertEqual(self.database.get_relation_status("猫", "RELATED_TO", "犬"), "ACTIVE")
        self.assertEqual(self.database.get_relation_status("犬", "RELATED_TO", "猫"), "ACTIVE")
        self.assertIsNone(self.database.get_relation_status("猫", "SAME_AS", "犬"))
        self.assertIsNone(self.inference.check_is_a("猫", "犬"))
    async def test_unavailable_embedding_service_falls_back_to_definition_question(self) -> None:
        class UnavailableProvider:
            model_id = "unavailable"

            async def embed(self, texts):
                raise EmbeddingError("local service is unavailable")

        self.bot.vocabulary = VocabularyManager(
            self.database, EmbeddingIndex(self.database, UnavailableProvider())
        )
        self.assertEqual(await self.send("猫飼いたい"), "猫って何？")
        self.assertEqual(self.bot.get_state(1, 2, 10).status, "ASK_DEFINITION")


if __name__ == "__main__":
    unittest.main()
