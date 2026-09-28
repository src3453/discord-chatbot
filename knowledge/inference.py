from __future__ import annotations

from database.database import Concept, Database


class InferenceEngine:
    def __init__(self, database: Database):
        self.database = database

    def is_a(self, subject: str | Concept, object_: str | Concept) -> bool:
        return self.check_is_a(subject, object_) is True

    def check_is_a(self, subject: str | Concept, object_: str | Concept) -> bool | None:
        subject_concept = self._resolve(subject)
        object_concept = self._resolve(object_)
        if subject_concept is None or object_concept is None:
            return None
        if subject_concept.id == object_concept.id:
            return True
        if self._reachable(subject_concept.id, object_concept.id):
            return True
        if self.database.get_relation_status(
            subject_concept.canonical_name, "IS_A", object_concept.canonical_name
        ) == "REJECTED":
            return False
        if self._reachable(object_concept.id, subject_concept.id):
            return False
        return None

    def _resolve(self, value: str | Concept) -> Concept | None:
        if isinstance(value, Concept):
            return value
        return self.database.lookup_word(value) or self.database.lookup_concept(value)

    def _reachable(self, start_id: int, target_id: int) -> bool:
        visited = {start_id}
        pending = [start_id]
        while pending:
            current = pending.pop()
            for parent in self.database.active_parent_concepts(current):
                if parent.id == target_id:
                    return True
                if parent.id not in visited:
                    visited.add(parent.id)
                    pending.append(parent.id)
        return False

    def most_specific_parent(self, word: str) -> str | None:
        concept = self.database.lookup_word(word)
        if concept is None:
            return None
        parents = self.database.active_parent_concepts(concept.id)
        return parents[0].canonical_name if parents else None
