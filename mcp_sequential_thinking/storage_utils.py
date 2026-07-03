import json
import logging
import os
from typing import List, Dict, Any
from pathlib import Path
from datetime import datetime
import portalocker

from .models import ThoughtData
from .logging_conf import configure_logging

logger = configure_logging("sequential-thinking.storage-utils")

# Version of the on-disk session/export schema. Version 2 introduces the
# append-only JSONL session format (header record + one thought per line)
# and the top-level "version" field in JSON exports.
SCHEMA_VERSION = 2


def prepare_thoughts_for_serialization(thoughts: List[ThoughtData]) -> List[Dict[str, Any]]:
    """Prepare thoughts for serialization with IDs included.

    Args:
        thoughts: List of thought data objects to prepare

    Returns:
        List[Dict[str, Any]]: List of thought dictionaries with IDs
    """
    return [thought.to_dict(include_id=True) for thought in thoughts]


def save_thoughts_to_file(
    file_path: Path,
    thoughts: List[Dict[str, Any]],
    lock_file: Path,
    metadata: Dict[str, Any] | None = None,
) -> None:
    """Save thoughts to a file with proper locking.

    Args:
        file_path: Path to the file to save
        thoughts: List of thought dictionaries to save
        lock_file: Path to the lock file
        metadata: Optional additional metadata to include
    """
    data = {
        "version": SCHEMA_VERSION,
        "thoughts": thoughts,
        "lastUpdated": datetime.now().isoformat()
    }

    # Add any additional metadata if provided
    if metadata:
        data.update(metadata)

    # Ensure destination directories exist before acquiring the lock.
    file_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file.parent.mkdir(parents=True, exist_ok=True)

    # Use file locking to ensure thread safety when writing
    with portalocker.Lock(lock_file, timeout=10) as _:
        _atomic_write_text(file_path, json.dumps(data, indent=2, ensure_ascii=False))

    logger.debug(f"Saved {len(thoughts)} thoughts to {file_path}")


def _atomic_write_text(file_path: Path, text: str) -> None:
    """Write ``text`` to ``file_path`` atomically.

    Writes to a temp file in the same directory, fsyncs, then ``os.replace()``s
    onto the target. This guarantees the destination is always either the old
    or the new complete state, never a truncated half-write. Callers are
    responsible for holding the appropriate file lock.

    Args:
        file_path: Destination path.
        text: Full file content to write.
    """
    tmp_path = file_path.with_suffix(file_path.suffix + '.tmp')
    with open(tmp_path, 'w', encoding='utf-8') as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, file_path)


def _header_record() -> Dict[str, Any]:
    """Build the header record that starts every JSONL session file."""
    return {"type": "header", "version": SCHEMA_VERSION, "createdAt": datetime.now().isoformat()}


def _dump_record(record: Dict[str, Any]) -> str:
    """Serialize a single JSONL record (compact, UTF-8-friendly)."""
    return json.dumps(record, ensure_ascii=False)


def append_thought_to_jsonl(
    file_path: Path,
    lock_file: Path,
    thought_dict: Dict[str, Any],
) -> None:
    """Append a single thought record to a JSONL session file.

    O(1) per call: the file is opened in append mode, the record is flushed
    and fsynced. If the file does not exist yet, a header record (schema
    version 2) is written first.

    Args:
        file_path: Path to the JSONL session file.
        lock_file: Path to the lock file.
        thought_dict: Serialized thought (as from ``ThoughtData.to_dict``).
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file.parent.mkdir(parents=True, exist_ok=True)

    with portalocker.Lock(lock_file, timeout=10) as _:
        is_new_file = not file_path.exists()
        with open(file_path, 'a', encoding='utf-8') as f:
            if is_new_file:
                f.write(_dump_record(_header_record()) + "\n")
            f.write(_dump_record({"type": "thought", **thought_dict}) + "\n")
            f.flush()
            os.fsync(f.fileno())

    logger.debug(f"Appended thought to {file_path}")


def rewrite_jsonl(
    file_path: Path,
    lock_file: Path,
    thoughts: List[Dict[str, Any]],
) -> None:
    """Atomically rewrite a JSONL session file with the given thoughts.

    Used by ``clear_history`` and ``import_session``, where the whole session
    is replaced. The write is atomic (tmp file + fsync + ``os.replace``).

    Args:
        file_path: Path to the JSONL session file.
        lock_file: Path to the lock file.
        thoughts: Serialized thoughts (as from ``ThoughtData.to_dict``).
    """
    lines = [_dump_record(_header_record())]
    lines.extend(_dump_record({"type": "thought", **t}) for t in thoughts)

    file_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file.parent.mkdir(parents=True, exist_ok=True)

    with portalocker.Lock(lock_file, timeout=10) as _:
        _atomic_write_text(file_path, "\n".join(lines) + "\n")

    logger.debug(f"Rewrote {len(thoughts)} thoughts to {file_path}")


def load_thoughts_from_jsonl(
    file_path: Path,
    lock_file: Path,
    backup_on_corruption: bool = False,
) -> List[ThoughtData]:
    """Load thoughts from a JSONL session file (schema version 2).

    Args:
        file_path: Path to the JSONL session file.
        lock_file: Path to the lock file.
        backup_on_corruption: Recovery behaviour reserved for the server's own
            session file. When True, a corrupt final line (interrupted append)
            is dropped with a warning and the valid prefix is kept; any other
            corruption renames the file to a ``.bak.<timestamp>`` backup and
            returns an empty list. When False, all errors propagate.

    Returns:
        List[ThoughtData]: Loaded thought data objects.

    Raises:
        ValueError: If the file is not a valid version-2 JSONL session file
            (only when ``backup_on_corruption`` is False). This includes
            ``json.JSONDecodeError`` and pydantic validation errors, which are
            ``ValueError`` subclasses.
    """
    if not file_path.exists():
        return []

    try:
        with portalocker.Lock(lock_file, timeout=10) as _, open(file_path, 'r', encoding='utf-8') as f:
            raw_lines = f.read().splitlines()

        # Ignore trailing blank lines.
        while raw_lines and not raw_lines[-1].strip():
            raw_lines.pop()

        if not raw_lines:
            return []

        header = json.loads(raw_lines[0])
        if not isinstance(header, dict) or header.get("type") != "header":
            raise ValueError(
                f"File {file_path} does not start with a header record and is not a "
                "valid session file."
            )
        version = header.get("version")
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported session schema version {version!r} in {file_path}; this "
                f"server supports version {SCHEMA_VERSION}. The file may have been "
                "created by a newer release."
            )

        thoughts: List[ThoughtData] = []
        last_index = len(raw_lines) - 1
        for index, line in enumerate(raw_lines[1:], start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                if backup_on_corruption and index == last_index:
                    # An interrupted append leaves exactly one truncated final
                    # line; the prefix is still a consistent session.
                    logger.warning(
                        f"Dropping truncated final record in {file_path} (interrupted write)"
                    )
                    break
                raise
            if not isinstance(record, dict) or record.get("type") != "thought":
                raise ValueError(
                    f"Unexpected record on line {index + 1} of {file_path}: "
                    "expected a thought record."
                )
            thoughts.append(ThoughtData.from_dict(record))

        logger.debug(f"Loaded {len(thoughts)} thoughts from {file_path}")
        return thoughts

    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error(f"Error loading from {file_path}: {e}")

        if not backup_on_corruption:
            raise

        backup_file = file_path.with_suffix(f".bak.{datetime.now().strftime('%Y%m%d%H%M%S')}")
        file_path.rename(backup_file)
        logger.info(f"Created backup of corrupted file at {backup_file}")
        return []


def load_thoughts_from_file(
    file_path: Path,
    lock_file: Path,
    backup_on_corruption: bool = False,
) -> List[ThoughtData]:
    """Load thoughts from a file with proper locking.

    Args:
        file_path: Path to the file to load
        lock_file: Path to the lock file
        backup_on_corruption: Recovery behaviour reserved for the server's own
            session file. When True, a corrupt or semantically invalid file is
            renamed to a ``.bak.<timestamp>`` backup and an empty list is
            returned (the server stays up). When False (the default, used for
            ``import_session``), any parse/validation error propagates so the
            caller's input file and current state are left untouched.

    Returns:
        List[ThoughtData]: Loaded thought data objects

    Raises:
        json.JSONDecodeError: If the file is not valid JSON (only when
            ``backup_on_corruption`` is False).
        KeyError: If the file doesn't contain valid thought data (only when
            ``backup_on_corruption`` is False).
        ValueError: If the file contains semantically invalid data, e.g. an
            unknown stage or a failed model validation (only when
            ``backup_on_corruption`` is False). Note that ``JSONDecodeError``
            and ``pydantic.ValidationError`` are both ``ValueError`` subclasses.
    """
    if not file_path.exists():
        return []

    try:
        # Use file locking and file handling in a single with statement
        # for cleaner resource management
        with portalocker.Lock(lock_file, timeout=10) as _, open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Legacy (v0.5.x) exports have no "version" field and count as v1.
        version = data.get("version", 1)
        if version not in (1, SCHEMA_VERSION):
            raise ValueError(
                f"Unsupported export schema version {version!r} in {file_path}; this "
                f"server supports versions 1 and {SCHEMA_VERSION}. The file may have "
                "been created by a newer release."
            )

        # A valid session/export file must carry a "thoughts" key. Without this
        # check, importing an arbitrary JSON file would silently load an empty
        # list and wipe the current session.
        if "thoughts" not in data:
            raise KeyError(
                f"File {file_path} does not contain a 'thoughts' key and is not a valid session file."
            )

        # Convert data to ThoughtData objects after file is closed
        thoughts = [ThoughtData.from_dict(thought_dict) for thought_dict in data["thoughts"]]

        logger.debug(f"Loaded {len(thoughts)} thoughts from {file_path}")
        return thoughts

    except (json.JSONDecodeError, KeyError, ValueError) as e:
        # JSONDecodeError and pydantic.ValidationError are ValueError subclasses,
        # so (KeyError, ValueError) covers malformed JSON, missing keys, unknown
        # stages and failed model validation alike.
        logger.error(f"Error loading from {file_path}: {e}")

        if not backup_on_corruption:
            # Import path: never touch the caller's file or our current state.
            raise

        # Recovery path (own session file only): back up the corrupt file and
        # start from an empty session instead of crashing the server.
        backup_file = file_path.with_suffix(f".bak.{datetime.now().strftime('%Y%m%d%H%M%S')}")
        file_path.rename(backup_file)
        logger.info(f"Created backup of corrupted file at {backup_file}")
        return []