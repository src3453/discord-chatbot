import unittest

from rules.engine import Intent, RuleEngine


class RuleEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = RuleEngine()

    def test_yes_no_vocabulary_is_normalized_without_matching_sentences(self) -> None:
        self.assertEqual(self.rules.classify_yes_no("そうです。"), Intent.YES)
        self.assertEqual(self.rules.classify_yes_no("違うよ！"), Intent.NO)
        self.assertIsNone(self.rules.classify_yes_no("猫は動物です。"))

    def test_relation_question_and_negative_statement_are_recognized(self) -> None:
        question = self.rules.parse_relation("猫は動物の一種ですか？")
        self.assertEqual((question.subject, question.object, question.is_question), ("猫", "動物", True))

        denial = self.rules.parse_relation("猫は動物ではない")
        self.assertEqual((denial.subject, denial.object, denial.is_negative), ("猫", "動物", True))

    def test_unrelated_predicate_is_not_misread_as_is_a(self) -> None:
        self.assertIsNone(self.rules.parse_relation("猫は魚を食べたい？"))


if __name__ == "__main__":
    unittest.main()
