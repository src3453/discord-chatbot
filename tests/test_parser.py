import unittest

from nlp.parser import JapaneseParser


class JapaneseParserTests(unittest.TestCase):
    def test_parse_exposes_surface_normalized_form_and_pos(self) -> None:
        tokens = JapaneseParser().parse("猫を飼いたい")

        cat = next(token for token in tokens if token.surface == "猫")
        verb = next(token for token in tokens if token.part_of_speech[0] == "動詞")
        self.assertEqual(cat.normalized, "猫")
        self.assertEqual(cat.dictionary_form, "猫")
        self.assertTrue(cat.is_noun)
        self.assertEqual(verb.dictionary_form, "飼う")


    def test_splits_compound_noun_into_known_word_and_modifier(self) -> None:
        tokens = JapaneseParser().parse("猫好き")
        self.assertEqual([token.surface for token in tokens], ["猫", "好き"])

if __name__ == "__main__":
    unittest.main()
