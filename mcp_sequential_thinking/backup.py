"""Consistent SQLite snapshot and restore into a new storage directory."""

from __future__ import annotations

import argparse
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

import portalocker

from .sessions import _SCHEMA, SessionError, SessionRepository


def validate_snapshot(connection: sqlite3.Connection) -> None:
    if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
        raise SessionError("UNSUPPORTED_SCHEMA", "Use a compatible server for this snapshot")
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise SessionError("STORAGE_ERROR", "Snapshot integrity check failed")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise SessionError("INVALID_REFERENCE", "Snapshot contains invalid references")

    def normalize(sql: str) -> str:
        return " ".join(sql.strip().split()).lower()

    expected_schema = {normalize(sql) for sql in _SCHEMA.split(";") if sql.strip()}
    actual_schema = {
        normalize(row[0])
        for row in connection.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL")
    }
    if actual_schema != expected_schema:
        raise SessionError(
            "UNSUPPORTED_SCHEMA", "Snapshot schema differs from the supported schema"
        )
    required = {"sessions", "branches", "steps", "requests", "migrations"}
    actual = {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if actual != required:
        raise SessionError("UNSUPPORTED_SCHEMA", "Unexpected snapshot tables")
    # New IDs can only refer to existing earlier rows. This catches edits that
    # introduce cycles even when SQLite's existence constraints still hold.
    if connection.execute(
        "SELECT 1 FROM steps s JOIN steps p ON p.id=s.parent_id OR p.id=s.supersedes_id "
        "WHERE p.rowid>=s.rowid LIMIT 1"
    ).fetchone():
        raise SessionError("INVALID_REFERENCE", "Snapshot contains a nonhistorical reference")


def _snapshot(source: sqlite3.Connection, destination: Path) -> None:
    """Install a verified complete file without ever overwriting an existing file."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError("Snapshot destination already exists")
    descriptor, name = tempfile.mkstemp(
        prefix=".snapshot-", suffix=".sqlite3", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(name)
    try:
        with closing(sqlite3.connect(temporary)) as target:
            source.backup(target)
            validate_snapshot(target)
            target.execute("PRAGMA journal_mode=DELETE")
        with temporary.open("r+b") as stream:
            os.fsync(stream.fileno())
        os.link(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def create_snapshot(storage_dir: Path, destination: Path) -> None:
    database = storage_dir / "worklog.sqlite3"
    if not database.is_file():
        raise FileNotFoundError("No session database in storage directory")
    source = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        _snapshot(source, destination)
    finally:
        source.close()


def restore_snapshot(source_path: Path, storage_dir: Path) -> None:
    """Restore to a fresh directory; no clobbering a current database or JSONL."""
    if not source_path.is_file():
        raise FileNotFoundError("Snapshot does not exist")
    storage_dir.mkdir(parents=True, exist_ok=True)
    with portalocker.Lock(storage_dir / "startup.lock", timeout=5):
        if any(
            (storage_dir / name).exists()
            for name in (
                "worklog.sqlite3",
                "worklog.sqlite3-wal",
                "worklog.sqlite3-shm",
                "current_session.json",
                "current_session.jsonl",
            )
        ):
            raise FileExistsError("Restore requires a fresh storage directory")
        source = sqlite3.connect(source_path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            validate_snapshot(source)
            _snapshot(source, storage_dir / "worklog.sqlite3")
        finally:
            source.close()
    repository = SessionRepository(str(storage_dir))
    repository.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["create", "restore"])
    parser.add_argument("storage_dir", type=Path)
    parser.add_argument("snapshot", type=Path)
    args = parser.parse_args()
    try:
        if args.operation == "create":
            create_snapshot(args.storage_dir.resolve(), args.snapshot.resolve())
        else:
            restore_snapshot(args.snapshot.resolve(), args.storage_dir.resolve())
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(
            1, f"Snapshot operation failed ({type(error).__name__}); originals preserved.\n"
        )


if __name__ == "__main__":
    main()
