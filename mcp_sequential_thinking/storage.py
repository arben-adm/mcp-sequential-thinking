import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import portalocker

from .logging_conf import configure_logging
from .models import ThoughtData, ThoughtStage
from .storage_utils import (
    append_thought_to_jsonl,
    load_thoughts_from_file,
    load_thoughts_from_jsonl,
    prepare_thoughts_for_serialization,
    rewrite_jsonl,
    save_thoughts_to_file,
    validate_thoughts,
)

logger = configure_logging("sequential-thinking.storage")


class DuplicateThoughtNumberError(ValueError):
    """Raised by :meth:`ThoughtStorage.add_thought` when ``thought_number``
    collides with an existing thought on the same line (B1)."""

    def __init__(self, thought_number: int, branch_id: str | None, existing: ThoughtData):
        self.thought_number = thought_number
        self.branch_id = branch_id
        self.existing = existing
        line = "mainline" if branch_id is None else f"branch '{branch_id}'"
        snippet = existing.thought[:60] + ("..." if len(existing.thought) > 60 else "")
        super().__init__(
            f"thought_number {thought_number} is already used on the {line} "
            f'(existing thought: "{snippet}")'
        )


class ThoughtStorage:
    """Storage manager for thought data."""

    def __init__(self, storage_dir: str | None = None, lock_timeout: float = 10.0):
        """Initialize the storage manager.

        Args:
            storage_dir: Directory to store thought data files. If None, uses a default directory.
            lock_timeout: Seconds to wait for the file lock before giving up
                (B7). Callers translate the resulting
                ``portalocker.exceptions.BaseLockException`` into a clear
                protocol error instead of hanging indefinitely. Lowered in
                tests to keep a stale-lock regression test fast.
        """
        self.lock_timeout = lock_timeout
        if storage_dir is None:
            # Use user's home directory by default
            home_dir = Path.home()
            self.storage_dir = home_dir / ".mcp_sequential_thinking"
        else:
            self.storage_dir = Path(storage_dir)

        # Create storage directory if it doesn't exist
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # Default session file (schema v2, append-only JSONL). The legacy v1
        # JSON file is only read once for migration.
        self.current_session_file = self.storage_dir / "current_session.jsonl"
        self.legacy_session_file = self.storage_dir / "current_session.json"
        self.lock_file = self.storage_dir / "current_session.lock"

        # Exports/imports are confined to a dedicated subdirectory so an export
        # can never clobber the session file (or its lock file). Created lazily
        # by export_session.
        self.export_dir = self.storage_dir / "exports"

        # Thread safety
        self._lock = threading.RLock()
        self.thought_history: list[ThoughtData] = []

        # Load existing session if available
        self.state_lock_file = self.storage_dir / "state.lock"
        with self._lock, portalocker.Lock(self.state_lock_file, timeout=self.lock_timeout):
            self._load_session()

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        """Serialize reload/validation/write across threads and processes.

        state.lock is distinct from the record-file lock. On uncertain writes,
        reload before exposing RAM; if that fails, every subsequent operation
        must retry validation before it can write. No cached state is authoritative.
        """
        with self._lock, portalocker.Lock(self.state_lock_file, timeout=self.lock_timeout):
            self._load_session()
            try:
                yield
            except OSError:
                self._load_session()
                raise

    def record_thought(
        self, *, strict_stages: bool = False, **fields: Any
    ) -> tuple[ThoughtData, list[ThoughtData], list[str]]:
        """Allocate, validate policy and persist in one serialized operation."""
        from .analysis import ThoughtAnalyzer

        with self._transaction():
            if fields.get("thought_number") is None:
                fields["thought_number"] = self.next_thought_number(
                    fields.get("branch_id"), fields.get("branch_from_thought")
                )
            thought = ThoughtData(**fields)
            issue = ThoughtAnalyzer.detect_stage_transition_issue(thought, self.thought_history)
            if issue and strict_stages:
                raise ValueError(issue)
            self._append_validated(thought)
            return (
                thought,
                [t.model_copy(deep=True) for t in self.thought_history],
                [issue] if issue else [],
            )

    @staticmethod
    def _ensure_within(base: Path, candidate: str) -> Path:
        """Resolve ``candidate`` and ensure it stays inside ``base``.

        Confines model-controlled export/import paths to the storage directory
        so a path like ``/etc/passwd`` or ``../../foo`` cannot escape it
        (CWE-22 / CWE-73).

        Args:
            base: The directory the path must stay within (e.g. storage_dir).
            candidate: The caller-supplied path (may be absolute or relative).

        Returns:
            Path: The resolved, contained path (safe to open).

        Raises:
            ValueError: If the resolved path is outside ``base``.
        """
        base_r = base.resolve()
        candidate_path = Path(candidate)
        if candidate_path.is_absolute():
            resolved = candidate_path.resolve()
        else:
            resolved = (base_r / candidate_path).resolve()

        try:
            resolved.relative_to(base_r)
        except ValueError:
            # Log the full resolved base server-side, but keep it out of the
            # client-facing message (it would leak the user's home directory).
            logger.error(f"Rejected path '{candidate}': resolves outside '{base_r}'")
            raise ValueError(
                f"Path '{candidate}' resolves outside the allowed export directory. "
                "Export/import paths must stay within the storage area."
            ) from None
        return resolved

    def _load_session(self) -> None:
        """Load thought history from the current session file if it exists.

        If no v2 JSONL session exists but a legacy v1 JSON session does, the
        v1 file is migrated to JSONL once (lossless, idempotent).
        """
        with self._lock:
            if not self.current_session_file.exists() and self.legacy_session_file.exists():
                self._migrate_v1_session()
                return

            # backup_on_corruption=True: this is our own session file, so a
            # corrupt or invalid file is backed up (or a truncated final line
            # dropped) and we recover rather than crashing the server on startup.
            self.thought_history = load_thoughts_from_jsonl(
                self.current_session_file,
                self.lock_file,
                backup_on_corruption=True,
                timeout=self.lock_timeout,
            )

    def _migrate_v1_session(self) -> None:
        """Migrate a legacy v1 JSON session file to the v2 JSONL format.

        The v1 file is loaded (with the usual corruption recovery), rewritten
        as JSONL, and then renamed to ``current_session.json.migrated-to-v2``
        so a second start only finds the JSONL file.
        """
        with portalocker.Lock(self.lock_file, timeout=self.lock_timeout):
            thoughts = load_thoughts_from_file(
                self.legacy_session_file,
                self.lock_file,
                backup_on_corruption=True,
                timeout=self.lock_timeout,
                _already_locked=True,
            )
            rewrite_jsonl(
                self.current_session_file,
                self.lock_file,
                prepare_thoughts_for_serialization(thoughts),
                timeout=self.lock_timeout,
                _already_locked=True,
            )
            # Preserve the validated v1 original after the v2 replacement succeeds.
            if self.legacy_session_file.exists():
                migrated = self.legacy_session_file.with_name("current_session.json.migrated-to-v2")
                self.legacy_session_file.rename(migrated)
                logger.info(
                    f"Migrated v1 session ({len(thoughts)} thoughts) to "
                    f"{self.current_session_file}; original kept at {migrated}"
                )
            self.thought_history = thoughts

    def add_thought(self, thought: ThoughtData) -> None:
        """Add a thought to the history and append it to the session file.

        Args:
            thought: The thought data to add

        Raises:
            DuplicateThoughtNumberError: If ``thought.thought_number`` is
                already used on the same line (mainline or the same
                ``branch_id``). The check and the append happen under the
                same lock acquisition, so this holds even under concurrent
                callers racing on the same number (B1).
        """
        with self._transaction():
            self._append_validated(thought)

    def _append_validated(self, thought: ThoughtData) -> None:
        existing = next(
            (
                t
                for t in self.thought_history
                if t.branch_id == thought.branch_id and t.thought_number == thought.thought_number
            ),
            None,
        )
        if existing is not None:
            raise DuplicateThoughtNumberError(thought.thought_number, thought.branch_id, existing)

        validate_thoughts([*self.thought_history, thought])
        append_thought_to_jsonl(
            self.current_session_file,
            self.lock_file,
            thought.to_dict(include_id=True),
            timeout=self.lock_timeout,
        )
        self.thought_history.append(thought.model_copy(deep=True))

    def get_all_thoughts(self) -> list[ThoughtData]:
        """Get all thoughts in the current session.

        Returns:
            List[ThoughtData]: All thoughts in the current session
        """
        with self._transaction():
            # Return a copy to avoid external modification
            return [t.model_copy(deep=True) for t in self.thought_history]

    def get_thoughts_by_stage(self, stage: ThoughtStage) -> list[ThoughtData]:
        """Get all thoughts in a specific stage.

        Args:
            stage: The thinking stage to filter by

        Returns:
            List[ThoughtData]: Thoughts in the specified stage
        """
        with self._transaction():
            return [t.model_copy(deep=True) for t in self.thought_history if t.stage == stage]

    def next_thought_number(
        self, branch_id: str | None, branch_from_thought: int | None = None
    ) -> int:
        """Compute the next free thought number for a line (B1: used when the
        caller omits ``thought_number``).

        For the mainline (``branch_id is None``), this continues the highest
        number used anywhere in the session (mainline or branch), matching
        the existing convention of one global increasing counter. For a
        fresh branch with no thoughts yet, numbering continues from its fork
        point (``branch_from_thought``) rather than restarting.

        Args:
            branch_id: The line to compute the next number for.
            branch_from_thought: The fork point, used only when starting a
                brand-new branch that has no thoughts yet.

        Returns:
            int: The next free thought number.
        """
        with self._lock:
            line_numbers = [
                t.thought_number for t in self.thought_history if t.branch_id == branch_id
            ]
            if line_numbers:
                return max(line_numbers) + 1
            if branch_id is not None and branch_from_thought is not None:
                return branch_from_thought + 1
            all_numbers = [t.thought_number for t in self.thought_history]
            return (max(all_numbers) + 1) if all_numbers else 1

    def clear_history(self) -> int:
        """Clear the thought history and rewrite the session file."""
        with self._transaction():
            count = len(self.thought_history)
            rewrite_jsonl(self.current_session_file, self.lock_file, [], timeout=self.lock_timeout)
            self.thought_history.clear()
            return count

    def export_session(self, file_path: str) -> int:
        """Export the current session to a file.

        Args:
            file_path: Path to save the exported session. Relative paths are
                resolved against the ``exports/`` subdirectory of the storage
                directory; the result must stay inside it.

        Raises:
            ValueError: If file_path resolves outside the export directory.
        """
        # Confine the caller-controlled path to export_dir before any file I/O,
        # so an export can never overwrite the session or lock file.
        file_path_obj = self._ensure_within(self.export_dir, file_path)
        self.export_dir.mkdir(parents=True, exist_ok=True)

        with self._transaction():
            # Use utility function to prepare thoughts for serialization
            thoughts_with_ids = prepare_thoughts_for_serialization(self.thought_history)

            # Create export-specific metadata
            metadata = {
                "exportedAt": datetime.now().isoformat(),
                "metadata": {
                    "totalThoughts": len(self.thought_history),
                    "stages": {
                        stage.value: len([t for t in self.thought_history if t.stage == stage])
                        for stage in ThoughtStage
                    },
                },
            }

        lock_file = file_path_obj.with_suffix(".lock")

        # Use utility function to save with proper locking
        save_thoughts_to_file(
            file_path_obj, thoughts_with_ids, lock_file, metadata, timeout=self.lock_timeout
        )
        return len(thoughts_with_ids)

    def import_session(self, file_path: str) -> int:
        """Import a session from a file.

        Args:
            file_path: Path to the file to import. Relative paths are resolved
                against the ``exports/`` subdirectory of the storage directory;
                the result must stay inside it.

        Raises:
            ValueError: If file_path resolves outside the export directory,
                if the file is not valid JSON, or if it contains semantically
                invalid thought data. In all error cases the input file and the
                current session are left untouched.
            FileNotFoundError: If the file doesn't exist.
            KeyError: If the file doesn't contain a 'thoughts' key.
        """
        # Confine the caller-controlled path to export_dir before any file I/O.
        file_path_obj = self._ensure_within(self.export_dir, file_path)
        lock_file = file_path_obj.with_suffix(".lock")

        # load_thoughts_from_file returns [] for missing files (recovery
        # behaviour for the server's own session file). For an import that
        # would silently wipe the current session, so reject explicitly.
        if not file_path_obj.exists():
            raise FileNotFoundError(f"Import file not found: {file_path}")

        # Use utility function to load thoughts. backup_on_corruption defaults to
        # False, so a malformed/invalid input file raises instead of renaming the
        # caller's file or silently wiping the current session.
        thoughts = load_thoughts_from_file(file_path_obj, lock_file, timeout=self.lock_timeout)

        with self._transaction():
            rewrite_jsonl(
                self.current_session_file,
                self.lock_file,
                prepare_thoughts_for_serialization(thoughts),
                timeout=self.lock_timeout,
            )
            self.thought_history = thoughts
            return len(thoughts)
