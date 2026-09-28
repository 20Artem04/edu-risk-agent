"""Общие функции безопасной работы с SQLite."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from src.config import DB_PATH


def connect(db_path: Path | str = DB_PATH, read_only: bool = False) -> sqlite3.Connection:
    """Открыть соединение с включёнными внешними ключами и Row-объектами."""
    db_path = Path(db_path)
    if read_only:
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=20)
    else:
        connection = sqlite3.connect(db_path, timeout=20)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    if not read_only:
        connection.execute("PRAGMA journal_mode = WAL")
    return connection


@contextmanager
def transaction(db_path: Path | str = DB_PATH) -> Iterator[sqlite3.Connection]:
    """Контекст транзакции с commit/rollback."""
    connection = connect(db_path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
