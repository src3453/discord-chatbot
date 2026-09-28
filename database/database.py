from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class Concept:
    id: int
    canonical_name: str


@dataclass(frozen=True)
class VocabularyEntry:
    word: str
    concept: Concept


@dataclass(frozen=True)
class GraphNode:
    id: int
    canonical_name: str
    words: tuple[str, ...]


@dataclass(frozen=True)
class GraphEdge:
    subject_id: int
    predicate: str
    object_id: int


@dataclass(frozen=True)
class GraphSnapshot:
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]


@dataclass(frozen=True)
class ForgetWordPlan:
    word: str
    concept_id: int
    canonical_name: str
    word_type: str
    remaining_words: tuple[str, ...]

    @property
    def is_canonical(self) -> bool:
        return self.word == self.canonical_name

    @property
    def is_protected(self) -> bool:
        return self.word_type == "SYSTEM"

    @property
    def replacement_word(self) -> str | None:
        if self.is_canonical and self.remaining_words:
            return self.remaining_words[0]
        return None

    @property
    def removes_concept(self) -> bool:
        return self.is_canonical and not self.remaining_words


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(path))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.initialize()

    def initialize(self) -> None:
        base = Path(__file__).resolve().parent
        self.connection.executescript((base / "schema.sql").read_text(encoding="utf-8"))
        self.connection.executescript((base / "seed.sql").read_text(encoding="utf-8"))

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except Exception:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    @staticmethod
    def _concept(row: sqlite3.Row | None) -> Concept | None:
        if row is None:
            return None
        return Concept(id=row["id"], canonical_name=row["canonical_name"])

    def lookup_word(self, word: str) -> Concept | None:
        row = self.connection.execute(
            """SELECT concepts.id, concepts.canonical_name
               FROM words JOIN concepts ON concepts.id = words.concept_id
               WHERE words.word = ? AND concepts.status = 'ACTIVE'""",
            (word.strip(),),
        ).fetchone()
        return self._concept(row)

    def lookup_concept(self, canonical_name: str) -> Concept | None:
        row = self.connection.execute(
            "SELECT id, canonical_name FROM concepts WHERE canonical_name = ? AND status = 'ACTIVE'",
            (canonical_name.strip(),),
        ).fetchone()
        return self._concept(row)

    def is_reaction_channel_enabled(
        self, guild_id: int | None, channel_id: int
    ) -> bool:
        if guild_id is None:
            return False
        row = self.connection.execute(
            """SELECT enabled FROM reaction_channels
               WHERE guild_id = ? AND channel_id = ?""",
            (guild_id, channel_id),
        ).fetchone()
        return row is not None and bool(row["enabled"])

    def set_reaction_channel(
        self, guild_id: int, channel_id: int, enabled: bool
    ) -> None:
        with self.transaction():
            self.connection.execute(
                """INSERT INTO reaction_channels (guild_id, channel_id, enabled)
                   VALUES (?, ?, ?)
                   ON CONFLICT(guild_id, channel_id) DO UPDATE SET
                       enabled = excluded.enabled,
                       updated_at = CURRENT_TIMESTAMP""",
                (guild_id, channel_id, int(enabled)),
            )

    def get_relation_status(self, subject: str, predicate: str, object_: str) -> str | None:
        subject_concept = self.lookup_word(subject) or self.lookup_concept(subject)
        object_concept = self.lookup_word(object_) or self.lookup_concept(object_)
        if subject_concept is None or object_concept is None:
            return None
        row = self.connection.execute(
            """SELECT status FROM relations
               WHERE subject_id = ? AND predicate = ? AND object_id = ?""",
            (subject_concept.id, predicate, object_concept.id),
        ).fetchone()
        return None if row is None else str(row["status"])

    def active_parent_concepts(self, concept_id: int) -> list[Concept]:
        rows = self.connection.execute(
            """SELECT concepts.id, concepts.canonical_name
               FROM relations JOIN concepts ON concepts.id = relations.object_id
               WHERE relations.subject_id = ? AND relations.predicate = 'IS_A'
                 AND relations.status = 'ACTIVE' AND concepts.status = 'ACTIVE'
               ORDER BY relations.id""",
            (concept_id,),
        ).fetchall()
        return [Concept(id=row["id"], canonical_name=row["canonical_name"]) for row in rows]

    def active_parent_names(self, word: str) -> list[str]:
        concept = self.lookup_word(word)
        if concept is None:
            return []
        return [parent.canonical_name for parent in self.active_parent_concepts(concept.id)]


    def graph_snapshot(self) -> GraphSnapshot:
        concept_rows = self.connection.execute(
            """SELECT id, canonical_name FROM concepts
               WHERE status = 'ACTIVE' ORDER BY id"""
        ).fetchall()
        words_by_concept = {int(row["id"]): [] for row in concept_rows}
        word_rows = self.connection.execute(
            """SELECT words.word, words.concept_id
               FROM words JOIN concepts ON concepts.id = words.concept_id
               WHERE concepts.status = 'ACTIVE' ORDER BY words.id"""
        ).fetchall()
        for row in word_rows:
            words_by_concept[int(row["concept_id"])].append(str(row["word"]))

        edge_rows = self.connection.execute(
            """SELECT relations.subject_id, relations.predicate, relations.object_id
               FROM relations
               JOIN concepts AS subject ON subject.id = relations.subject_id
               JOIN concepts AS object ON object.id = relations.object_id
               WHERE relations.status = 'ACTIVE'
                 AND subject.status = 'ACTIVE' AND object.status = 'ACTIVE'
               ORDER BY relations.id"""
        ).fetchall()
        edges: list[GraphEdge] = []
        related_pairs: set[tuple[int, int]] = set()
        for row in edge_rows:
            subject_id = int(row["subject_id"])
            object_id = int(row["object_id"])
            predicate = str(row["predicate"])
            if predicate == "RELATED_TO":
                pair = tuple(sorted((subject_id, object_id)))
                if pair in related_pairs:
                    continue
                related_pairs.add(pair)
            edges.append(
                GraphEdge(
                    subject_id=subject_id,
                    predicate=predicate,
                    object_id=object_id,
                )
            )
        return GraphSnapshot(
            nodes=tuple(
                GraphNode(
                    id=int(row["id"]),
                    canonical_name=str(row["canonical_name"]),
                    words=tuple(words_by_concept[int(row["id"])]),
                )
                for row in concept_rows
            ),
            edges=tuple(edges),
        )

    def list_vocabulary_entries(self) -> list[VocabularyEntry]:
        rows = self.connection.execute(
            """SELECT words.word, concepts.id, concepts.canonical_name
               FROM words JOIN concepts ON concepts.id = words.concept_id
               WHERE concepts.status = 'ACTIVE'
               ORDER BY words.id"""
        ).fetchall()
        return [
            VocabularyEntry(
                word=row["word"],
                concept=Concept(id=row["id"], canonical_name=row["canonical_name"]),
            )
            for row in rows
        ]

    def load_embeddings(self, model_id: str) -> dict[str, tuple[int, bytes]]:
        rows = self.connection.execute(
            "SELECT word, dimension, vector FROM embeddings WHERE model = ?",
            (model_id,),
        ).fetchall()
        return {
            row["word"]: (int(row["dimension"]), bytes(row["vector"]))
            for row in rows
        }

    def save_embeddings(
        self, model_id: str, embeddings: dict[str, tuple[int, bytes]]
    ) -> None:
        if not embeddings:
            return
        rows = []
        for word, (dimension, vector) in embeddings.items():
            if dimension <= 0 or len(vector) != dimension * 4:
                raise ValueError(f"Invalid embedding for {word!r}")
            rows.append((word, model_id, dimension, vector))
        with self.transaction():
            self.connection.executemany(
                """INSERT INTO embeddings (word, model, dimension, vector)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(word) DO UPDATE SET
                       model = excluded.model,
                       dimension = excluded.dimension,
                       vector = excluded.vector,
                       created_at = CURRENT_TIMESTAMP""",
                rows,
            )

    def _ensure_concept(self, word: str) -> Concept:
        word = word.strip()
        if not word:
            raise ValueError("A concept word cannot be empty")
        existing = self.lookup_word(word)
        if existing is not None:
            return existing
        existing = self.lookup_concept(word)
        if existing is not None:
            self.connection.execute(
                "INSERT INTO words (word, concept_id, word_type) VALUES (?, ?, 'NORMAL')",
                (word, existing.id),
            )
            return existing
        cursor = self.connection.execute(
            "INSERT INTO concepts (canonical_name) VALUES (?)", (word,)
        )
        concept = Concept(id=int(cursor.lastrowid), canonical_name=word)
        self.connection.execute(
            "INSERT INTO words (word, concept_id, word_type) VALUES (?, ?, 'NORMAL')",
            (word, concept.id),
        )
        return concept

    def learn_relation(self, subject: str, predicate: str, object_: str) -> tuple[Concept, Concept]:
        if predicate not in {"IS_A", "SAME_AS", "RELATED_TO"}:
            raise ValueError(f"Unsupported predicate: {predicate}")
        with self.transaction():
            subject_concept = self._ensure_concept(subject)
            object_concept = self._ensure_concept(object_)
            if predicate in {"IS_A", "RELATED_TO"} and subject_concept.id == object_concept.id:
                raise ValueError(f"A concept cannot be {predicate} itself")
            relations = [(subject_concept.id, predicate, object_concept.id)]
            if predicate == "RELATED_TO":
                relations.append((object_concept.id, predicate, subject_concept.id))
            self.connection.executemany(
                """INSERT INTO relations (subject_id, predicate, object_id, status)
                   VALUES (?, ?, ?, 'ACTIVE')
                   ON CONFLICT(subject_id, predicate, object_id)
                   DO UPDATE SET status = 'ACTIVE', confidence = 100""",
                relations,
            )
        return subject_concept, object_concept

    def learn_synonym(self, alias: str, canonical_word: str) -> bool:
        alias = alias.strip()
        canonical_word = canonical_word.strip()
        if not alias or not canonical_word or alias == canonical_word:
            return False
        with self.transaction():
            existing_alias = self.lookup_word(alias)
            canonical = self.lookup_word(canonical_word) or self.lookup_concept(canonical_word)
            if existing_alias is not None:
                return canonical is not None and existing_alias.id == canonical.id
            alias_concept = self.lookup_concept(alias)
            if alias_concept is not None and (
                canonical is None or alias_concept.id != canonical.id
            ):
                return False
            if canonical is None:
                canonical = self._ensure_concept(canonical_word)
            if alias_concept is not None:
                canonical = alias_concept
            self.connection.execute(
                "INSERT INTO words (word, concept_id, word_type) VALUES (?, ?, 'SYNONYM')",
                (alias, canonical.id),
            )
        return True

    def _forget_word_plan(self, word: str) -> ForgetWordPlan | None:
        row = self.connection.execute(
            """SELECT words.word, words.word_type, concepts.id, concepts.canonical_name
               FROM words JOIN concepts ON concepts.id = words.concept_id
               WHERE words.word = ?""",
            (word,),
        ).fetchone()
        if row is None:
            return None
        remaining_rows = self.connection.execute(
            """SELECT word FROM words
               WHERE concept_id = ? AND word != ? ORDER BY id""",
            (row["id"], word),
        ).fetchall()
        return ForgetWordPlan(
            word=str(row["word"]),
            concept_id=int(row["id"]),
            canonical_name=str(row["canonical_name"]),
            word_type=str(row["word_type"]),
            remaining_words=tuple(str(item["word"]) for item in remaining_rows),
        )

    def preview_forget_word(self, word: str) -> ForgetWordPlan | None:
        return self._forget_word_plan(word.strip())

    def forget_word(self, word: str) -> ForgetWordPlan | None:
        word = word.strip()
        if not word:
            return None
        with self.transaction():
            plan = self._forget_word_plan(word)
            if plan is None or plan.is_protected:
                return plan
            if plan.is_canonical and plan.replacement_word is None:
                self.connection.execute(
                    "DELETE FROM relations WHERE subject_id = ? OR object_id = ?",
                    (plan.concept_id, plan.concept_id),
                )
                self.connection.execute(
                    "DELETE FROM words WHERE concept_id = ?", (plan.concept_id,)
                )
                self.connection.execute(
                    "DELETE FROM concepts WHERE id = ?", (plan.concept_id,)
                )
            else:
                self.connection.execute("DELETE FROM words WHERE word = ?", (word,))
                if plan.replacement_word is not None:
                    self.connection.execute(
                        "UPDATE concepts SET canonical_name = ? WHERE id = ?",
                        (plan.replacement_word, plan.concept_id),
                    )
                    self.connection.execute(
                        "UPDATE words SET word_type = 'NORMAL' WHERE word = ?",
                        (plan.replacement_word,),
                    )
            return plan

    def reject_relation(self, subject: str, predicate: str, object_: str) -> bool:
        subject_concept = self.lookup_word(subject) or self.lookup_concept(subject)
        object_concept = self.lookup_word(object_) or self.lookup_concept(object_)
        if subject_concept is None or object_concept is None:
            return False
        with self.transaction():
            if predicate == "RELATED_TO":
                cursor = self.connection.execute(
                    """UPDATE relations SET status = 'REJECTED'
                       WHERE predicate = ? AND status = 'ACTIVE'
                         AND ((subject_id = ? AND object_id = ?)
                              OR (subject_id = ? AND object_id = ?))""",
                    (
                        predicate,
                        subject_concept.id,
                        object_concept.id,
                        object_concept.id,
                        subject_concept.id,
                    ),
                )
            else:
                cursor = self.connection.execute(
                    """UPDATE relations SET status = 'REJECTED'
                       WHERE subject_id = ? AND predicate = ? AND object_id = ?
                         AND status = 'ACTIVE'""",
                    (subject_concept.id, predicate, object_concept.id),
                )
            return cursor.rowcount > 0

    def close(self) -> None:
        self.connection.close()
