from __future__ import annotations

import asyncio
import json
import math
import struct
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol, Sequence
from urllib.parse import urlsplit

from database.database import Concept, Database


class EmbeddingError(RuntimeError):
    """LM Studio could not produce a valid embedding response."""


@dataclass(frozen=True)
class EmbeddingCandidate:
    concept: Concept
    similarity: float


class EmbeddingProvider(Protocol):
    model_id: str

    async def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        """Return one finite vector for each input string, in input order."""


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None

class LMStudioEmbeddings:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:1234/v1",
        model_id: str = "text-embedding-embeddinggemma-300m-qat",
        api_key: str = "lm-studio",
        timeout: float = 15.0,
    ):
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("LM Studio must use a clean loopback URL")
        if not model_id.strip():
            raise ValueError("LM Studio embedding model ID cannot be empty")
        self.base_url = base_url.rstrip("/")
        self.model_id = model_id.strip()
        self.api_key = api_key.strip()
        self.timeout = timeout

    async def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        if not texts:
            return []
        return await asyncio.to_thread(self._request_embeddings, list(texts))

    def _request_embeddings(self, texts: list[str]) -> list[tuple[float, ...]]:
        payload = json.dumps(
            {"model": self.model_id, "input": texts}, ensure_ascii=False
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            f"{self.base_url}/embeddings", data=payload, headers=headers, method="POST"
        )
        try:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}), _NoRedirectHandler()
            )
            with opener.open(request, timeout=self.timeout) as response:
                result = json.load(response)
        except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError) as error:
            raise EmbeddingError("LM Studio embedding request failed") from error

        rows = result.get("data") if isinstance(result, dict) else None
        if not isinstance(rows, list) or len(rows) != len(texts):
            raise EmbeddingError("LM Studio returned an unexpected embedding count")
        if all(isinstance(row, dict) and isinstance(row.get("index"), int) for row in rows):
            rows = sorted(rows, key=lambda row: row["index"])

        vectors: list[tuple[float, ...]] = []
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("embedding"), list):
                raise EmbeddingError("LM Studio returned an invalid embedding")
            vector = self._validate_vector(row["embedding"])
            if vectors and len(vector) != len(vectors[0]):
                raise EmbeddingError("LM Studio returned inconsistent dimensions")
            vectors.append(vector)
        return vectors

    @staticmethod
    def _validate_vector(values: Sequence[object]) -> tuple[float, ...]:
        try:
            vector = tuple(float(value) for value in values)
        except (TypeError, ValueError, OverflowError) as error:
            raise EmbeddingError("LM Studio returned a non-numeric embedding") from error
        if not vector or not all(math.isfinite(value) for value in vector):
            raise EmbeddingError("LM Studio returned an empty or non-finite embedding")
        return vector


class EmbeddingIndex:
    QUERY_PREFIX = "task: search result | query: "
    DOCUMENT_PREFIX = "title: none | text: "
    BATCH_SIZE = 128

    def __init__(self, database: Database, provider: EmbeddingProvider):
        self.database = database
        self.provider = provider
        self.model_id = provider.model_id

    async def search(
        self, query: str, *, limit: int = 3, minimum_similarity: float = 0.45
    ) -> list[EmbeddingCandidate]:
        if limit <= 0:
            return []
        if not 0.0 <= minimum_similarity <= 1.0:
            raise ValueError("minimum_similarity must be between 0 and 1")
        entries = self.database.list_vocabulary_entries()
        if not entries:
            return []

        query_vectors = await self.provider.embed([self.QUERY_PREFIX + query])
        query_vector = self._single_vector(query_vectors)
        stored = self.database.load_embeddings(self.model_id)
        vectors: dict[str, tuple[float, ...]] = {}
        missing: list[tuple[str, Concept]] = []
        for entry in entries:
            record = stored.get(entry.word)
            vector = self._decode(record) if record is not None else None
            if vector is None or len(vector) != len(query_vector):
                missing.append((entry.word, entry.concept))
            else:
                vectors[entry.word] = vector

        for offset in range(0, len(missing), self.BATCH_SIZE):
            batch = missing[offset:offset + self.BATCH_SIZE]
            texts = [self.DOCUMENT_PREFIX + word for word, _ in batch]
            batch_vectors = await self.provider.embed(texts)
            if len(batch_vectors) != len(batch):
                raise EmbeddingError("Embedding provider returned an unexpected vector count")
            records: dict[str, tuple[int, bytes]] = {}
            for (word, _), raw_vector in zip(batch, batch_vectors):
                vector = self._validate_vector(raw_vector)
                if len(vector) != len(query_vector):
                    raise EmbeddingError("Embedding dimensions do not match the query")
                vectors[word] = vector
                records[word] = (len(vector), self._encode(vector))
            self.database.save_embeddings(self.model_id, records)

        best_by_concept: dict[int, EmbeddingCandidate] = {}
        for entry in entries:
            vector = vectors.get(entry.word)
            if vector is None or entry.word == query or entry.concept.canonical_name == query:
                continue
            similarity = self._cosine_similarity(query_vector, vector)
            if similarity < minimum_similarity:
                continue
            candidate = EmbeddingCandidate(entry.concept, similarity)
            previous = best_by_concept.get(entry.concept.id)
            if previous is None or candidate.similarity > previous.similarity:
                best_by_concept[entry.concept.id] = candidate

        return sorted(
            best_by_concept.values(),
            key=lambda candidate: (-candidate.similarity, candidate.concept.canonical_name),
        )[:limit]

    @classmethod
    def _single_vector(cls, vectors: Sequence[Sequence[float]]) -> tuple[float, ...]:
        if len(vectors) != 1:
            raise EmbeddingError("Embedding provider returned an unexpected vector count")
        return cls._validate_vector(vectors[0])

    @staticmethod
    def _validate_vector(values: Sequence[float]) -> tuple[float, ...]:
        try:
            vector = tuple(float(value) for value in values)
        except (TypeError, ValueError, OverflowError) as error:
            raise EmbeddingError("Embedding provider returned a non-numeric vector") from error
        if not vector or not all(math.isfinite(value) for value in vector):
            raise EmbeddingError("Embedding provider returned an empty or non-finite vector")
        return vector

    @staticmethod
    def _decode(record: tuple[int, bytes]) -> tuple[float, ...] | None:
        dimension, blob = record
        if dimension <= 0 or len(blob) != dimension * 4:
            return None
        vector = struct.unpack(f"<{dimension}f", blob)
        if not all(math.isfinite(value) for value in vector):
            return None
        return vector

    @staticmethod
    def _encode(vector: Sequence[float]) -> bytes:
        return struct.pack(f"<{len(vector)}f", *vector)

    @staticmethod
    def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
        if len(left) != len(right):
            raise EmbeddingError("Embedding dimensions do not match")
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0.0 or right_norm == 0.0:
            return -1.0
        return dot / (left_norm * right_norm)
