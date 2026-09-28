from __future__ import annotations

from database.database import Concept, Database
from knowledge.embeddings import EmbeddingCandidate, EmbeddingIndex
from nlp.parser import Token


class VocabularyManager:
    def __init__(
        self, database: Database, embedding_index: EmbeddingIndex | None = None
    ):
        self.database = database
        self.embedding_index = embedding_index

    def lookup(self, word: str) -> Concept | None:
        return self.database.lookup_word(word)

    async def find_similar(
        self, word: str, *, limit: int = 3, minimum_similarity: float = 0.45
    ) -> list[EmbeddingCandidate]:
        if self.embedding_index is None:
            return []
        return await self.embedding_index.search(
            word, limit=limit, minimum_similarity=minimum_similarity
        )

    def lookup_token(self, token: Token) -> Concept | None:
        for candidate in dict.fromkeys((token.normalized, token.dictionary_form, token.surface)):
            if candidate.strip():
                concept = self.database.lookup_word(candidate)
                if concept is not None:
                    return concept
        return None

    def first_unknown_noun(self, tokens: list[Token]) -> str | None:
        seen: set[str] = set()
        for token in tokens:
            if not token.is_noun:
                continue
            if len(token.part_of_speech) > 1 and token.part_of_speech[1] in {"数詞", "代名詞"}:
                continue
            candidates = [
                candidate.strip()
                for candidate in dict.fromkeys((token.normalized, token.dictionary_form, token.surface))
                if candidate.strip()
            ]
            if any(candidate in seen for candidate in candidates):
                continue
            seen.update(candidates)
            if not any(self.database.lookup_word(candidate) is not None for candidate in candidates):
                return candidates[0] if candidates else None
        return None
