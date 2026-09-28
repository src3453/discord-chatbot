from __future__ import annotations

import argparse
import logging
from pathlib import Path

from bot.conversation import ConversationManager
from bot.discord_bot import create_discord_client
from config import load_settings
from database.database import Database
from knowledge.embeddings import EmbeddingIndex, LMStudioEmbeddings
from knowledge.graph import GraphRenderError, render_knowledge_graph
from knowledge.inference import InferenceEngine
from knowledge.ontology import Ontology
from knowledge.vocabulary import VocabularyManager
from nlp.parser import JapaneseParser
from rules.engine import RuleEngine


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Discord knowledge bot")
    subcommands = parser.add_subparsers(dest="command")
    graph_parser = subcommands.add_parser(
        "graph", help="render the SQLite knowledge graph as a PNG"
    )
    graph_parser.add_argument(
        "--output", type=Path, default=Path("knowledge_graph.png")
    )
    return parser


def main() -> None:
    arguments = _argument_parser().parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    settings = load_settings()

    if arguments.command == "graph":
        database = Database(settings.database_path)
        try:
            try:
                image = render_knowledge_graph(database.graph_snapshot())
            except GraphRenderError as error:
                raise SystemExit(f"Could not render knowledge graph: {error}") from error
            arguments.output.parent.mkdir(parents=True, exist_ok=True)
            arguments.output.write_bytes(image)
            print(f"Knowledge graph written to {arguments.output}")
        finally:
            database.close()
        return

    if not settings.discord_token:
        raise SystemExit("Set DISCORD_BOT_TOKEN in .env before starting the bot.")

    database = Database(settings.database_path)
    try:
        parser = JapaneseParser()
        ontology = Ontology(database)
        embedding_provider = LMStudioEmbeddings(
            base_url=settings.lm_studio_base_url,
            model_id=settings.embedding_model_id,
            api_key=settings.lm_studio_api_key,
        )
        embedding_index = EmbeddingIndex(database, embedding_provider)
        conversation = ConversationManager(
            parser=parser,
            vocabulary=VocabularyManager(database, embedding_index),
            ontology=ontology,
            inference=InferenceEngine(database),
            rules=RuleEngine(),
            embedding_min_similarity=settings.embedding_min_similarity,
        )
        client = create_discord_client(conversation, database)
        client.run(settings.discord_token)
    finally:
        database.close()


if __name__ == "__main__":
    main()
