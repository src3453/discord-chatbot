from __future__ import annotations

from database.database import Concept, Database


class Ontology:
    def __init__(self, database: Database):
        self.database = database

    def lookup(self, word: str) -> Concept | None:
        return self.database.lookup_word(word)

    def relation_status(self, subject: str, predicate: str, object_: str) -> str | None:
        return self.database.get_relation_status(subject, predicate, object_)

    def learn_is_a(self, subject: str, object_: str) -> tuple[Concept, Concept]:
        return self.database.learn_relation(subject, "IS_A", object_)

    def learn_related(self, left: str, right: str) -> tuple[Concept, Concept]:
        return self.database.learn_relation(left, "RELATED_TO", right)

    def learn_synonym(self, alias: str, canonical_word: str) -> bool:
        return self.database.learn_synonym(alias, canonical_word)

    def reject_is_a(self, subject: str, object_: str) -> bool:
        return self.database.reject_relation(subject, "IS_A", object_)

    def direct_parents(self, word: str) -> list[str]:
        return self.database.active_parent_names(word)
