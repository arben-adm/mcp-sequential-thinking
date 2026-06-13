import threading
from typing import List, Optional
from pathlib import Path
from datetime import datetime

from .models import ThoughtData, ThoughtStage
from .logging_conf import configure_logging
from .storage_utils import prepare_thoughts_for_serialization, save_thoughts_to_file, load_thoughts_from_file

logger = configure_logging("sequential-thinking.storage")


class ThoughtStorage:
    """Storage manager for thought data."""

    def __init__(self, storage_dir: Optional[str] = None):
        """Initialize the storage manager.

        Args:
            storage_dir: Directory to store thought data files. If None, uses a default directory.
        """
        if storage_dir is None:
            # Use user's home directory by default
            home_dir = Path.home()
            self.storage_dir = home_dir / ".mcp_sequential_thinking"
        else:
            self.storage_dir = Path(storage_dir)

        # Create storage directory if it doesn't exist
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # Default session file
        self.current_session_file = self.storage_dir / "current_session.json"
        self.lock_file = self.storage_dir / "current_session.lock"

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
            raise ValueError(
                f"Path '{candidate}' is outside the allowed storage directory "
                f"'{base_r}'. Export/import are confined to the storage directory."
            )
        return resolved

    def _load_session(self) -> None:
        """Load thought history from the current session file if it exists."""
        with self._lock:
            # Use the utility function to handle loading with proper error handling.
            # backup_on_corruption=True: this is our own session file, so a corrupt
            # or invalid file is backed up and we recover with an empty session
            # rather than crashing the server on startup.
            self.thought_history = load_thoughts_from_file(
                self.current_session_file, self.lock_file, backup_on_corruption=True
            )

    def _save_session(self) -> None:
        """Save the current thought history to the session file."""
        # Use thread lock to ensure consistent data. Snapshot AND file write
        # must both run under the lock so a stale snapshot can never be written
        # after a newer one (RLock makes reentrancy harmless).
        with self._lock:
            # Use utility functions to prepare and save thoughts
            thoughts_with_ids = prepare_thoughts_for_serialization(self.thought_history)

            # Save to file with proper locking
            save_thoughts_to_file(self.current_session_file, thoughts_with_ids, self.lock_file)

    def add_thought(self, thought: ThoughtData) -> None:
        """Add a thought to the history and save the session.

        Args:
            thought: The thought data to add
        """
        with self._lock:
            self.thought_history.append(thought)
        self._save_session()

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

    def clear_history(self) -> None:
        """Clear the thought history and save the empty session."""
        with self._lock:
            self.thought_history.clear()
        self._save_session()

    def export_session(self, file_path: str) -> None:
        """Export the current session to a file.

        Args:
            file_path: Path to save the exported session. Must resolve to a
                location inside the storage directory.

        Raises:
            ValueError: If file_path resolves outside the storage directory.
        """
        # Confine the caller-controlled path to storage_dir before any file I/O.
        file_path_obj = self._ensure_within(self.storage_dir, file_path)

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
        save_thoughts_to_file(file_path_obj, thoughts_with_ids, lock_file, metadata)

    def import_session(self, file_path: str) -> None:
        """Import a session from a file.

        Args:
            file_path: Path to the file to import

        Raises:
            ValueError: If file_path resolves outside the storage directory,
                if the file is not valid JSON, or if it contains semantically
                invalid thought data. In all error cases the input file and the
                current session are left untouched.
            FileNotFoundError: If the file doesn't exist.
            KeyError: If the file doesn't contain valid thought data.
        """
        # Confine the caller-controlled path to storage_dir before any file I/O.
        file_path_obj = self._ensure_within(self.storage_dir, file_path)
        lock_file = file_path_obj.with_suffix('.lock')

        # Use utility function to load thoughts. backup_on_corruption defaults to
        # False, so a malformed/invalid input file raises instead of renaming the
        # caller's file or silently wiping the current session.
        thoughts = load_thoughts_from_file(file_path_obj, lock_file)

        with self._lock:
            self.thought_history = thoughts

        self._save_session()
