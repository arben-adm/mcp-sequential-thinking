"""Local transactional work-note repository; each operation owns its connection."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Literal, cast
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

Kind = Literal[
    "note", "observation", "evidence", "assumption", "option", "risk", "decision", "next_action"
]
Text = Annotated[str, Field(min_length=1, max_length=10000)]
ShortText = Annotated[str, Field(min_length=1, max_length=500)]


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    uri: Annotated[str, Field(min_length=1, max_length=2000)]
    locator: Annotated[str, Field(max_length=500)] = ""
    excerpt: Annotated[str, Field(max_length=2000)] = ""
    provenance: Literal["caller_supplied_unverified"] = "caller_supplied_unverified"


class Completion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    outcome: Annotated[str, Field(max_length=3000)] = ""
    rationale: Annotated[str, Field(max_length=3000)] = ""
    evidence_step_ids: Annotated[list[UUID], Field(max_length=50)] = Field(default_factory=list)
    assumptions: Annotated[list[ShortText], Field(max_length=20)] = Field(default_factory=list)
    rejected_options: Annotated[list[ShortText], Field(max_length=20)] = Field(default_factory=list)
    risks: Annotated[list[ShortText], Field(max_length=20)] = Field(default_factory=list)
    open_questions: Annotated[list[ShortText], Field(max_length=20)] = Field(default_factory=list)
    next_actions: Annotated[list[ShortText], Field(max_length=20)] = Field(default_factory=list)

    @model_validator(mode="after")
    def bounded_completion(self) -> Completion:
        if len(self.model_dump_json()) > 20000:
            raise ValueError("Completion exceeds 20000 characters")
        return self


class StepInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    content: Text
    kind: Kind = "note"
    branch_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")] = "main"
    parent_step_id: UUID | None = None
    supersedes_step_id: UUID | None = None
    branch_from_step_id: UUID | None = None
    sources: Annotated[list[Source], Field(max_length=20)] = Field(default_factory=list)

    @model_validator(mode="after")
    def bounded_step(self) -> StepInput:
        if not self.content.strip():
            raise ValueError("Content must not be blank")
        if len(self.model_dump_json()) > 30000:
            raise ValueError("Step including sources exceeds 30000 characters")
        return self


class SessionError(ValueError):
    """Stable, bounded, content-free business error for MCP tool adapters."""

    def __init__(self, code: str, hint: str):
        self.code = code
        self.hint = hint
        super().__init__(f"{code}: {hint}")


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_SCHEMA = """
CREATE TABLE sessions (
 id TEXT PRIMARY KEY NOT NULL, title TEXT NOT NULL, mode TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('active','finalized')),
 version INTEGER NOT NULL CHECK(version >= 0), created_at TEXT NOT NULL,
 completion TEXT
);
CREATE TABLE branches (
 session_id TEXT NOT NULL, id TEXT NOT NULL, origin_id TEXT,
 PRIMARY KEY(session_id,id),
 FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE,
 FOREIGN KEY(session_id,origin_id) REFERENCES steps(session_id,id)
);
CREATE TABLE steps (
 id TEXT PRIMARY KEY NOT NULL, session_id TEXT NOT NULL, branch_id TEXT NOT NULL,
 position INTEGER NOT NULL CHECK(position > 0), content TEXT NOT NULL,
 kind TEXT NOT NULL, parent_id TEXT, supersedes_id TEXT, created_at TEXT NOT NULL,
 sources TEXT NOT NULL, legacy TEXT,
 UNIQUE(session_id,id), UNIQUE(session_id,branch_id,position),
 FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE,
 FOREIGN KEY(session_id,branch_id) REFERENCES branches(session_id,id),
 FOREIGN KEY(session_id,parent_id) REFERENCES steps(session_id,id),
 FOREIGN KEY(session_id,supersedes_id) REFERENCES steps(session_id,id)
);
CREATE TABLE requests (
 scope TEXT NOT NULL, request_id TEXT NOT NULL, payload TEXT NOT NULL,
 result TEXT NOT NULL, PRIMARY KEY(scope,request_id)
);
CREATE TABLE migrations (
 name TEXT PRIMARY KEY NOT NULL, checksum TEXT NOT NULL, source_version INTEGER NOT NULL,
 mapping TEXT NOT NULL, completed_at TEXT NOT NULL
);
CREATE INDEX steps_session ON steps(session_id,created_at,id);
"""


class SessionRepository:
    """SQLite on a local filesystem, no shared mutable record cache.

    BEGIN IMMEDIATE serializes writers; busy_timeout bounds lock waiting to five
    seconds. Connections are opened/closed in the calling worker thread. Request
    mappings commit with data. A retry after a lost response reads the saved result.
    """

    def __init__(self, directory: str | None = None, *, ephemeral: bool = False):
        self.ephemeral = ephemeral
        self._memory_lock = threading.RLock()
        self._anchor: sqlite3.Connection | None = None
        self.directory = Path(directory or ".")
        self.path: Path | str
        if ephemeral:
            self.path = f"file:worklog-{uuid4()}?mode=memory&cache=shared"
            self._anchor = sqlite3.connect(self.path, uri=True)
        else:
            self.directory.mkdir(parents=True, exist_ok=True)
            self.path = self.directory / "worklog.sqlite3"
        with self._connection() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise SessionError("UNSUPPORTED_SCHEMA", "Use a compatible server or restore")
            connection.execute(
                "PRAGMA journal_mode=MEMORY" if ephemeral else "PRAGMA journal_mode=WAL"
            )
            connection.execute("BEGIN IMMEDIATE")
            try:
                # Recheck under the write lock for concurrent first starts.
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version == 0:
                    for statement in _SCHEMA.split(";"):
                        if statement.strip():
                            connection.execute(statement)
                    connection.execute("PRAGMA user_version=1")
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def close(self) -> None:
        if self._anchor is not None:
            self._anchor.close()
            self._anchor = None

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        with self._memory_lock if self.ephemeral else nullcontext():
            connection: sqlite3.Connection | None = None
            try:
                connection = sqlite3.connect(
                    self.path, timeout=5, isolation_level=None, uri=self.ephemeral
                )
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA busy_timeout=5000")
                connection.execute("PRAGMA synchronous=FULL")
                yield connection
            except sqlite3.IntegrityError:
                raise SessionError("CONFLICT", "Stored identities or references conflict") from None
            except sqlite3.Error as error:
                code = getattr(error, "sqlite_errorcode", None)
                # Python 3.10 does not expose sqlite_errorcode. Match only SQLite's
                # fixed lock messages there; never include database error text in replies.
                busy = (code is not None and code & 0xFF in (5, 6)) or (
                    code is None
                    and str(error)
                    in (
                        "database is locked",
                        "database table is locked",
                        "database schema is locked",
                    )
                )
                if busy:
                    raise SessionError("STORAGE_BUSY", "Retry the same request_id") from None
                raise SessionError(
                    "STORAGE_ERROR", "Inspect storage; retry with the same request_id"
                ) from None
            finally:
                if connection is not None:
                    connection.close()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    @staticmethod
    def _session(connection: sqlite3.Connection, session_id: str) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if row is None:
            raise SessionError("UNKNOWN_SESSION", "Use list_sessions to select an existing session")
        return cast(sqlite3.Row, row)

    @staticmethod
    def _replay(
        connection: sqlite3.Connection, scope: str, request_id: str, payload: str
    ) -> dict[str, Any] | None:
        if not 1 <= len(request_id) <= 128:
            raise SessionError("INVALID_INPUT", "request_id must contain 1–128 characters")
        row = connection.execute(
            "SELECT payload,result FROM requests WHERE scope=? AND request_id=?",
            (scope, request_id),
        ).fetchone()
        if row is None:
            return None
        if row["payload"] != hashlib.sha256(payload.encode("utf-8")).hexdigest():
            raise SessionError(
                "IDEMPOTENCY_CONFLICT", "Use the original content or a new request_id"
            )
        result: dict[str, Any] = json.loads(row["result"])
        return result

    @staticmethod
    def _remember(
        connection: sqlite3.Connection,
        scope: str,
        request_id: str,
        payload: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        connection.execute(
            "INSERT INTO requests VALUES(?,?,?,?)",
            (scope, request_id, hashlib.sha256(payload.encode("utf-8")).hexdigest(), _json(result)),
        )
        return result

    def create_session(
        self, title: str, request_id: str, mode: Literal["freeform"] = "freeform"
    ) -> dict[str, Any]:
        if not title.strip() or len(title) > 500 or mode != "freeform":
            raise SessionError(
                "INVALID_INPUT", "Provide a title of 1–500 characters and mode freeform"
            )
        payload = _json({"title": title, "mode": mode})
        with self._write() as connection:
            cached = self._replay(connection, "create", request_id, payload)
            if cached is not None:
                return cached
            session_id = str(uuid4())
            connection.execute(
                "INSERT INTO sessions VALUES(?,?,?,'active',0,?,NULL)",
                (session_id, title, mode, _now()),
            )
            connection.execute("INSERT INTO branches VALUES(?,'main',NULL)", (session_id,))
            return self._remember(
                connection,
                "create",
                request_id,
                payload,
                {
                    "session_id": session_id,
                    "status": "active",
                    "version": 0,
                    "storage": "memory_only" if self.ephemeral else "local_plaintext_sqlite",
                    "retention": "until_process_exit"
                    if self.ephemeral
                    else "until_explicit_deletion",
                    "deletion_scope": "active_database_records; backups and exported copies remain",
                },
            )

    @staticmethod
    def _reference(connection: sqlite3.Connection, session_id: str, step_id: str | None) -> None:
        if (
            step_id is not None
            and connection.execute(
                "SELECT 1 FROM steps WHERE session_id=? AND id=?", (session_id, step_id)
            ).fetchone()
            is None
        ):
            raise SessionError("INVALID_REFERENCE", "Reference an existing step in this session")

    def add_step(self, session_id: str, step: StepInput, request_id: str) -> dict[str, Any]:
        if session_id == "legacy":
            raise SessionError(
                "INVALID_INPUT", "Use process_thought for writes to the compatibility session"
            )
        payload = _json(step.model_dump(mode="json"))
        scope = "step:" + session_id
        with self._write() as connection:
            cached = self._replay(connection, scope, request_id, payload)
            if cached is not None:
                return cached
            session = self._session(connection, session_id)
            if session["status"] != "active":
                raise SessionError("CONFLICT", "Finalized sessions do not accept new steps")
            parent = str(step.parent_step_id) if step.parent_step_id else None
            supersedes = str(step.supersedes_step_id) if step.supersedes_step_id else None
            origin = str(step.branch_from_step_id) if step.branch_from_step_id else None
            for reference in (parent, supersedes, origin):
                self._reference(connection, session_id, reference)
            branch = connection.execute(
                "SELECT origin_id FROM branches WHERE session_id=? AND id=?",
                (session_id, step.branch_id),
            ).fetchone()
            if branch is None:
                if origin is None:
                    raise SessionError(
                        "INVALID_REFERENCE", "A new branch requires branch_from_step_id"
                    )
                connection.execute(
                    "INSERT INTO branches VALUES(?,?,?)", (session_id, step.branch_id, origin)
                )
            elif origin is not None and branch["origin_id"] != origin:
                raise SessionError("INVALID_REFERENCE", "A branch's origin cannot change")
            if supersedes is not None:
                target = connection.execute(
                    "SELECT branch_id FROM steps WHERE session_id=? AND id=?",
                    (session_id, supersedes),
                ).fetchone()
                if target["branch_id"] != step.branch_id:
                    raise SessionError(
                        "INVALID_REFERENCE", "Revisions must stay on the target branch"
                    )
                if connection.execute(
                    "SELECT 1 FROM steps WHERE session_id=? AND supersedes_id=?",
                    (session_id, supersedes),
                ).fetchone():
                    raise SessionError(
                        "CONFLICT", "Revise the current replacement, not an already superseded step"
                    )
            position = connection.execute(
                "SELECT COALESCE(MAX(position),0)+1 FROM steps WHERE session_id=? AND branch_id=?",
                (session_id, step.branch_id),
            ).fetchone()[0]
            step_id, created = str(uuid4()), _now()
            connection.execute(
                "INSERT INTO steps VALUES(?,?,?,?,?,?,?,?,?,?,NULL)",
                (
                    step_id,
                    session_id,
                    step.branch_id,
                    position,
                    step.content,
                    step.kind,
                    parent,
                    supersedes,
                    created,
                    _json([source.model_dump() for source in step.sources]),
                ),
            )
            connection.execute("UPDATE sessions SET version=version+1 WHERE id=?", (session_id,))
            result = {
                "step_id": step_id,
                "session_id": session_id,
                "branch_id": step.branch_id,
                "position": position,
                "version": session["version"] + 1,
                "created_at": created,
            }
            return self._remember(connection, scope, request_id, payload, result)

    def finalize_session(
        self, session_id: str, completion: Completion, expected_version: int, request_id: str
    ) -> dict[str, Any]:
        payload = _json(
            {"completion": completion.model_dump(mode="json"), "expected_version": expected_version}
        )
        scope = "finalize:" + session_id
        with self._write() as connection:
            cached = self._replay(connection, scope, request_id, payload)
            if cached is not None:
                return cached
            session = self._session(connection, session_id)
            if session["version"] != expected_version or session["status"] != "active":
                raise SessionError(
                    "CONFLICT", "Read the current session and use its active version"
                )
            for reference in completion.evidence_step_ids:
                self._reference(connection, session_id, str(reference))
            connection.execute(
                "UPDATE sessions SET status='finalized',version=version+1,completion=? WHERE id=?",
                (_json(completion.model_dump(mode="json")), session_id),
            )
            return self._remember(
                connection,
                scope,
                request_id,
                payload,
                {
                    "session_id": session_id,
                    "status": "finalized",
                    "version": expected_version + 1,
                },
            )

    def delete_session(
        self, session_id: str, expected_version: int, request_id: str
    ) -> dict[str, Any]:
        if session_id == "legacy":
            raise SessionError("INVALID_INPUT", "Use clear_history for the compatibility session")
        scope, payload = "delete:" + session_id, _json({"expected_version": expected_version})
        with self._write() as connection:
            cached = self._replay(connection, scope, request_id, payload)
            if cached is not None:
                return cached
            session = self._session(connection, session_id)
            if session["version"] != expected_version:
                raise SessionError("CONFLICT", "Read the current version before deleting")
            count = connection.execute(
                "SELECT COUNT(*) FROM steps WHERE session_id=?", (session_id,)
            ).fetchone()[0]
            # Deferred checks allow deleting cyclic table dependencies as one transaction.
            connection.execute("PRAGMA defer_foreign_keys=ON")
            connection.execute("DELETE FROM sessions WHERE id=?", (session_id,))
            # Request payloads may contain step content: delete these too.
            connection.execute(
                "DELETE FROM requests WHERE scope IN (?,?)",
                ("step:" + session_id, "finalize:" + session_id),
            )
            return self._remember(
                connection,
                scope,
                request_id,
                payload,
                {
                    "session_id": session_id,
                    "deleted_steps": count,
                    "scope": "active_database_records; not backups, exports, or secure erasure",
                },
            )

    def list_sessions(
        self,
        search: str = "",
        status: Literal["active", "finalized"] | None = None,
        cursor: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 100 or len(search) > 500:
            raise SessionError(
                "INVALID_INPUT", "limit must be 1–100 and search at most 500 characters"
            )
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id,title,status,version,created_at FROM sessions WHERE id>? AND "
                "instr(lower(title),lower(?))>0 AND (? IS NULL OR status=?) ORDER BY id LIMIT "
                "?",
                (cursor, search, status, status, limit + 1),
            ).fetchall()
            result: dict[str, Any] = {
                "sessions": [],
                "cursor": None,
                "limit": limit,
                "max_chars": 12000,
                "truncated": False,
            }
            for row in rows[:limit]:
                result["sessions"].append(dict(row))
                if len(json.dumps(result, ensure_ascii=False)) > 11800:
                    result["sessions"].pop()
                    result["truncated"] = True
                    break
            if len(result["sessions"]) < len(rows):
                result["cursor"] = result["sessions"][-1]["id"]
                result["truncated"] = True
            return result

    def read_session(
        self,
        session_id: str,
        cursor: int = 0,
        limit: int = 20,
        max_chars: int = 12000,
        kind: Kind | None = None,
        step_id: str | None = None,
        active_only: bool = False,
        content_offset: int | None = None,
        content_chars: int = 4000,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 100 or not 1000 <= max_chars <= 50000 or cursor < 0:
            raise SessionError(
                "INVALID_INPUT", "Use limit 1–100, max_chars 1000–50000 and nonnegative cursor"
            )
        if content_offset is not None and (
            content_offset < 0 or step_id is None or not 1 <= content_chars <= 10000
        ):
            raise SessionError("INVALID_INPUT", "Text chunks require step_id and valid offset/size")
        with self._connection() as connection:
            connection.execute("BEGIN")
            session = self._session(connection, session_id)
            rows = connection.execute(
                "SELECT s.rowid AS sequence,s.*, EXISTS(SELECT 1 FROM steps r WHERE "
                "r.session_id=s.session_id AND r.supersedes_id=s.id) AS superseded FROM steps "
                "s WHERE s.session_id=? AND s.rowid>? AND (? IS NULL OR s.kind=?) AND (? IS "
                "NULL OR s.id=?) AND (?=0 OR NOT EXISTS(SELECT 1 FROM steps r WHERE "
                "r.session_id=s.session_id AND r.supersedes_id=s.id)) ORDER BY s.rowid LIMIT "
                "?",
                (session_id, cursor, kind, kind, step_id, step_id, int(active_only), limit + 1),
            ).fetchall()
            result: dict[str, Any] = {
                "session_id": session_id,
                "title": session["title"],
                "status": session["status"],
                "version": session["version"],
                "steps": [],
                "completion": None,
                "completion_available": session["completion"] is not None,
                "cursor": None,
                "truncated": False,
                "max_chars": max_chars,
                "limit": limit,
            }
            if len(json.dumps(result, ensure_ascii=False)) > max_chars - 100:
                raise SessionError("RESPONSE_LIMIT", "Increase max_chars to read session metadata")
            if session["completion"] is not None:
                candidate = json.loads(session["completion"])
                result["completion"] = candidate
                if len(json.dumps(result, ensure_ascii=False)) > max_chars // 2:
                    result["completion"] = None
                    result["truncated"] = True
            for row in rows[:limit]:
                item = dict(row)
                item.pop("legacy")
                item["sources"] = json.loads(item["sources"])
                item["superseded"] = bool(item["superseded"])
                if content_offset is not None:
                    total = len(item["content"])
                    item["content"] = item["content"][
                        content_offset : content_offset + content_chars
                    ]
                    item["content_offset"] = content_offset
                    item["content_total_chars"] = total
                    end = content_offset + len(item["content"])
                    item["next_content_offset"] = end if end < total else None
                    item["content_truncated"] = content_offset > 0 or end < total
                    result["truncated"] = result["truncated"] or item["content_truncated"]
                result["steps"].append(item)
                result["cursor"] = row["sequence"]
                if len(json.dumps(result, ensure_ascii=False)) > max_chars - 100:
                    result["steps"].pop()
                    result["cursor"] = (
                        result["steps"][-1]["sequence"] if result["steps"] else cursor
                    )
                    result["truncated"] = True
                    if not result["steps"]:
                        raise SessionError(
                            "RESPONSE_LIMIT",
                            "Increase max_chars or use step_id with content_offset/content_chars",
                        )
                    break
            else:
                if len(rows) > limit:
                    result["truncated"] = True
                else:
                    result["cursor"] = None
            return result

    def migrate_legacy(self) -> dict[str, Any] | None:
        """Import one validated JSONL/v1 history, preserving source bytes and IDs.

        Stop old binaries first. The source's physical lock remains held through
        commit; a changed source on a later startup is a conflict, never silently
        ignored. The old JSONL implementation does not know SQLite exists.
        """
        import hashlib
        import os

        import portalocker

        from .storage_utils import load_thoughts_from_file, load_thoughts_from_jsonl

        if self.ephemeral:
            return None
        source = self.directory / "current_session.jsonl"
        if not source.exists():
            source = self.directory / "current_session.json"
        if not source.exists():
            return None
        state_lock = self.directory / "state.lock"
        file_lock = self.directory / "current_session.lock"
        with portalocker.Lock(state_lock, timeout=5):
            # Validation precedes mutation. JSONL recovery is deliberately not
            # performed by this migration: repair it explicitly with the A loader.
            before = source.read_bytes()
            checksum = hashlib.sha256(before).hexdigest()
            with self._connection() as connection:
                existing = connection.execute(
                    "SELECT checksum,mapping FROM migrations WHERE name='legacy'"
                ).fetchone()
                if existing is not None:
                    if existing["checksum"] != checksum:
                        raise SessionError(
                            "MIGRATION_CONFLICT",
                            "Legacy source changed after migration; stop old writers and reconcile",
                        )
                    return {"session_id": "legacy", "mapping": json.loads(existing["mapping"])}
            loader = (
                load_thoughts_from_jsonl if source.suffix == ".jsonl" else load_thoughts_from_file
            )
            thoughts = loader(source, file_lock)
            with portalocker.Lock(file_lock, timeout=5):
                if source.read_bytes() != before:
                    raise SessionError(
                        "MIGRATION_CONFLICT", "Source changed during validation; stop old writers"
                    )
                backup = self.directory / (source.name + ".pre-sqlite." + checksum)
                if backup.exists():
                    if backup.read_bytes() != before:
                        raise SessionError(
                            "MIGRATION_CONFLICT", "Migration backup does not match source"
                        )
                else:
                    with backup.open("xb") as stream:
                        stream.write(before)
                        stream.flush()
                        os.fsync(stream.fileno())
                with self._write() as connection:
                    if connection.execute("SELECT 1 FROM sessions WHERE id='legacy'").fetchone():
                        raise SessionError(
                            "MIGRATION_CONFLICT",
                            "Legacy session already exists without migration record",
                        )
                    connection.execute(
                        "INSERT INTO sessions VALUES('legacy','Legacy working notes',"
                        "'freeform','active',?,?,NULL)",
                        (len(thoughts), _now()),
                    )
                    connection.execute("INSERT INTO branches VALUES('legacy','main',NULL)")
                    mapping = []
                    by_position: dict[tuple[str | None, int], str] = {}
                    branches = {"main"}
                    for thought in thoughts:
                        branch = (
                            "main" if thought.branch_id is None else "legacy-" + thought.branch_id
                        )
                        parent = (
                            by_position.get((None, thought.branch_from_thought))
                            if thought.branch_from_thought
                            else None
                        )
                        revision = (
                            by_position.get((thought.branch_id, thought.revises_thought_number))
                            if thought.revises_thought_number
                            else None
                        )
                        if branch not in branches:
                            connection.execute(
                                "INSERT INTO branches VALUES('legacy',?,?)", (branch, parent)
                            )
                            branches.add(branch)
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
                        by_position[(thought.branch_id, thought.thought_number)] = str(thought.id)
                        mapping.append(
                            {
                                "branch_id": thought.branch_id,
                                "thought_number": thought.thought_number,
                                "step_id": str(thought.id),
                            }
                        )
                    if connection.execute("PRAGMA foreign_key_check").fetchall():
                        raise SessionError(
                            "MIGRATION_CONFLICT", "Migrated reference validation failed"
                        )
                    connection.execute(
                        "INSERT INTO migrations VALUES('legacy',?,?,?,?)",
                        (checksum, 2 if source.suffix == ".jsonl" else 1, _json(mapping), _now()),
                    )
                    return {"session_id": "legacy", "mapping": mapping}

    def resume_session(
        self, session_id: str, max_chars: int = 12000, limit: int = 20
    ) -> dict[str, Any]:
        """Extract active decisions/actions and recent notes, never infer conclusions."""
        if not 1000 <= max_chars <= 50000 or not 1 <= limit <= 100:
            raise SessionError("INVALID_INPUT", "Use max_chars 1000–50000 and limit 1–100")
        with self._connection() as connection:
            connection.execute("BEGIN")
            session = self._session(connection, session_id)
            rows = connection.execute(
                "SELECT s.* FROM steps s WHERE session_id=? AND NOT EXISTS "
                "(SELECT 1 FROM steps r WHERE r.session_id=s.session_id AND r.supersedes_id=s.id) "
                "ORDER BY CASE kind WHEN 'decision' THEN 0 WHEN 'next_action' THEN 1 "
                "WHEN 'risk' THEN 2 WHEN 'assumption' THEN 2 ELSE 3 END, rowid DESC LIMIT ?",
                (session_id, limit + 1),
            ).fetchall()
            result: dict[str, Any] = {
                "session_id": session_id,
                "goal": session["title"],
                "status": session["status"],
                "version": session["version"],
                "view": "resume",
                "steps": [],
                "completion": None,
                "completion_available": session["completion"] is not None,
                "truncated": False,
                "max_chars": max_chars,
                "limit": limit,
                "full_history": {"tool": "read_session", "view": "steps", "cursor": 0},
            }
            if len(json.dumps(result, ensure_ascii=False)) > max_chars - 100:
                raise SessionError("RESPONSE_LIMIT", "Increase max_chars to read session metadata")
            if session["completion"] is not None:
                completion = json.loads(session["completion"])
                excerpt = {
                    key: value[:3] if isinstance(value, list) else value[:500]
                    for key, value in completion.items()
                }
                result["completion"] = excerpt
                result["truncated"] = excerpt != completion
                if len(json.dumps(result, ensure_ascii=False)) > max_chars // 2:
                    result["completion"] = None
                    result["truncated"] = True
            for row in rows[:limit]:
                item = {
                    "id": row["id"],
                    "branch_id": row["branch_id"],
                    "position": row["position"],
                    "kind": row["kind"],
                    "content": row["content"][:500],
                    "content_truncated": len(row["content"]) > 500,
                    "supersedes_id": row["supersedes_id"],
                    "created_at": row["created_at"],
                }
                result["steps"].append(item)
                if len(json.dumps(result, ensure_ascii=False)) > max_chars - 50:
                    result["steps"].pop()
                    result["truncated"] = True
                    break
                if item["content_truncated"]:
                    result["truncated"] = True
            if len(rows) > len(result["steps"]):
                result["truncated"] = True
            return result
