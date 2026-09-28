import struct
import tempfile
import unittest
from pathlib import Path

from database.database import Database


class DatabaseTests(unittest.TestCase):
    def test_seeded_hierarchy_and_rejection_preserve_relation(self) -> None:
        database = Database(":memory:")
        try:
            animal = database.lookup_word("動物")
            life = database.lookup_word("生き物")
            self.assertIsNotNone(animal)
            self.assertIsNotNone(life)
            self.assertEqual(database.get_relation_status("動物", "IS_A", "生き物"), "ACTIVE")

            database.learn_relation("猫", "IS_A", "動物")
            self.assertEqual(database.get_relation_status("猫", "IS_A", "動物"), "ACTIVE")
            self.assertTrue(database.reject_relation("猫", "IS_A", "動物"))
            self.assertEqual(database.get_relation_status("猫", "IS_A", "動物"), "REJECTED")
            self.assertFalse(database.reject_relation("猫", "IS_A", "動物"))
        finally:
            database.close()

    def test_learning_is_atomic_when_relation_is_invalid(self) -> None:
        database = Database(":memory:")
        try:
            with self.assertRaises(ValueError):
                database.learn_relation("未作成対象", "IS_A", "未作成対象")
            self.assertIsNone(database.lookup_word("未作成対象"))
        finally:
            database.close()

    def test_learned_knowledge_survives_reopening_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "knowledge.sqlite3"
            database = Database(path)
            database.learn_relation("猫", "IS_A", "動物")
            database.close()

            reopened = Database(path)
            try:
                self.assertEqual(reopened.get_relation_status("猫", "IS_A", "動物"), "ACTIVE")
            finally:
                reopened.close()

    def test_synonym_resolves_to_the_same_concept(self) -> None:
        database = Database(":memory:")
        try:
            database.learn_relation("猫", "IS_A", "動物")
            self.assertTrue(database.learn_synonym("ねこ", "猫"))
            self.assertEqual(database.lookup_word("ねこ"), database.lookup_word("猫"))
        finally:
            database.close()

    def test_conflicting_synonym_does_not_create_a_partial_concept(self) -> None:
        database = Database(":memory:")
        try:
            database.learn_relation("犬", "IS_A", "動物")
            self.assertFalse(database.learn_synonym("犬", "未登録の概念"))
            self.assertIsNone(database.lookup_concept("未登録の概念"))
        finally:
            database.close()

    def test_graph_snapshot_contains_aliases_and_only_active_relations(self) -> None:
        database = Database(":memory:")
        try:
            database.learn_relation("猫", "IS_A", "動物")
            database.learn_synonym("ねこ", "猫")
            database.learn_relation("犬", "IS_A", "動物")
            database.reject_relation("犬", "IS_A", "動物")

            snapshot = database.graph_snapshot()
            cat = next(node for node in snapshot.nodes if node.canonical_name == "猫")
            dog = next(node for node in snapshot.nodes if node.canonical_name == "犬")
            self.assertEqual(cat.words, ("猫", "ねこ"))
            self.assertEqual(dog.words, ("犬",))
            self.assertTrue(
                any(
                    edge.subject_id == cat.id
                    and edge.predicate == "IS_A"
                    and edge.object_id == database.lookup_word("動物").id
                    for edge in snapshot.edges
                )
            )
            self.assertFalse(any(edge.subject_id == dog.id for edge in snapshot.edges))
        finally:
            database.close()

    def test_related_to_is_symmetric_and_graph_shows_one_undirected_edge(self) -> None:
        database = Database(":memory:")
        try:
            database.learn_relation("猫", "RELATED_TO", "犬")
            self.assertEqual(database.get_relation_status("猫", "RELATED_TO", "犬"), "ACTIVE")
            self.assertEqual(database.get_relation_status("犬", "RELATED_TO", "猫"), "ACTIVE")

            snapshot = database.graph_snapshot()
            related_edges = [edge for edge in snapshot.edges if edge.predicate == "RELATED_TO"]
            self.assertEqual(len(related_edges), 1)
            self.assertTrue(database.reject_relation("猫", "RELATED_TO", "犬"))
            self.assertEqual(database.get_relation_status("猫", "RELATED_TO", "犬"), "REJECTED")
            self.assertEqual(database.get_relation_status("犬", "RELATED_TO", "猫"), "REJECTED")
            self.assertFalse(
                any(edge.predicate == "RELATED_TO" for edge in database.graph_snapshot().edges)
            )
        finally:
            database.close()

    def test_reaction_channels_default_off_and_are_guild_channel_scoped(self) -> None:
        database = Database(":memory:")
        try:
            self.assertFalse(database.is_reaction_channel_enabled(1, 10))
            self.assertFalse(database.is_reaction_channel_enabled(None, 10))
            database.set_reaction_channel(1, 10, True)
            self.assertTrue(database.is_reaction_channel_enabled(1, 10))
            self.assertFalse(database.is_reaction_channel_enabled(1, 11))
            self.assertFalse(database.is_reaction_channel_enabled(2, 10))
            database.set_reaction_channel(1, 10, False)
            self.assertFalse(database.is_reaction_channel_enabled(1, 10))
        finally:
            database.close()

    def test_reaction_channel_setting_survives_reopening_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bot.sqlite3"
            database = Database(path)
            database.set_reaction_channel(123, 456, True)
            database.close()

            reopened = Database(path)
            try:
                self.assertTrue(reopened.is_reaction_channel_enabled(123, 456))
                self.assertFalse(reopened.is_reaction_channel_enabled(123, 457))
            finally:
                reopened.close()

    def test_forgetting_alias_preserves_concept_relations_and_other_embeddings(self) -> None:
        database = Database(":memory:")
        try:
            database.learn_relation("猫", "IS_A", "動物")
            database.learn_synonym("ねこ", "猫")
            vector = struct.pack("<2f", 1.0, 0.0)
            database.save_embeddings("test-model", {"ねこ": (2, vector)})

            result = database.forget_word("ねこ")

            self.assertFalse(result.is_canonical)
            self.assertIsNone(database.lookup_word("ねこ"))
            self.assertEqual(database.lookup_word("猫").canonical_name, "猫")
            self.assertEqual(database.get_relation_status("猫", "IS_A", "動物"), "ACTIVE")
            self.assertNotIn("ねこ", database.load_embeddings("test-model"))
        finally:
            database.close()

    def test_forgetting_canonical_promotes_alias_and_keeps_relations(self) -> None:
        database = Database(":memory:")
        try:
            database.learn_relation("猫", "IS_A", "動物")
            database.learn_synonym("ねこ", "猫")

            result = database.forget_word("猫")

            self.assertEqual(result.replacement_word, "ねこ")
            self.assertIsNone(database.lookup_word("猫"))
            self.assertEqual(database.lookup_word("ねこ").canonical_name, "ねこ")
            self.assertEqual(database.get_relation_status("ねこ", "IS_A", "動物"), "ACTIVE")
        finally:
            database.close()

    def test_forgetting_last_word_removes_concept_and_relations(self) -> None:
        database = Database(":memory:")
        try:
            database.learn_relation("犬", "IS_A", "動物")
            result = database.forget_word("犬")
            self.assertTrue(result.removes_concept)
            self.assertIsNone(database.lookup_concept("犬"))
            self.assertIsNone(database.get_relation_status("犬", "IS_A", "動物"))
        finally:
            database.close()

    def test_system_vocabulary_cannot_be_forgotten(self) -> None:
        database = Database(":memory:")
        try:
            result = database.forget_word("動物")
            self.assertTrue(result.is_protected)
            self.assertIsNotNone(database.lookup_word("動物"))
        finally:
            database.close()


if __name__ == "__main__":
    unittest.main()
