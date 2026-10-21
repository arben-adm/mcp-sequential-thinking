import json
import os
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from typing import Any

import portalocker

from .logging_conf import configure_logging
from .models import ThoughtData

logger = configure_logging("sequential-thinking.storage-utils")

# Version of the on-disk session/export schema. Version 2 introduces the
# append-only JSONL session format (header record + one thought per line)
# and the top-level "version" field in JSON exports.
SCHEMA_VERSION = 2


def prepare_thoughts_for_serialization(thoughts: list[ThoughtData]) -> list[dict[str, Any]]:
    """Prepare thoughts for serialization with IDs included.

    Args:
        thoughts: List of thought data objects to prepare

    Returns:
        List[Dict[str, Any]]: List of thought dictionaries with IDs
    """
    return [thought.to_dict(include_id=True) for thought in thoughts]


def save_thoughts_to_file(
    file_path: Path,
    thoughts: list[dict[str, Any]],
    lock_file: Path,
    metadata: dict[str, Any] | None = None,
    timeout: float = 10.0,
) -> None:
    """Save thoughts to a file with proper locking.

    Args:
        file_path: Path to the file to save
        thoughts: List of thought dictionaries to save
        lock_file: Path to the lock file
        metadata: Optional additional metadata to include
        timeout: Seconds to wait for the lock before raising
            ``portalocker.exceptions.BaseLockException`` (B7).
    """
    data = {
        "version": SCHEMA_VERSION,
        "thoughts": thoughts,
        "lastUpdated": datetime.now().isoformat(),
    }

    # Add any additional metadata if provided
    if metadata:
        data.update(metadata)

    serialized = json.dumps(data, indent=2, ensure_ascii=False)
    if len(thoughts) > MAX_IMPORT_RECORDS or len(serialized.encode("utf-8")) > MAX_IMPORT_BYTES:
        raise ValueError("Export exceeds format limits; use a database backup")

    # Ensure destination directories exist before acquiring the lock.
    file_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file.parent.mkdir(parents=True, exist_ok=True)

    # Use file locking to ensure thread safety when writing
    with portalocker.Lock(lock_file, timeout=timeout) as _:
        _atomic_write_text(file_path, serialized)

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
    tmp_path = file_path.with_suffix(file_path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, file_path)


def _header_record() -> dict[str, Any]:
    """Build the header record that starts every JSONL session file."""
    return {"type": "header", "version": SCHEMA_VERSION, "createdAt": datetime.now().isoformat()}


def _dump_record(record: dict[str, Any]) -> str:
    """Serialize a single JSONL record (compact, UTF-8-friendly)."""
    return json.dumps(record, ensure_ascii=False)


def append_thought_to_jsonl(
    file_path: Path,
    lock_file: Path,
    thought_dict: dict[str, Any],
    timeout: float = 10.0,
) -> None:
    """Append a single thought record to a JSONL session file.

    O(1) per call: the file is opened in append mode, the record is flushed
    and fsynced. If the file does not exist yet, a header record (schema
    version 2) is written first.

    Args:
        file_path: Path to the JSONL session file.
        lock_file: Path to the lock file.
        thought_dict: Serialized thought (as from ``ThoughtData.to_dict``).
        timeout: Seconds to wait for the lock before raising
            ``portalocker.exceptions.BaseLockException`` (B7).
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file.parent.mkdir(parents=True, exist_ok=True)

    with portalocker.Lock(lock_file, timeout=timeout) as _:
        is_new_file = not file_path.exists() or file_path.stat().st_size == 0
        with open(file_path, "a", encoding="utf-8", newline="") as f:
            if is_new_file:
                f.write(_dump_record(_header_record()) + "\n")
            f.write(_dump_record({"type": "thought", **thought_dict}) + "\n")
            f.flush()
            os.fsync(f.fileno())

    logger.debug(f"Appended thought to {file_path}")


def rewrite_jsonl(
    file_path: Path,
    lock_file: Path,
    thoughts: list[dict[str, Any]],
    timeout: float = 10.0,
    *,
    _already_locked: bool = False,
) -> None:
    """Atomically rewrite a JSONL session file with the given thoughts.

    Used by ``clear_history`` and ``import_session``, where the whole session
    is replaced. The write is atomic (tmp file + fsync + ``os.replace``).

    Args:
        file_path: Path to the JSONL session file.
        lock_file: Path to the lock file.
        thoughts: Serialized thoughts (as from ``ThoughtData.to_dict``).
        timeout: Seconds to wait for the lock before raising
            ``portalocker.exceptions.BaseLockException`` (B7).
    """
    lines = [_dump_record(_header_record())]
    lines.extend(_dump_record({"type": "thought", **t}) for t in thoughts)

    file_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file.parent.mkdir(parents=True, exist_ok=True)

    with nullcontext() if _already_locked else portalocker.Lock(lock_file, timeout=timeout) as _:
        _atomic_write_text(file_path, "\n".join(lines) + "\n")

    logger.debug(f"Rewrote {len(thoughts)} thoughts to {file_path}")


class UnsupportedSchemaVersion(ValueError):
    """The original must remain untouched; use a compatible server or restore."""


MAX_IMPORT_BYTES = 16 * 1024 * 1024
MAX_IMPORT_RECORDS = 10000


def validate_thoughts(thoughts: list[ThoughtData]) -> None:
    """Shared integrity rules. Never deduplicate, renumber, or replace IDs."""
    ids = set()
    positions = set()
    forks: dict[str, int | None] = {}
    prior: list[ThoughtData] = []
    for thought in thoughts:
        if thought.id in ids:
            raise ValueError("Duplicate thought UUID")
        position = (thought.branch_id, thought.thought_number)
        if position in positions:
            raise ValueError("Duplicate thought position")
        if thought.branch_id is not None:
            if (
                thought.branch_id in forks
                and forks[thought.branch_id] != thought.branch_from_thought
            ):
                raise ValueError("Branch origin cannot change")
            forks[thought.branch_id] = thought.branch_from_thought
        for number, branch in [
            (thought.revises_thought_number, thought.branch_id),
            (thought.branch_from_thought, None),
        ]:
            if number is not None:
                targets = [t for t in prior if t.thought_number == number and t.branch_id == branch]
                if len(targets) != 1:
                    raise ValueError(
                        "Invalid reference: expected one earlier target in reference scope"
                    )
        ids.add(thought.id)
        positions.add(position)
        prior.append(thought)


def _incomplete_tail(line: bytes, error: UnicodeDecodeError | json.JSONDecodeError) -> bool:
    """Conservatively distinguish truncation from malformed complete syntax."""
    if isinstance(error, UnicodeDecodeError):
        if error.reason != "unexpected end of data" or error.end != len(line):
            return False
        line = line[: error.start]
        try:
            json.loads(line)
        except json.JSONDecodeError as prefix_error:
            return _incomplete_tail(line, prefix_error)
        return False
    decoded = line.decode("utf-8")
    return error.msg.startswith("Unterminated string") or error.pos >= len(decoded.rstrip())


def load_thoughts_from_jsonl(
    file_path: Path,
    lock_file: Path,
    backup_on_corruption: bool = False,
    timeout: float = 10.0,
) -> list[ThoughtData]:
    """Validate under one lock; repair only an unterminated malformed tail.

    Corruption in complete records and unsupported versions stop startup without
    changing the source. A repair retains an exact backup of the original bytes.
    """
    with portalocker.Lock(lock_file, timeout=timeout):
        if not file_path.exists():
            return []
        raw = file_path.read_bytes()
        if not raw:
            return []
        lines = raw.splitlines(keepends=True)
        header = json.loads(lines[0])
        if not isinstance(header, dict) or header.get("type") != "header":
            raise ValueError("Invalid session header; restore required")
        if type(header.get("version")) is not int or header["version"] != SCHEMA_VERSION:
            raise UnsupportedSchemaVersion(
                "Unsupported session version; use compatible server or restore"
            )
        thoughts: list[ThoughtData] = []
        missing_ids = False
        offset = len(lines[0])
        repair_at: int | None = None
        for index, line in enumerate(lines[1:], start=1):
            if not line.strip():
                offset += len(line)
                continue
            try:
                record = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                if (
                    backup_on_corruption
                    and index == len(lines) - 1
                    and not line.endswith(b"\n")
                    and _incomplete_tail(line, error)
                ):
                    repair_at = offset
                    break
                raise ValueError("Corrupt complete session record; restore required") from None
            if not isinstance(record, dict) or record.get("type") != "thought":
                raise ValueError("Invalid session record; restore required")
            missing_ids = missing_ids or "id" not in record
            thoughts.append(ThoughtData.from_dict(record))
            offset += len(line)
        validate_thoughts(thoughts)
        if repair_at is not None or (missing_ids and backup_on_corruption):
            from uuid import uuid4

            backup = file_path.with_name(file_path.name + ".bak." + str(uuid4()))
            with backup.open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            if missing_ids:
                repaired = [_dump_record(header)]
                repaired.extend(
                    _dump_record({"type": "thought", **t.to_dict(True)}) for t in thoughts
                )
                _atomic_write_text(file_path, "\n".join(repaired) + "\n")
            else:
                _atomic_write_text(file_path, raw[:repair_at].decode("utf-8"))
        elif backup_on_corruption and not raw.endswith(b"\n"):
            # Complete JSON without a final newline must not concatenate with an append.
            _atomic_write_text(file_path, raw.decode("utf-8") + "\n")
        return thoughts


def load_thoughts_from_file(
    file_path: Path,
    lock_file: Path,
    backup_on_corruption: bool = False,
    timeout: float = 10.0,
    *,
    _already_locked: bool = False,
) -> list[ThoughtData]:
    """Validate a bounded v1/v2 export completely before any replacement.

    The legacy backup_on_corruption argument remains accepted, but corrupt
    originals are never silently replaced with empty writable sessions.
    """
    with nullcontext() if _already_locked else portalocker.Lock(lock_file, timeout=timeout):
        if not file_path.exists():
            return []
        with file_path.open("rb") as stream:
            raw = stream.read(MAX_IMPORT_BYTES + 1)
        if len(raw) > MAX_IMPORT_BYTES:
            raise ValueError("Import exceeds byte limit")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Import root must be an object")
        if type(data.get("version", 1)) is not int or data.get("version", 1) not in (
            1,
            SCHEMA_VERSION,
        ):
            raise UnsupportedSchemaVersion("Unsupported export schema version")
        if set(data) - {"version", "thoughts", "lastUpdated", "exportedAt", "metadata"}:
            raise ValueError("Unknown export envelope fields")
        if "metadata" in data and not isinstance(data["metadata"], dict):
            raise ValueError("Export metadata must be an object")
        if "thoughts" not in data:
            raise KeyError("Import requires thoughts")
        records = data["thoughts"]
        if not isinstance(records, list):
            raise ValueError("thoughts must be a list")
        if len(records) > MAX_IMPORT_RECORDS:
            raise ValueError("Import exceeds record limit")
        if any(not isinstance(record, dict) for record in records):
            raise ValueError("Every thought must be an object")
        thoughts = [ThoughtData.from_dict(record) for record in records]
        validate_thoughts(thoughts)
        return thoughts
