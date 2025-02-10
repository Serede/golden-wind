#!/usr/bin/env python3

import logging
import random
import string
import sys
import tempfile
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import AsyncGenerator, Dict, Generator, List

import fitz
import yaml
from telegram import Message, Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__file__)


def random_string(length: int) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(random.choices(alphabet, k=length))


class App:
    _actions_file = Path(".actions.yaml")
    _token_file = Path(".token.txt")
    _user_id_file = Path(".user_id.txt")

    @property
    def _token(self) -> str:
        return self._token_file.read_text()

    @property
    def _user_id(self) -> int:
        return int(self._user_id_file.read_text())

    @property
    def filter(self) -> filters.BaseFilter:
        return filters.User(self._user_id)

    @property
    def actions(self) -> List[Dict[str, str]]:
        with open(self._actions_file) as actions_file:
            return yaml.safe_load(actions_file)

    @asynccontextmanager
    async def download_document(self, message: Message) -> AsyncGenerator[Path]:
        document = await self._app.bot.get_file(message.document.file_id)

        with tempfile.TemporaryDirectory() as temp_dir:
            location = Path(temp_dir) / message.document.file_name
            await document.download_to_drive(location)
            yield location

    @contextmanager
    def process_document(self, path: Path) -> Generator[Path]:
        with tempfile.TemporaryDirectory() as temp_dir:
            hash = random_string(8)
            location = Path(temp_dir) / f"{path.stem}-{hash}.{path.suffix}"

            with fitz.open(path) as document:
                document.select([0])
                page = document[0]

                for entry in self.actions:
                    text = entry.get("replace")
                    new_text = entry.get("with")
                    if not text or not new_text:
                        continue

                    found = page.search_for(text)
                    logger.info(f"Found {len(found)} occurrences of {text}")

                    for i, rect in enumerate(found):
                        # First, redact (remove) the original text
                        page.add_redact_annot(rect)
                        page.apply_redactions()

                        # Insert the new text at the adjusted position
                        page.insert_text(
                            fitz.Point(rect.x0, rect.y1),  # Same point
                            text,
                            fontsize=8,
                            fontname="helv",  # Helvetica
                            color=(0, 0, 0),  # Black
                        )

                        logger.info(
                            f"Replaced instance {i + 1} of {text} with {new_text}."
                        )

                document.save(location)

            yield location

    async def handler(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.message.chat_id
        document = update.message.document

        # Process only PDF documents
        if not document or not document.file_name.endswith(".pdf"):
            return

        # Download document, process it and send it back
        async with self.download_document(update.message) as original:
            with self.process_document(original) as copy:
                await self._app.bot.send_document(chat_id=chat_id, document=copy)

    def __init__(self) -> None:
        self._app = ApplicationBuilder().token(self._token).build()
        self._app.add_handler(
            MessageHandler(filters=self.filter, callback=self.handler)
        )

    def start(self) -> None:
        self._app.run_polling()


def main() -> int:
    App().start()


if __name__ == "__main__":
    sys.exit(main())
