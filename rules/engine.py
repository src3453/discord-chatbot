from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum



class Intent(str, Enum):
    YES = "YES"
    NO = "NO"
    RELATION = "RELATION"
    OTHER = "OTHER"


@dataclass(frozen=True)
class RelationUtterance:
    subject: str
    object: str
    is_question: bool
    is_negative: bool


class RuleEngine:
    YES_WORDS = {
        "はい", "うん", "そう", "そうです", "正しい", "合ってる", "その通り", "ok",
    }
    NO_WORDS = {
        "いいえ", "いや", "違う", "違います", "違うよ", "そうじゃない",
    }
    NEGATION_SUFFIXES = (
        "ではありません", "じゃありません", "ではないです", "じゃないです",
        "ではない", "じゃない",
    )

    def classify_yes_no(self, text: str) -> Intent | None:
        value = unicodedata.normalize("NFKC", text).strip().casefold()
        value = re.sub(r"[\s、。.!！?？]+", "", value)
        if value in self.YES_WORDS:
            return Intent.YES
        if value in self.NO_WORDS:
            return Intent.NO
        return None

    def detect_intent(self, text: str) -> Intent:
        answer = self.classify_yes_no(text)
        if answer is not None:
            return answer
        return Intent.RELATION if self.parse_relation(text) is not None else Intent.OTHER

    def parse_relation(self, text: str) -> RelationUtterance | None:
        value = unicodedata.normalize("NFKC", text).strip()
        is_question = value.endswith(("?", "？")) or value.endswith(("ですか", "ますか"))
        value = value.rstrip(" \t\r\n。.!！?？")
        if not value or "は" not in value:
            return None
        subject, right = value.split("は", 1)
        subject = subject.strip()
        right = right.strip()
        if not subject or not right:
            return None

        if right.endswith("ですか") or right.endswith("ますか"):
            is_question = True
            right = right[:-3] if right.endswith("ですか") else right[:-3]
        elif right.endswith("か"):
            is_question = True
            right = right[:-1]

        is_negative = False
        for suffix in self.NEGATION_SUFFIXES:
            if right.endswith(suffix):
                right = right[:-len(suffix)]
                is_negative = True
                break

        for suffix in ("の一種です", "の一種", "一種です", "一種", "ということです", "です", "だ"):
            if right.endswith(suffix):
                right = right[:-len(suffix)]
                break
        object_ = right.strip()
        if "は" in subject or "は" in object_:
            return None
        if re.search(r"(?:を|が|に|へ|と|で)[ぁ-ゖァ-ヺ一-龯]", object_):
            return None
        if not object_ or any(char.isspace() for char in subject + object_):
            return None
        if not re.fullmatch(r"[\wー・]+", subject, flags=re.UNICODE):
            return None
        if not re.fullmatch(r"[\wー・]+", object_, flags=re.UNICODE):
            return None
        return RelationUtterance(
            subject=subject,
            object=object_,
            is_question=is_question,
            is_negative=is_negative,
        )
