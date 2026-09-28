from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass

from knowledge.embeddings import EmbeddingCandidate, EmbeddingError
from knowledge.inference import InferenceEngine
from knowledge.ontology import Ontology
from knowledge.vocabulary import VocabularyManager
from nlp.parser import JapaneseParser, Token
from rules.engine import Intent, RelationUtterance, RuleEngine

logger = logging.getLogger(__name__)


_CANCEL_COMMAND = re.compile(
    r"(?:会話(?:を)?|それを)?(?:やっぱり|もう)?"
    r"(?:キャンセル|cancel|中止|中断|取り消して|取り消し|取り消す|"
    r"やめる|やめて|やめます|やめたい|終了|もういい|やっぱりいい)"
    r"(?:してください|して|します|したい(?:です)?|お願い(?:します)?|"
    r"で|ください|する|です)?"
)


def _is_cancel_command(text: str) -> bool:
    normalized = unicodedata.normalize("NFKC", text).casefold().strip()
    normalized = normalized.strip(" \t\r\n。.!！?？、,")
    return _CANCEL_COMMAND.fullmatch(normalized) is not None


_NO_EMBEDDING_CHOICE_PHRASES = (
    "該当しない",
    "該当しません",
    "該当なし",
    "当てはまらない",
    "当てはまりません",
    "候補にない",
    "候補にはない",
    "候補がない",
    "候補はない",
    "候補はありません",
    "候補と違う",
    "候補が違う",
    "どれも違う",
    "どれも違います",
    "どれでもない",
    "どれにも当てはまらない",
    "どの候補も違う",
    "どの候補も違います",
    "どの候補も当てはまらない",
    "どの候補にも当てはまらない",
    "どの候補も合わない",
    "近いものがない",
    "近いものはない",
    "近いものはありません",
    "近い候補がない",
    "近い候補はありません",
    "全部違う",
    "全部違います",
    "すべて違う",
    "全て違う",
)


def _is_no_embedding_candidate(text: str) -> bool:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = re.sub(r"[\s、。.!！?？]+", "", normalized)
    return any(phrase in normalized for phrase in _NO_EMBEDDING_CHOICE_PHRASES)


@dataclass
class ConversationState:
    status: str
    target: str = ""
    candidate: str = ""
    predicate: str = "IS_A"
    correction: bool = False
    embedding_candidate: bool = False
    choices: tuple[EmbeddingCandidate, ...] = ()


class ConversationManager:
    def __init__(
        self,
        parser: JapaneseParser,
        vocabulary: VocabularyManager,
        ontology: Ontology,
        inference: InferenceEngine,
        rules: RuleEngine,
        embedding_min_similarity: float = 0.45,
    ):
        self.parser = parser
        self.vocabulary = vocabulary
        self.ontology = ontology
        self.inference = inference
        self.rules = rules
        self.embedding_min_similarity = embedding_min_similarity
        self._states: dict[tuple[int | None, int, int], ConversationState] = {}

    def get_state(
        self, guild_id: int | None, channel_id: int, user_id: int
    ) -> ConversationState | None:
        return self._states.get((guild_id, channel_id, user_id))

    async def process_message(
        self, guild_id: int | None, channel_id: int, user_id: int, text: str
    ) -> str:
        key = (guild_id, channel_id, user_id)
        state = self._states.get(key)
        if state is not None and _is_cancel_command(text):
            self._states.pop(key, None)
            return "会話を中断しました。"
        tokens = self.parser.parse(text)
        if state is not None:
            relation = self.rules.parse_relation(text)
            if state.correction and relation is not None:
                self._states.pop(key, None)
                return await self._handle_relation(key, relation)
            return self._handle_state(key, state, tokens, text)
        intent = self.rules.detect_intent(text)
        if intent == Intent.YES:
            return "はい。"
        if intent == Intent.NO:
            return "いいえ。"
        if intent == Intent.RELATION:
            relation = self.rules.parse_relation(text)
            if relation is not None:
                return await self._handle_relation(key, relation)

        unknown = self.vocabulary.first_unknown_noun(tokens)
        if unknown is not None:
            return await self._ask_unknown(key, unknown)

        for token in tokens:
            concept = self.vocabulary.lookup_token(token)
            if concept is None:
                continue
            parent = self.inference.most_specific_parent(token.normalized)
            if parent is None:
                parent = self.inference.most_specific_parent(token.dictionary_form)
            if parent is not None:
                return f"{concept.canonical_name}は{parent}ですね。"
            return f"「{concept.canonical_name}」ですね。"
        return "まだよくわかりません。"

    async def _ask_unknown(
        self, key: tuple[int | None, int, int], unknown: str
    ) -> str:
        search_state = ConversationState(status="EMBEDDING_SEARCH", target=unknown)
        self._states[key] = search_state
        try:
            candidates = await self.vocabulary.find_similar(
                unknown,
                limit=3,
                minimum_similarity=self.embedding_min_similarity,
            )
        except EmbeddingError as error:
            logger.warning("Embedding retrieval unavailable: %s", error)
            candidates = []
        except Exception:
            if self._states.get(key) is search_state:
                self._states.pop(key, None)
            raise
        if self._states.get(key) is not search_state:
            return ""
        if candidates:
            search_state.status = "ASK_EMBEDDING_CHOICE"
            search_state.choices = tuple(candidates)
            logger.info(
                "Embedding candidates for %s: %s",
                unknown,
                ", ".join(candidate.concept.canonical_name for candidate in candidates),
            )
            return self._embedding_choice_prompt(search_state)
        search_state.status = "ASK_DEFINITION"
        logger.info("Unknown word: %s", unknown)
        logger.info("Asking definition: %s", unknown)
        return f"{unknown}って何？"

    def _handle_state(
        self,
        key: tuple[int | None, int, int],
        state: ConversationState,
        tokens: list[Token],
        text: str,
    ) -> str:
        if state.status == "EMBEDDING_SEARCH":
            return "候補を検索中です。少し待ってください。"
        if state.status == "ASK_DEFINITION":
            return self._handle_definition(key, state, tokens, text)
        if state.status == "ASK_EMBEDDING_CHOICE":
            return self._handle_embedding_choice(key, state, tokens, text)
        if state.status == "ASK_CONFIRMATION":
            return self._handle_confirmation(key, state, text)
        if state.status == "ASK_SYNONYM":
            return self._handle_synonym(key, state, text)
        if state.status == "ASK_RELATION":
            return self._handle_relation_answer(key, state, text)
        self._states.pop(key, None)
        return "まだよくわかりません。"

    @staticmethod
    def _embedding_choice_prompt(state: ConversationState) -> str:
        options = "、".join(
            f"{index}. {candidate.concept.canonical_name} ({candidate.similarity:.2f})"
            for index, candidate in enumerate(state.choices, start=1)
        )
        return (
            f"「{state.target}」に近い既知概念候補です（確定ではありません）。該当しない場合は、「該当しない」と答えてください。"
            f"番号か語を選んでください: {options}"
        )

    def _handle_embedding_choice(
        self,
        key: tuple[int | None, int, int],
        state: ConversationState,
        tokens: list[Token],
        text: str,
    ) -> str:
        if (
            self.rules.classify_yes_no(text) == Intent.NO
            or _is_no_embedding_candidate(text)
        ):
            state.status = "ASK_DEFINITION"
            state.choices = ()
            return f"{state.target}って何？"

        choice = unicodedata.normalize("NFKC", text)
        choice = choice.replace(" ", "").replace("　", "").strip("。.!！?？")
        choice_number = choice.removeprefix("候補").removesuffix("番")
        selected = None
        if choice_number.isdecimal():
            index = int(choice_number) - 1
            if 0 <= index < len(state.choices):
                selected = state.choices[index].concept.canonical_name
        if selected is None:
            for candidate in state.choices:
                name = candidate.concept.canonical_name
                if choice == name or any(
                    value == name
                    for token in tokens
                    for value in (token.normalized, token.dictionary_form, token.surface)
                ):
                    selected = name
                    break
        if selected is None:
            return self._embedding_choice_prompt(state)

        state.status = "ASK_SYNONYM"
        state.candidate = selected
        state.embedding_candidate = True
        state.choices = ()
        return f"「{state.target}」と「{selected}」は同じ意味ですか？"

    def _handle_definition(
        self,
        key: tuple[int | None, int, int],
        state: ConversationState,
        tokens: list[Token],
        text: str,
    ) -> str:
        utterance = self.rules.parse_relation(text)
        candidate = None
        if utterance is not None and utterance.subject == state.target:
            candidate = utterance.object
        if candidate is None:
            candidate = self._first_answer_word(tokens, state.target)
        if candidate is None:
            return f"{state.target}について、もう少し教えてください。"
        if candidate == state.target:
            self._states[key] = ConversationState(
                status="ASK_SYNONYM", target=state.target, candidate=candidate
            )
            return f"「{state.target}」は「{candidate}」と同じ意味ですか？"
        self._states[key] = ConversationState(
            status="ASK_CONFIRMATION", target=state.target, candidate=candidate
        )
        logger.info("Proposed relation: %s IS_A %s", state.target, candidate)
        return f"{state.target}は{candidate}の一種ですか？"

    @staticmethod
    def _first_answer_word(tokens: list[Token], target: str) -> str | None:
        for token in tokens:
            if not token.is_noun:
                continue
            if len(token.part_of_speech) > 1 and token.part_of_speech[1] in {"数詞", "代名詞"}:
                continue
            for word in (token.normalized, token.dictionary_form, token.surface):
                word = word.strip()
                if word and word != target:
                    return word
        return None

    def _handle_confirmation(
        self, key: tuple[int | None, int, int], state: ConversationState, text: str
    ) -> str:
        answer = self.rules.classify_yes_no(text)
        if answer == Intent.YES and state.correction:
            self._states.pop(key, None)
            return "わかりました。"
        if answer == Intent.YES:
            if state.predicate == "SAME_AS":
                learned = self.ontology.learn_synonym(state.target, state.candidate)
                if not learned:
                    self._states.pop(key, None)
                    return f"「{state.target}」は別の概念として登録済みです。"
                logger.info("Learned synonym: %s = %s", state.target, state.candidate)
            elif state.predicate == "RELATED_TO":
                self.ontology.learn_related(state.target, state.candidate)
                logger.info(
                    "Learned related terms: %s RELATED_TO %s",
                    state.target,
                    state.candidate,
                )
            else:
                self.ontology.learn_is_a(state.target, state.candidate)
                logger.info("Learned: %s IS_A %s", state.target, state.candidate)
            self._states.pop(key, None)
            return "わかりました。"
        if answer == Intent.NO:
            if state.correction:
                if self.ontology.reject_is_a(state.target, state.candidate):
                    logger.info("Relation rejected: %s IS_A %s", state.target, state.candidate)
                self._states[key] = ConversationState(
                    status="ASK_RELATION", target=state.target, candidate=state.candidate
                )
                return f"では、{state.target}と{state.candidate}はどういう関係ですか？"
            if state.predicate == "RELATED_TO":
                state.status = "ASK_RELATION"
                return f"では、{state.target}と{state.candidate}はどういう関係ですか？"
            if state.embedding_candidate:
                state.status = "ASK_RELATION"
                state.embedding_candidate = False
                return f"では、{state.target}と{state.candidate}はどういう関係ですか？"
            self._states[key] = ConversationState(
                status="ASK_SYNONYM", target=state.target, candidate=state.candidate
            )
            return f"「{state.target}」は「{state.candidate}」と同じ意味ですか？"
        if state.correction:
            return f"{state.target}は{state.candidate}ということで合っていますか？"
        if state.predicate == "SAME_AS":
            return f"「{state.target}」と「{state.candidate}」は同じ意味ですか？"
        if state.predicate == "RELATED_TO":
            return f"「{state.target}」と「{state.candidate}」は似た言葉として関連していますか？"
        return f"{state.target}は{state.candidate}ということで合っていますか？"

    def _handle_synonym(
        self, key: tuple[int | None, int, int], state: ConversationState, text: str
    ) -> str:
        answer = self.rules.classify_yes_no(text)
        if answer == Intent.YES:
            if self.ontology.learn_synonym(state.target, state.candidate):
                logger.info("Learned synonym: %s = %s", state.target, state.candidate)
                self._states.pop(key, None)
                return "わかりました。"
            self._states.pop(key, None)
            return f"「{state.target}」は別の概念として登録済みです。"
        if answer == Intent.NO:
            if state.embedding_candidate:
                state.status = "ASK_CONFIRMATION"
                state.predicate = "IS_A"
                return f"{state.target}は{state.candidate}の一種ですか？"
            self._states[key] = ConversationState(
                status="ASK_RELATION", target=state.target, candidate=state.candidate
            )
            return f"では、{state.target}と{state.candidate}はどういう関係ですか？"
        return f"「{state.target}」は「{state.candidate}」と同じ意味ですか？"

    def _handle_relation_answer(
        self,
        key: tuple[int | None, int, int],
        state: ConversationState,
        text: str,
    ) -> str:
        utterance = self.rules.parse_relation(text)
        if utterance is not None and not utterance.is_question and not utterance.is_negative:
            state.target = utterance.subject
            state.candidate = utterance.object
            state.predicate = "IS_A"
            state.status = "ASK_CONFIRMATION"
            return f"{state.target}は{state.candidate}ということで合っていますか？"
        compact = text.replace(" ", "").replace("　", "").strip("。.!！?？").casefold()
        if compact in {"一種", "一種です", "is_a", "isa", "包含関係"}:
            state.status = "ASK_CONFIRMATION"
            state.predicate = "IS_A"
            return f"{state.target}は{state.candidate}の一種ですか？"
        if compact in {"同じ", "同じ意味", "同義語", "同じ意味です"}:
            state.status = "ASK_CONFIRMATION"
            state.predicate = "SAME_AS"
            return f"「{state.target}」は「{state.candidate}」と同じ意味ですか？"
        if compact in {
            "似てる", "似ている", "似た言葉", "似た言葉です", "似た単語", "類似",
            "関連", "関連語", "関連する", "関連している", "関連してる", "関連がある",
            "関係ある", "関係がある", "related_to", "related",
        }:
            state.status = "ASK_CONFIRMATION"
            state.predicate = "RELATED_TO"
            return f"「{state.target}」と「{state.candidate}」は似た言葉として関連していますか？"
        return (
            f"「一種」「同じ意味」「似た言葉」などで、"
            f"{state.target}と{state.candidate}の関係を教えてください。"
        )

    async def _handle_relation(
        self, key: tuple[int | None, int, int], relation: RelationUtterance
    ) -> str:
        if relation.is_question:
            subject = self.ontology.lookup(relation.subject)
            object_ = self.ontology.lookup(relation.object)
            if subject is None or object_ is None:
                unknown = relation.subject if subject is None else relation.object
                return await self._ask_unknown(key, unknown)
            answer = self.inference.check_is_a(subject, object_)
            if answer is True:
                if self.ontology.relation_status(relation.subject, "IS_A", relation.object) == "ACTIVE":
                    self._states[key] = ConversationState(
                        status="ASK_CONFIRMATION",
                        target=relation.subject,
                        candidate=relation.object,
                        correction=True,
                    )
                return "はい。"
            if answer is False:
                return "いいえ。"
            return "まだわかりません。"

        if relation.is_negative:
            if self.ontology.reject_is_a(relation.subject, relation.object):
                logger.info("Relation rejected: %s IS_A %s", relation.subject, relation.object)
                self._states[key] = ConversationState(
                    status="ASK_RELATION", target=relation.subject, candidate=relation.object
                )
                return f"では、{relation.subject}と{relation.object}はどういう関係ですか？"
            return "その関係はまだ学習していません。"

        if self.ontology.relation_status(relation.subject, "IS_A", relation.object) == "ACTIVE":
            return "わかりました。"
        self._states[key] = ConversationState(
            status="ASK_CONFIRMATION", target=relation.subject, candidate=relation.object
        )
        return f"{relation.subject}は{relation.object}ということで合っていますか？"
