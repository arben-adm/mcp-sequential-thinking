import multiprocessing
import sqlite3
from contextlib import closing
from uuid import uuid4

import pytest

from mcp_sequential_thinking.sessions import Completion, SessionError, SessionRepository, StepInput


def create(tmp_path):
    repository = SessionRepository(str(tmp_path))
    session = repository.create_session("Debug a stalled request", "create")
    return repository, session["session_id"]


def test_session_uuid_revision_restart_and_finalization(tmp_path):
    repository, session_id = create(tmp_path)
    first = repository.add_step(
        session_id, StepInput(content="Hypothesis: database", kind="assumption"), "one"
    )
    revised = repository.add_step(
        session_id,
        StepInput(
            content="Database ruled out", kind="observation", supersedes_step_id=first["step_id"]
        ),
        "two",
    )
    repository = SessionRepository(str(tmp_path))
    rows = repository.read_session(session_id)["steps"]
    assert [row["id"] for row in rows] == [first["step_id"], revised["step_id"]]
    assert [row["superseded"] for row in rows] == [True, False]
    assert [
        row["id"] for row in repository.read_session(session_id, active_only=True)["steps"]
    ] == [revised["step_id"]]
    completion = Completion(
        outcome="Inspect client",
        evidence_step_ids=[revised["step_id"]],
        next_actions=["Trace client retries"],
    )
    with pytest.raises(SessionError, match="CONFLICT"):
        repository.finalize_session(session_id, completion, 1, "final")
    final = repository.finalize_session(session_id, completion, 2, "final")
    assert final["version"] == 3
    assert repository.finalize_session(session_id, completion, 2, "final") == final
    with pytest.raises(SessionError, match="SESSION_FINALIZED"):
        repository.add_step(session_id, StepInput(content="new"), "three")
    assert repository.read_session(session_id)["completion"]["outcome"] == "Inspect client"


def test_idempotency_and_session_isolation(tmp_path):
    repository, session_id = create(tmp_path)
    other = repository.create_session("Other", "other")["session_id"]
    step = StepInput(content="original")
    first = repository.add_step(session_id, step, "repeat")
    assert repository.add_step(session_id, step, "repeat") == first
    with pytest.raises(SessionError, match="IDEMPOTENCY_CONFLICT"):
        repository.add_step(session_id, StepInput(content="changed"), "repeat")
    with pytest.raises(SessionError, match="INVALID_REFERENCE"):
        repository.add_step(
            other, StepInput(content="bad parent", parent_step_id=first["step_id"]), "bad"
        )
    with pytest.raises(SessionError, match="INVALID_REFERENCE"):
        repository.finalize_session(
            other, Completion(evidence_step_ids=[first["step_id"]]), 0, "bad-final"
        )
    assert repository.read_session(other)["steps"] == []
    assert len(repository.read_session(session_id)["steps"]) == 1
    assert len(repository.list_sessions()["sessions"]) == 2


def test_branch_origin_and_branch_revision(tmp_path):
    repository, session_id = create(tmp_path)
    first = repository.add_step(session_id, StepInput(content="root"), "one")
    branch = repository.add_step(
        session_id,
        StepInput(content="option", branch_id="alternative", branch_from_step_id=first["step_id"]),
        "two",
    )
    revision = repository.add_step(
        session_id,
        StepInput(
            content="better option", branch_id="alternative", supersedes_step_id=branch["step_id"]
        ),
        "three",
    )
    assert revision["position"] == 2
    with pytest.raises(SessionError, match="INVALID_REFERENCE"):
        repository.add_step(
            session_id,
            StepInput(
                content="move fork",
                branch_id="alternative",
                branch_from_step_id=revision["step_id"],
            ),
            "bad",
        )
    with pytest.raises(SessionError, match="INVALID_REFERENCE"):
        repository.add_step(
            session_id, StepInput(content="missing", parent_step_id=uuid4()), "bad2"
        )


def test_database_constraints_and_deletion(tmp_path):
    repository, session_id = create(tmp_path)
    first = repository.add_step(session_id, StepInput(content="root"), "one")
    repository.add_step(
        session_id,
        StepInput(
            content="child",
            branch_id="alternative",
            branch_from_step_id=first["step_id"],
            parent_step_id=first["step_id"],
        ),
        "two",
    )
    with repository._connection() as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        for branch in (None, "main"):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO steps VALUES(?,?,?,?,?,?,?,?,?,?,NULL)",
                    (
                        str(uuid4()),
                        session_id,
                        branch,
                        1,
                        "duplicate",
                        "note",
                        None,
                        None,
                        "now",
                        "[]",
                    ),
                )
    with pytest.raises(SessionError, match="CONFLICT"):
        repository.delete_session(session_id, 1, "delete")
    result = repository.delete_session(session_id, 2, "delete")
    assert result["deleted_steps"] == 2
    assert repository.delete_session(session_id, 2, "delete") == result
    with pytest.raises(SessionError, match="UNKNOWN_SESSION"):
        repository.read_session(session_id)
    with repository._connection() as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def _session_writer(directory, session_id, barrier, prefix):
    repository = SessionRepository(directory)
    barrier.wait(timeout=10)
    for n in range(100):
        repository.add_step(session_id, StepInput(content=f"{prefix}-{n}"), f"{prefix}-{n}")


def test_two_processes_200_steps(tmp_path):
    repository, session_id = create(tmp_path)
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    processes = [
        context.Process(target=_session_writer, args=(str(tmp_path), session_id, barrier, prefix))
        for prefix in ("a", "b")
    ]
    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(20)
        assert [p.exitcode for p in processes] == [0, 0]
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join()
    with repository._connection() as connection:
        rows = connection.execute("SELECT id,position FROM steps").fetchall()
    assert len(rows) == len({row["id"] for row in rows}) == 200
    assert sorted(row["position"] for row in rows) == list(range(1, 201))
    assert repository.read_session(session_id)["version"] == 200


def _commit_without_response(directory, session_id):
    import os

    repository = SessionRepository(directory)
    repository.add_step(session_id, StepInput(content="committed"), "lost-response")
    os._exit(17)


def test_process_exit_after_commit_before_response(tmp_path):
    repository, session_id = create(tmp_path)
    process = multiprocessing.get_context("spawn").Process(
        target=_commit_without_response, args=(str(tmp_path), session_id)
    )
    process.start()
    process.join(10)
    assert process.exitcode == 17
    retry = repository.add_step(session_id, StepInput(content="committed"), "lost-response")
    rows = repository.read_session(session_id)["steps"]
    assert [row["id"] for row in rows] == [retry["step_id"]]
    assert repository.read_session(session_id)["version"] == 1


def test_pagination_returns_all_steps_and_honors_budget(tmp_path):
    import json

    repository, session_id = create(tmp_path)
    expected = [
        repository.add_step(session_id, StepInput(content="x" * 100), str(n))["step_id"]
        for n in range(30)
    ]
    seen, cursor = [], 0
    while cursor is not None:
        result = repository.read_session(session_id, cursor=cursor, max_chars=2000)
        assert len(json.dumps(result, ensure_ascii=False)) <= 2000
        seen.extend(row["id"] for row in result["steps"])
        cursor = result["cursor"]
    assert seen == expected


def test_legacy_migration_preserves_ids_bytes_and_naive_timestamp(tmp_path):
    from mcp_sequential_thinking.models import ThoughtData, ThoughtStage
    from mcp_sequential_thinking.storage import ThoughtStorage

    store = ThoughtStorage(str(tmp_path))
    first = ThoughtData(
        thought="old",
        thought_number=1,
        total_thoughts=10,
        next_thought_needed=True,
        stage=ThoughtStage.ANALYSIS,
        timestamp="2020-01-01T12:00:00",
    )
    store.add_thought(first)
    store.add_thought(
        ThoughtData(
            thought="revision",
            thought_number=2,
            total_thoughts=10,
            next_thought_needed=True,
            stage=ThoughtStage.ANALYSIS,
            is_revision=True,
            revises_thought_number=1,
        )
    )
    original = store.current_session_file.read_bytes()
    repository = SessionRepository(str(tmp_path))
    result = repository.migrate_legacy()
    assert result["session_id"] == "legacy"
    assert store.current_session_file.read_bytes() == original
    rows = repository.read_session("legacy")["steps"]
    assert rows[0]["id"] == str(first.id)
    assert rows[0]["created_at"] == first.timestamp
    assert rows[1]["supersedes_id"] == str(first.id)
    assert SessionRepository(str(tmp_path)).migrate_legacy() == result
    assert len(repository.read_session("legacy")["steps"]) == 2
    assert any(path.read_bytes() == original for path in tmp_path.glob("*.pre-sqlite.*"))


def test_conflicting_legacy_migration_preserves_original(tmp_path):
    import json

    from mcp_sequential_thinking.models import ThoughtData, ThoughtStage

    item = ThoughtData(
        thought="old",
        thought_number=1,
        total_thoughts=1,
        next_thought_needed=False,
        stage=ThoughtStage.ANALYSIS,
    ).to_dict(True)
    source = tmp_path / "current_session.json"
    source.write_text(json.dumps({"thoughts": [item, item]}))
    original = source.read_bytes()
    repository = SessionRepository(str(tmp_path))
    with pytest.raises(ValueError):
        repository.migrate_legacy()
    assert source.read_bytes() == original
    assert repository.list_sessions()["sessions"] == []


def _crash_migration(directory, after_commit):
    import os
    from contextlib import contextmanager

    repository = SessionRepository(directory)
    original_write = repository._write

    @contextmanager
    def crash_write():
        with original_write() as connection:
            yield connection
            if not after_commit:
                os._exit(18)
        os._exit(19)

    repository._write = crash_write
    repository.migrate_legacy()


@pytest.mark.parametrize("after_commit", [False, True])
def test_migration_process_exit_is_atomic(tmp_path, after_commit):
    import json

    from mcp_sequential_thinking.models import ThoughtData, ThoughtStage

    item = ThoughtData(
        thought="old",
        thought_number=1,
        total_thoughts=1,
        next_thought_needed=False,
        stage=ThoughtStage.ANALYSIS,
    ).to_dict(True)
    source = tmp_path / "current_session.json"
    source.write_text(json.dumps({"thoughts": [item]}))
    original = source.read_bytes()
    process = multiprocessing.get_context("spawn").Process(
        target=_crash_migration, args=(str(tmp_path), after_commit)
    )
    process.start()
    process.join(10)
    assert process.exitcode == (19 if after_commit else 18)
    repository = SessionRepository(str(tmp_path))
    assert len(repository.list_sessions()["sessions"]) == int(after_commit)
    repository.migrate_legacy()
    assert [row["id"] for row in repository.read_session("legacy")["steps"]] == [item["id"]]
    assert source.read_bytes() == original


def test_full_snapshot_restores_new_writes_and_retry_keys(tmp_path):
    from mcp_sequential_thinking.backup import create_snapshot, restore_snapshot

    repository, session_id = create(tmp_path / "source")
    written = repository.add_step(session_id, StepInput(content="after migration"), "one")
    repository.finalize_session(session_id, Completion(outcome="done"), 1, "final")
    snapshot = tmp_path / "snapshot.sqlite3"
    create_snapshot(tmp_path / "source", snapshot)
    restore_snapshot(snapshot, tmp_path / "restored")
    restored = SessionRepository(str(tmp_path / "restored"))
    assert restored.read_session(session_id) == repository.read_session(session_id)
    assert restored.add_step(session_id, StepInput(content="after migration"), "one") == written
    before = snapshot.read_bytes()
    with pytest.raises(FileExistsError):
        create_snapshot(tmp_path / "source", snapshot)
    assert snapshot.read_bytes() == before
    with pytest.raises(FileExistsError):
        restore_snapshot(snapshot, tmp_path / "restored")


def test_ephemeral_repository_creates_no_files_and_loses_state(tmp_path):
    from mcp_sequential_thinking.legacy import LegacyAdapter

    repository = SessionRepository(str(tmp_path / "unused"), ephemeral=True)
    adapter = LegacyAdapter(repository)
    session = repository.create_session("Transient", "create")
    assert session["storage"] == "memory_only"
    repository.add_step(session["session_id"], StepInput(content="private transient note"), "one")
    with pytest.raises(SessionError):
        adapter.export_session("not-created.json")
    adapter.close()
    repository.close()
    assert list(tmp_path.iterdir()) == []
    fresh = SessionRepository(ephemeral=True)
    assert fresh.list_sessions()["sessions"] == []
    fresh.close()


def test_resume_prioritizes_active_decision_and_next_action(tmp_path):
    repository, session_id = create(tmp_path)
    old = repository.add_step(session_id, StepInput(content="Use A", kind="decision"), "old")
    current = repository.add_step(
        session_id,
        StepInput(content="Use B", kind="decision", supersedes_step_id=old["step_id"]),
        "current",
    )
    action = repository.add_step(
        session_id, StepInput(content="Benchmark B", kind="next_action"), "action"
    )
    for number in range(30):
        repository.add_step(session_id, StepInput(content=f"Observation {number}"), str(number))
    resume = repository.resume_session(session_id)
    ids = [step["id"] for step in resume["steps"]]
    assert ids[:2] == [current["step_id"], action["step_id"]]
    assert old["step_id"] not in ids
    assert resume["truncated"]
    assert resume["goal"] == "Debug a stalled request"


def _old_exclusive_writer(directory):
    from pathlib import Path

    import portalocker

    try:
        with portalocker.Lock(Path(directory) / "current_session.lock", timeout=0.2):
            (Path(directory) / "old-writer-mutated").write_text("bad")
    except portalocker.exceptions.BaseLockException:
        return
    raise AssertionError("old writer acquired lock during new-server lifetime")


def test_legacy_lifetime_guard_blocks_real_old_exclusive_writer(tmp_path):
    from mcp_sequential_thinking.legacy import LegacyAdapter

    repository = SessionRepository(str(tmp_path))
    adapter = LegacyAdapter(repository)
    try:
        process = multiprocessing.get_context("spawn").Process(
            target=_old_exclusive_writer, args=(str(tmp_path),)
        )
        process.start()
        process.join(10)
        assert process.exitcode == 0
        assert not (tmp_path / "old-writer-mutated").exists()
    finally:
        adapter.close()


def test_sqlite_future_schema_preserves_bytes(tmp_path):
    repository = SessionRepository(str(tmp_path))
    with repository._connection() as connection:
        connection.execute("PRAGMA user_version=999")
    path = tmp_path / "worklog.sqlite3"
    original = path.read_bytes()
    with pytest.raises(SessionError, match="UNSUPPORTED_SCHEMA"):
        SessionRepository(str(tmp_path))
    assert path.read_bytes() == original


def test_finalize_race_includes_write_or_rejects_version(tmp_path):
    import concurrent.futures
    import threading

    repository, session_id = create(tmp_path)
    barrier = threading.Barrier(2)

    def write():
        barrier.wait(timeout=5)
        try:
            return repository.add_step(session_id, StepInput(content="concurrent"), "write")
        except SessionError as error:
            return error.code

    def finalize():
        barrier.wait(timeout=5)
        try:
            return repository.finalize_session(session_id, Completion(outcome="done"), 0, "final")
        except SessionError as error:
            return error.code

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(write), pool.submit(finalize)
        outcomes = [first.result(), second.result()]
    assert sum(isinstance(result, dict) for result in outcomes) == 1
    assert any(code in outcomes for code in ("CONFLICT", "SESSION_FINALIZED"))
    assert repository.read_session(session_id)["version"] == 1


def test_busy_timeout_is_retryable_without_mutation(tmp_path):
    repository, session_id = create(tmp_path)
    with closing(sqlite3.connect(repository.path, isolation_level=None)) as blocker:
        blocker.execute("BEGIN IMMEDIATE")
        try:
            with pytest.raises(SessionError) as caught:
                repository.add_step(session_id, StepInput(content="Retry me"), "busy")
            assert caught.value.code == "STORAGE_BUSY"
        finally:
            blocker.rollback()
    assert repository.read_session(session_id)["steps"] == []
    saved = repository.add_step(session_id, StepInput(content="Retry me"), "busy")
    assert saved == repository.add_step(session_id, StepInput(content="Retry me"), "busy")


@pytest.mark.parametrize("view", ["read_session", "resume_session"])
def test_escaped_title_cannot_exceed_read_budget(tmp_path, view):
    repository = SessionRepository(str(tmp_path))
    session = repository.create_session("\x01" * 500, "escaped-title")
    with pytest.raises(SessionError) as caught:
        getattr(repository, view)(session["session_id"], max_chars=1000)
    assert caught.value.code == "RESPONSE_LIMIT"
    import json

    result = getattr(repository, view)(session["session_id"], max_chars=12000)
    assert len(json.dumps(result, ensure_ascii=False)) <= 12000


def test_large_legacy_note_is_fully_readable_in_bounded_chunks(tmp_path):
    import json

    from mcp_sequential_thinking.legacy import LegacyAdapter
    from mcp_sequential_thinking.models import ThoughtStage

    repository = SessionRepository(str(tmp_path))
    adapter = LegacyAdapter(repository)
    original = "large note 😀 " * 7000
    try:
        step, _, _ = adapter.record_thought(
            thought=original,
            total_thoughts=1,
            next_thought_needed=False,
            stage=ThoughtStage.ANALYSIS,
        )
        with pytest.raises(SessionError, match="RESPONSE_LIMIT"):
            repository.read_session("legacy", step_id=str(step.id), max_chars=50000)
        offset, pieces = 0, []
        while offset is not None:
            page = repository.read_session(
                "legacy",
                step_id=str(step.id),
                content_offset=offset,
                content_chars=4000,
            )
            assert len(json.dumps(page, ensure_ascii=False)) <= 12000
            item = page["steps"][0]
            assert item["content_total_chars"] == len(original)
            pieces.append(item["content"])
            offset = item["next_content_offset"]
        assert "".join(pieces) == original
    finally:
        adapter.close()
        repository.close()
