from __future__ import annotations

import unittest

from database.database import Database
from knowledge.embeddings import EmbeddingIndex, LMStudioEmbeddings
from tests.embedding_fixtures import SemanticFixtureProvider


class EmbeddingIndexTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.database = Database(":memory:")
        self.database.learn_relation("猫", "IS_A", "動物")
        self.database.learn_synonym("ねこ", "猫")
        self.database.learn_relation("犬", "IS_A", "動物")
        self.provider = SemanticFixtureProvider()
        self.provider.vectors["ねこ"] = (1.0, 0.0)
        self.provider.vectors["ミケ"] = (1.0, 0.0)
        self.index = EmbeddingIndex(self.database, self.provider)

    async def asyncTearDown(self) -> None:
        self.database.close()

    def test_provider_rejects_non_loopback_endpoint(self) -> None:
        with self.assertRaises(ValueError):
            LMStudioEmbeddings(base_url="https://api.example.com/v1")

    async def test_search_ranks_distinct_concepts_and_reuses_stored_vectors(self) -> None:
        candidates = await self.index.search(
            "ミケ", limit=3, minimum_similarity=0.75
        )

        self.assertEqual(candidates[0].concept.canonical_name, "猫")
        self.assertEqual(candidates[1].concept.canonical_name, "動物")
        self.assertEqual(len({candidate.concept.id for candidate in candidates}), len(candidates))
        self.assertEqual(len(self.provider.document_requests), len(self.database.list_vocabulary_entries()))
        self.assertTrue(self.database.load_embeddings(self.provider.model_id))

        await self.index.search("別の未知語", limit=3, minimum_similarity=0.75)
        self.assertEqual(len(self.provider.document_requests), len(self.database.list_vocabulary_entries()))

    async def test_nonpositive_limit_skips_embedding(self) -> None:
        database = Database(":memory:")
        provider = SemanticFixtureProvider()
        try:
            index = EmbeddingIndex(database, provider)
            self.assertEqual(await index.search("猫", limit=0), [])
            self.assertEqual(provider.call_count, 0)
        finally:
            database.close()


if __name__ == "__main__":
    unittest.main()
