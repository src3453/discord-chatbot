from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sudachipy import Dictionary, SplitMode


@dataclass(frozen=True)
class Token:
    surface: str
    normalized: str
    dictionary_form: str
    part_of_speech: tuple[str, ...]

    @property
    def is_noun(self) -> bool:
        return bool(self.part_of_speech) and self.part_of_speech[0] == "名詞"


class JapaneseParser:
    def __init__(self, tokenizer: Any | None = None):
        self.tokenizer = tokenizer if tokenizer is not None else Dictionary().create()

    def parse(self, text: str) -> list[Token]:
        return [
            Token(
                surface=morpheme.surface(),
                normalized=morpheme.normalized_form(),
                dictionary_form=morpheme.dictionary_form(),
                part_of_speech=tuple(morpheme.part_of_speech()),
            )
            for morpheme in self.tokenizer.tokenize(text, SplitMode.A)
        ]
