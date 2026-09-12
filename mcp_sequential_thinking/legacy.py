"""Compatibility adapter for the five original tools over the session database."""

from __future__ import annotations

import json
from typing import Any

import portalocker

from .analysis import ThoughtAnalyzer
from .models import ThoughtData, ThoughtStage
from .sessions import SessionError, SessionRepository, _json, _now
from .storage import DuplicateThoughtNumberError, ThoughtStorage
from .storage_utils import (
    load_thoughts_from_file,
    prepare_thoughts_for_serialization,
    save_thoughts_to_file,
    validate_thoughts,
)


class LegacyAdapter:
    """One explicit local legacy session; not a tenant or authorization boundary."""

    def __init__(self, repository: SessionRepository):
        self.repository = repository
        self.storage_dir = repository.directory
        self.export_dir = self.storage_dir / "exports"
        self.lock_file = self.storage_dir / "state.lock"
        self.lock_timeout = 5.0
        repository.migrate_legacy()
        self._guard: portalocker.Lock | None = None
        if not repository.ephemeral:
            self._guard = portalocker.Lock(
                self.storage_dir / "current_session.lock",
                timeout=5,
                flags=portalocker.LOCK_SH | portalocker.LOCK_NB,
            )
            self._guard.acquire()
            try:
                repository.migrate_legacy()
            except BaseException:
                self._guard.release()
                raise
        with repository._write() as connection:
            if connection.execute("SELECT 1 FROM sessions WHERE id='legacy'").fetchone() is None:
                connection.execute(
                    "INSERT INTO sessions VALUES('legacy','Legacy working notes',"
                    "'freeform','active',0,?,NULL)",
                    (_now(),),
                )
                connection.execute("INSERT INTO branches VALUES('legacy','main',NULL)")

    def close(self) -> None:
        if self._guard is not None:
            self._guard.release()

    @property
    def thought_history(self) -> list[ThoughtData]:
        return self.get_all_thoughts()

    def get_all_thoughts(self) -> list[ThoughtData]:
        with self.repository._connection() as connection:
            rows = connection.execute(
                "SELECT legacy FROM steps WHERE session_id='legacy' ORDER BY rowid"
            ).fetchall()
            return [ThoughtData.from_dict(json.loads(row["legacy"])) for row in rows]

    @staticmethod
    def _next(thoughts: list[ThoughtData], branch_id: str | None, fork: int | None) -> int:
        numbers = [t.thought_number for t in thoughts if t.branch_id == branch_id]
        if numbers:
            return max(numbers) + 1
        if branch_id is not None and fork is not None:
            return fork + 1
        return max((t.thought_number for t in thoughts), default=0) + 1

    def record_thought(
        self, *, strict_stages: bool = False, **fields: Any
    ) -> tuple[ThoughtData, list[ThoughtData], list[str]]:
        with self.repository._write() as connection:
            session = self.repository._session(connection, "legacy")
            if session["status"] != "active":
                raise SessionError("CONFLICT", "Legacy session has been finalized")
            rows = connection.execute(
                "SELECT legacy FROM steps WHERE session_id='legacy' ORDER BY rowid"
            ).fetchall()
            thoughts = [ThoughtData.from_dict(json.loads(row["legacy"])) for row in rows]
            if fields.get("thought_number") is None:
                fields["thought_number"] = self._next(
                    thoughts, fields.get("branch_id"), fields.get("branch_from_thought")
                )
            thought = ThoughtData(**fields)
            duplicate = next(
                (
                    t
                    for t in thoughts
                    if t.branch_id == thought.branch_id
                    and t.thought_number == thought.thought_number
                ),
                None,
            )
            if duplicate is not None:
                raise DuplicateThoughtNumberError(
                    thought.thought_number, thought.branch_id, duplicate
                )
            validate_thoughts([*thoughts, thought])
            issue = ThoughtAnalyzer.detect_stage_transition_issue(thought, thoughts)
            if issue and strict_stages:
                raise ValueError(issue)
            self._insert(connection, thought, thoughts)
            connection.execute("UPDATE sessions SET version=version+1 WHERE id='legacy'")
            return thought, [*thoughts, thought], [issue] if issue else []

    @staticmethod
    def _insert(connection: Any, thought: ThoughtData, prior: list[ThoughtData]) -> None:
        branch = "main" if thought.branch_id is None else "legacy-" + thought.branch_id
        parent = next(
            (
                str(t.id)
                for t in prior
                if t.branch_id is None and t.thought_number == thought.branch_from_thought
            ),
            None,
        )
        revision = next(
            (
                str(t.id)
                for t in prior
                if t.branch_id == thought.branch_id
                and t.thought_number == thought.revises_thought_number
            ),
            None,
        )
        if (
            connection.execute(
                "SELECT 1 FROM branches WHERE session_id='legacy' AND id=?", (branch,)
            ).fetchone()
            is None
        ):
            connection.execute("INSERT INTO branches VALUES('legacy',?,?)", (branch, parent))
        connection.execute(
            "INSERT INTO steps VALUES(?,'legacy',?,?,?,?,?,?,?,'[]',?)",
            (
                str(thought.id),
                branch,
                thought.thought_number,
                thought.thought,
                "note",
                parent,
                revision,
                thought.timestamp,
                _json(thought.to_dict(True)),
            ),
        )

    def clear_history(self) -> int:
        return self._replace([])

    def _replace(self, thoughts: list[ThoughtData]) -> int:
        validate_thoughts(thoughts)
        with self.repository._write() as connection:
            session = self.repository._session(connection, "legacy")
            if session["status"] != "active":
                raise SessionError("CONFLICT", "Legacy session has been finalized")
            count = connection.execute(
                "SELECT COUNT(*) FROM steps WHERE session_id='legacy'"
            ).fetchone()[0]
            if count == 0 and not thoughts:
                return 0
            connection.execute("PRAGMA defer_foreign_keys=ON")
            connection.execute("DELETE FROM steps WHERE session_id='legacy'")
            connection.execute("DELETE FROM branches WHERE session_id='legacy'")
            connection.execute("INSERT INTO branches VALUES('legacy','main',NULL)")
            prior: list[ThoughtData] = []
            for thought in thoughts:
                self._insert(connection, thought, prior)
                prior.append(thought)
            connection.execute("UPDATE sessions SET version=version+1 WHERE id='legacy'")
            return int(count)

    def export_session(self, file_path: str) -> int:
        if self.repository.ephemeral:
            raise SessionError("INVALID_INPUT", "File export is disabled in ephemeral mode")
        path = ThoughtStorage._ensure_within(self.export_dir, file_path)
        thoughts = self.get_all_thoughts()
        save_thoughts_to_file(
            path,
            prepare_thoughts_for_serialization(thoughts),
            path.with_suffix(".lock"),
        )

        return len(thoughts)

    def import_session(self, file_path: str) -> int:
        if self.repository.ephemeral:
            raise SessionError("INVALID_INPUT", "File import is disabled in ephemeral mode")
        path = ThoughtStorage._ensure_within(self.export_dir, file_path)
        if not path.is_file():
            raise FileNotFoundError("Import file not found in exports directory")
        thoughts = load_thoughts_from_file(path, path.with_suffix(".lock"))
        self._replace(thoughts)
        return len(thoughts)

    def get_thoughts_by_stage(self, stage: ThoughtStage) -> list[ThoughtData]:
        return [t for t in self.get_all_thoughts() if t.stage == stage]

    def next_thought_number(
        self, branch_id: str | None, branch_from_thought: int | None = None
    ) -> int:
        return self._next(self.get_all_thoughts(), branch_id, branch_from_thought)
