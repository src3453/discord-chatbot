from __future__ import annotations

from collections.abc import Sequence

from knowledge.embeddings import EmbeddingIndex


class SemanticFixtureProvider:
    model_id = "test-semantic-fixture"

    def __init__(self) -> None:
        self.vectors: dict[str, tuple[float, ...]] = {
            "猫": (1.0, 0.0),
            "動物": (0.95, 0.05),
            "犬": (0.8, 0.6),
        }
        self.document_requests: list[str] = []
        self.call_count = 0
    async def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        self.call_count += 1
        vectors = []
        for text in texts:
            if text.startswith(EmbeddingIndex.QUERY_PREFIX):
                word = text.removeprefix(EmbeddingIndex.QUERY_PREFIX)
            elif text.startswith(EmbeddingIndex.DOCUMENT_PREFIX):
                word = text.removeprefix(EmbeddingIndex.DOCUMENT_PREFIX)
                self.document_requests.append(word)
            else:
                raise AssertionError(f"Unexpected embedding prompt: {text}")
            vectors.append(self.vectors.get(word, (0.0, 1.0)))
        return vectors
