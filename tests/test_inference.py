from __future__ import annotations

import unittest

from database.database import Database
from knowledge.inference import InferenceEngine


class InferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = Database(":memory:")
        self.inference = InferenceEngine(self.database)

    def tearDown(self) -> None:
        self.database.close()

    def test_is_a_uses_transitive_paths_and_reverse_hierarchy(self) -> None:
        self.database.learn_relation("猫", "IS_A", "動物")
        self.assertIs(self.inference.check_is_a("猫", "存在"), True)
        self.assertIs(self.inference.check_is_a("存在", "猫"), False)

    def test_cycle_search_terminates_and_does_not_invent_a_path(self) -> None:
        self.database.learn_relation("輪A", "IS_A", "輪B")
        self.database.learn_relation("輪B", "IS_A", "輪A")
        self.database.learn_relation("別概念", "IS_A", "物")
        self.assertIsNone(self.inference.check_is_a("輪A", "別概念"))


if __name__ == "__main__":
    unittest.main()
