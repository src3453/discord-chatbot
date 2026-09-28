from __future__ import annotations

import unittest
from io import BytesIO

from PIL import Image

from database.database import Database, GraphSnapshot
from knowledge.graph import render_knowledge_graph


class GraphRenderTests(unittest.TestCase):
    def test_database_network_renders_as_a_readable_png(self) -> None:
        database = Database(":memory:")
        try:
            database.learn_relation("猫", "IS_A", "動物")
            database.learn_synonym("ねこ", "猫")
            png = render_knowledge_graph(database.graph_snapshot())
        finally:
            database.close()

        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        image = Image.open(BytesIO(png))
        image.load()
        self.assertEqual(image.format, "PNG")
        self.assertGreater(image.width, 700)
        self.assertGreater(image.height, 300)

    def test_empty_snapshot_still_produces_an_image(self) -> None:
        png = render_knowledge_graph(GraphSnapshot(nodes=(), edges=()))
        image = Image.open(BytesIO(png))
        self.assertEqual(image.format, "PNG")


if __name__ == "__main__":
    unittest.main()
