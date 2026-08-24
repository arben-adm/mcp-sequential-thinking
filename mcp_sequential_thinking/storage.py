import threading
from typing import List, Optional
from pathlib import Path
from datetime import datetime

from .models import ThoughtData, ThoughtStage
from .logging_conf import configure_logging
from .storage_utils import (
    append_thought_to_jsonl,
    load_thoughts_from_file,
    load_thoughts_from_jsonl,
    prepare_thoughts_for_serialization,
    rewrite_jsonl,
    save_thoughts_to_file,
)

logger = configure_logging("sequential-thinking.storage")


class DuplicateThoughtNumberError(ValueError):
    """Raised by :meth:`ThoughtStorage.add_thought` when ``thought_number``
    collides with an existing thought on the same line (B1)."""

    def __init__(self, thought_number: int, branch_id: Optional[str], existing: ThoughtData):
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

    def __init__(self, storage_dir: Optional[str] = None, lock_timeout: float = 10.0):
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
        self.thought_history: List[ThoughtData] = []

        # Load existing session if available
        self._load_session()

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
            )
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
        thoughts = load_thoughts_from_file(
            self.legacy_session_file,
            self.lock_file,
            backup_on_corruption=True,
            timeout=self.lock_timeout,
        )
        rewrite_jsonl(
            self.current_session_file,
            self.lock_file,
            prepare_thoughts_for_serialization(thoughts),
            timeout=self.lock_timeout,
        )
        # On corruption the v1 file was already renamed to a .bak backup.
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
        # Memory update AND file append run under the lock so disk order
        # always matches memory order (RLock makes reentrancy harmless).
        with self._lock:
            existing = next(
                (
                    t
                    for t in self.thought_history
                    if t.branch_id == thought.branch_id
                    and t.thought_number == thought.thought_number
                ),
                None,
            )
            if existing is not None:
                raise DuplicateThoughtNumberError(
                    thought.thought_number, thought.branch_id, existing
                )

            self.thought_history.append(thought)
            append_thought_to_jsonl(
                self.current_session_file,
                self.lock_file,
                thought.to_dict(include_id=True),
                timeout=self.lock_timeout,
            )

    def get_all_thoughts(self) -> List[ThoughtData]:
        """Get all thoughts in the current session.

        Returns:
            List[ThoughtData]: All thoughts in the current session
        """
        with self._lock:
            # Return a copy to avoid external modification
            return list(self.thought_history)

    def get_thoughts_by_stage(self, stage: ThoughtStage) -> List[ThoughtData]:
        """Get all thoughts in a specific stage.

        Args:
            stage: The thinking stage to filter by

        Returns:
            List[ThoughtData]: Thoughts in the specified stage
        """
        with self._lock:
            return [t for t in self.thought_history if t.stage == stage]

    def next_thought_number(
        self, branch_id: Optional[str], branch_from_thought: Optional[int] = None
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
            line_numbers = [t.thought_number for t in self.thought_history if t.branch_id == branch_id]
            if line_numbers:
                return max(line_numbers) + 1
            if branch_id is not None and branch_from_thought is not None:
                return branch_from_thought + 1
            all_numbers = [t.thought_number for t in self.thought_history]
            return (max(all_numbers) + 1) if all_numbers else 1

    def clear_history(self) -> None:
        """Clear the thought history and rewrite the session file."""
        with self._lock:
            self.thought_history.clear()
            rewrite_jsonl(self.current_session_file, self.lock_file, [], timeout=self.lock_timeout)

    def export_session(self, file_path: str) -> None:
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

        with self._lock:
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
                    }
                }
            }
        
        lock_file = file_path_obj.with_suffix('.lock')

        # Use utility function to save with proper locking
        save_thoughts_to_file(
            file_path_obj, thoughts_with_ids, lock_file, metadata, timeout=self.lock_timeout
        )

    def import_session(self, file_path: str) -> None:
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
        lock_file = file_path_obj.with_suffix('.lock')

        # load_thoughts_from_file returns [] for missing files (recovery
        # behaviour for the server's own session file). For an import that
        # would silently wipe the current session, so reject explicitly.
        if not file_path_obj.exists():
            raise FileNotFoundError(f"Import file not found: {file_path}")

        # Use utility function to load thoughts. backup_on_corruption defaults to
        # False, so a malformed/invalid input file raises instead of renaming the
        # caller's file or silently wiping the current session.
        thoughts = load_thoughts_from_file(file_path_obj, lock_file, timeout=self.lock_timeout)

        with self._lock:
            self.thought_history = thoughts
            rewrite_jsonl(
                self.current_session_file,
                self.lock_file,
                prepare_thoughts_for_serialization(thoughts),
                timeout=self.lock_timeout,
            )
