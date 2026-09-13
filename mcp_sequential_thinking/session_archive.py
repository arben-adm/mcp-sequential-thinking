"""Portable single-session archives; imports create records and never replace them."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal
from uuid import UUID

import portalocker
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .sessions import Completion, SessionError, SessionRepository, StepInput, _json
from .storage import ThoughtStorage
from .storage_utils import MAX_IMPORT_BYTES, MAX_IMPORT_RECORDS, _atomic_write_text


class ArchiveStep(StepInput):
    id: UUID
    position: Annotated[int, Field(ge=1)]
    created_at: str


class SessionArchive(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["worklog-session"] = "worklog-session"
    version: Literal[1] = 1
    session_id: UUID
    title: Annotated[str, Field(min_length=1, max_length=500)]
    mode: Literal["freeform"]
    status: Literal["active", "finalized"]
    session_version: Annotated[int, Field(ge=0)]
    created_at: str
    completion: Completion | None
    steps: Annotated[list[ArchiveStep], Field(max_length=MAX_IMPORT_RECORDS)]

    @model_validator(mode="after")
    def validate_graph(self) -> SessionArchive:
        seen: dict[UUID, ArchiveStep] = {}
        origins: dict[str, UUID | None] = {"main": None}
        positions: dict[str, int] = {}
        superseded: set[UUID] = set()
        for step in self.steps:
            if step.id in seen or step.position != positions.get(step.branch_id, 0) + 1:
                raise ValueError("Duplicate ID or invalid branch position")
            for reference in (
                step.parent_step_id,
                step.supersedes_step_id,
                step.branch_from_step_id,
            ):
                if reference is not None and reference not in seen:
                    raise ValueError("References must point to earlier archive steps")
            if step.branch_id not in origins:
                if step.branch_from_step_id is None:
                    raise ValueError("Missing branch origin")
                origins[step.branch_id] = step.branch_from_step_id
            if origins[step.branch_id] != step.branch_from_step_id:
                raise ValueError("Inconsistent branch origin")
            if step.supersedes_step_id is not None:
                target = step.supersedes_step_id
                if target in superseded or seen[target].branch_id != step.branch_id:
                    raise ValueError("Invalid supersession")
                superseded.add(target)
            positions[step.branch_id] = step.position
            seen[step.id] = step
        if (self.status == "finalized") != (self.completion is not None):
            raise ValueError("Completion must match session status")
        if self.session_version != len(self.steps) + int(self.status == "finalized"):
            raise ValueError("Invalid session version")
        if self.completion and any(ref not in seen for ref in self.completion.evidence_step_ids):
            raise ValueError("Invalid completion evidence")
        return self


def export_session(repository: SessionRepository, file_path: str, session_id: str) -> int:
    if repository.ephemeral:
        raise SessionError("INVALID_INPUT", "File export is disabled in ephemeral mode")
    path = ThoughtStorage._ensure_within(repository.directory / "exports", file_path)
    with repository._connection() as connection:
        connection.execute("BEGIN")
        session = repository._session(connection, session_id)
        rows = connection.execute(
            "SELECT s.*, b.origin_id FROM steps s JOIN branches b "
            "ON b.session_id=s.session_id AND b.id=s.branch_id "
            "WHERE s.session_id=? ORDER BY s.rowid",
            (session_id,),
        ).fetchall()
        archive = SessionArchive(
            session_id=UUID(session_id),
            title=session["title"],
            mode=session["mode"],
            status=session["status"],
            session_version=session["version"],
            created_at=session["created_at"],
            completion=json.loads(session["completion"]) if session["completion"] else None,
            steps=[
                ArchiveStep(
                    id=row["id"],
                    position=row["position"],
                    created_at=row["created_at"],
                    content=row["content"],
                    kind=row["kind"],
                    branch_id=row["branch_id"],
                    parent_step_id=row["parent_id"],
                    supersedes_step_id=row["supersedes_id"],
                    branch_from_step_id=row["origin_id"],
                    sources=json.loads(row["sources"]),
                )
                for row in rows
            ],
        )
    serialized = archive.model_dump_json(indent=2)
    if len(serialized.encode("utf-8")) > MAX_IMPORT_BYTES:
        raise ValueError("Archive exceeds file limit; use a database snapshot")
    path.parent.mkdir(parents=True, exist_ok=True)
    with portalocker.Lock(path.with_suffix(".lock"), timeout=5):
        _atomic_write_text(path, serialized)
    return len(archive.steps)


def import_session(repository: SessionRepository, file_path: str, session_id: str) -> int:
    if repository.ephemeral:
        raise SessionError("INVALID_INPUT", "File import is disabled in ephemeral mode")
    path = ThoughtStorage._ensure_within(repository.directory / "exports", file_path)
    with portalocker.Lock(path.with_suffix(".lock"), timeout=5):
        with path.open("rb") as stream:
            raw = stream.read(MAX_IMPORT_BYTES + 1)
    if len(raw) > MAX_IMPORT_BYTES:
        raise ValueError("Archive exceeds file limit")
    archive = SessionArchive.model_validate_json(raw)
    if str(archive.session_id) != session_id:
        raise ValueError("session_id must match the archive")
    with repository._write() as connection:
        if connection.execute("SELECT 1 FROM sessions WHERE id=?", (session_id,)).fetchone():
            raise SessionError("CONFLICT", "Import into a store without this session")
        connection.execute("PRAGMA defer_foreign_keys=ON")
        connection.execute(
            "INSERT INTO sessions VALUES(?,?,?,?,?,?,?)",
            (
                session_id,
                archive.title,
                archive.mode,
                archive.status,
                archive.session_version,
                archive.created_at,
                _json(archive.completion.model_dump(mode="json")) if archive.completion else None,
            ),
        )
        branches: dict[str, Any] = {"main": None}
        for step in archive.steps:
            branches[step.branch_id] = (
                str(step.branch_from_step_id) if step.branch_from_step_id else None
            )
            connection.execute(
                "INSERT INTO steps VALUES(?,?,?,?,?,?,?,?,?,?,NULL)",
                (
                    str(step.id),
                    session_id,
                    step.branch_id,
                    step.position,
                    step.content,
                    step.kind,
                    str(step.parent_step_id) if step.parent_step_id else None,
                    str(step.supersedes_step_id) if step.supersedes_step_id else None,
                    step.created_at,
                    _json([source.model_dump() for source in step.sources]),
                ),
            )
        for branch, origin in branches.items():
            connection.execute("INSERT INTO branches VALUES(?,?,?)", (session_id, branch, origin))
        # Old retry records (e.g. from a deleted session) must never affect a restored archive.
        connection.execute(
            "DELETE FROM requests WHERE scope IN (?,?,?)",
            (
                "step:" + session_id,
                "finalize:" + session_id,
                "delete:" + session_id,
            ),
        )
    return len(archive.steps)
