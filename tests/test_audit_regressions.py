"""Desired behavior for confirmed 2026-09-05 audit findings."""

import json
from unittest.mock import patch

import pytest

from mcp_sequential_thinking.models import ThoughtData, ThoughtStage
from mcp_sequential_thinking.storage import ThoughtStorage


def thought(number=1, **kwargs):
    return ThoughtData(
        thought="keep",
        thought_number=number,
        total_thoughts=1000,
        next_thought_needed=True,
        stage=ThoughtStage.ANALYSIS,
        **kwargs,
    )


@pytest.mark.parametrize(
    "tail", [b'{"type":"thought","thought":"broken', b'{"type":"thought","thought":"\xf0\x9f']
)
def test_tail_repair_survives_100_appends_and_restarts(tmp_path, tail):
    store = ThoughtStorage(str(tmp_path))
    first = thought()
    store.add_thought(first)
    with store.current_session_file.open("ab") as stream:
        stream.write(tail)
    expected = [first.id]
    for number in range(2, 102):
        store = ThoughtStorage(str(tmp_path))
        assert [t.id for t in store.get_all_thoughts()] == expected
        item = thought(number)
        store.add_thought(item)
        expected.append(item.id)
    assert [t.id for t in ThoughtStorage(str(tmp_path)).get_all_thoughts()] == expected


@pytest.mark.parametrize("container", [{}, "", None, 0, False])
def test_invalid_import_container_preserves_both_files(tmp_path, container):
    store = ThoughtStorage(str(tmp_path))
    store.add_thought(thought())
    store.export_dir.mkdir()
    incoming = store.export_dir / "in.json"
    incoming.write_text(json.dumps({"thoughts": container}))
    before = store.current_session_file.read_bytes(), incoming.read_bytes()
    with pytest.raises((ValueError, TypeError)):
        store.import_session("in.json")
    assert (store.current_session_file.read_bytes(), incoming.read_bytes()) == before
    assert len(store.get_all_thoughts()) == 1


@pytest.mark.parametrize("mutation", ["append", "clear", "import"])
def test_failed_persistence_does_not_publish_memory(tmp_path, mutation):
    store = ThoughtStorage(str(tmp_path))
    first = thought()
    store.add_thought(first)
    store.export_dir.mkdir()
    (store.export_dir / "in.json").write_text(json.dumps({"thoughts": []}))
    target = "append_thought_to_jsonl" if mutation == "append" else "rewrite_jsonl"
    with patch("mcp_sequential_thinking.storage." + target, side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            if mutation == "append":
                store.add_thought(thought(2))
            elif mutation == "clear":
                store.clear_history()
            else:
                store.import_session("in.json")
    assert [t.id for t in store.get_all_thoughts()] == [first.id]
    assert [t.id for t in ThoughtStorage(str(tmp_path)).get_all_thoughts()] == [first.id]


def test_future_version_preserves_original_and_refuses_start(tmp_path):
    store = ThoughtStorage(str(tmp_path))
    store.add_thought(thought())
    path = store.current_session_file
    path.write_bytes(path.read_bytes().replace(b'"version": 2', b'"version": 999'))
    before = path.read_bytes()
    with pytest.raises(ValueError, match="[Uu]nsupported"):
        ThoughtStorage(str(tmp_path))
    assert path.read_bytes() == before


@pytest.mark.parametrize("duplicate", ["id", "position"])
def test_import_duplicate_identity_or_position_rejected(tmp_path, duplicate):
    store = ThoughtStorage(str(tmp_path))
    store.add_thought(thought())
    first, second = thought(), thought(2 if duplicate == "id" else 1)
    if duplicate == "id":
        second.id = first.id
    store.export_dir.mkdir()
    (store.export_dir / "in.json").write_text(
        json.dumps({"thoughts": [first.to_dict(True), second.to_dict(True)]})
    )
    before = store.current_session_file.read_bytes()
    with pytest.raises(ValueError):
        store.import_session("in.json")
    assert store.current_session_file.read_bytes() == before


def test_explicit_invalid_uuid_is_not_replaced():
    record = thought().to_dict(True)
    record["id"] = "invalid"
    with pytest.raises(ValueError):
        ThoughtData.from_dict(record)


def test_orphan_revision_rejected(tmp_path):
    store = ThoughtStorage(str(tmp_path))
    with pytest.raises(ValueError):
        store.add_thought(thought(10, is_revision=True, revises_thought_number=9))
    assert store.get_all_thoughts() == []


def test_branch_origin_cannot_change(tmp_path):
    store = ThoughtStorage(str(tmp_path))
    for item in [thought(), thought(2), thought(3, branch_id="x", branch_from_thought=1)]:
        store.add_thought(item)
    with pytest.raises(ValueError):
        store.add_thought(thought(4, branch_id="x", branch_from_thought=2))


def test_reads_are_defensive(tmp_path):
    store = ThoughtStorage(str(tmp_path))
    store.add_thought(thought())
    store.get_all_thoughts()[0].thought = "changed"
    assert store.get_all_thoughts()[0].thought == "keep"


def _writer(directory, barrier):
    store = ThoughtStorage(directory)
    barrier.wait(timeout=10)
    for _ in range(100):
        store.record_thought(
            thought="process note",
            thought_number=None,
            total_thoughts=1000,
            next_thought_needed=True,
            stage=ThoughtStage.ANALYSIS,
        )


def test_two_processes_200_atomic_writes(tmp_path):
    import multiprocessing

    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    processes = [context.Process(target=_writer, args=(str(tmp_path), barrier)) for _ in range(2)]
    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(20)
        assert [process.exitcode for process in processes] == [0, 0]
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join()
    records = ThoughtStorage(str(tmp_path)).get_all_thoughts()
    assert len(records) == len({t.id for t in records}) == 200
    assert sorted(t.thought_number for t in records) == list(range(1, 201))


@pytest.mark.asyncio
async def test_20_parallel_protocol_writes(tmp_path, monkeypatch):
    import asyncio

    from mcp import Client

    from mcp_sequential_thinking import server

    monkeypatch.setattr(server, "storage", ThoughtStorage(str(tmp_path)))
    async with Client(server.mcp, raise_exceptions=False) as client:
        results = await asyncio.gather(
            *[
                client.call_tool(
                    "process_thought",
                    {
                        "thought": "concurrent",
                        "total_thoughts": 100,
                        "next_thought_needed": True,
                        "stage": "Analysis",
                    },
                )
                for _ in range(20)
            ]
        )
    assert all(not result.is_error for result in results)
    assert sorted(t.thought_number for t in server.storage.get_all_thoughts()) == list(range(1, 21))


@pytest.mark.parametrize("operation", ["append", "clear", "import"])
@pytest.mark.parametrize("boundary", ["fsync", "replace"])
def test_low_level_failure_reconciles_before_next_write(tmp_path, operation, boundary):
    import os

    if operation == "append" and boundary == "replace":
        # An append has no replacement boundary; test its fsync instead.
        boundary = "fsync"
    store = ThoughtStorage(str(tmp_path))
    first = thought()
    store.add_thought(first)
    store.export_dir.mkdir()
    (store.export_dir / "in.json").write_text(json.dumps({"thoughts": []}))
    original = getattr(os, boundary)
    calls = 0

    def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("injected persistence boundary failure")
        return original(*args, **kwargs)

    with patch("mcp_sequential_thinking.storage_utils.os." + boundary, side_effect=fail_once):
        with pytest.raises(OSError):
            if operation == "append":
                store.add_thought(thought(2))
            elif operation == "clear":
                store.clear_history()
            else:
                store.import_session("in.json")
    disk = ThoughtStorage(str(tmp_path)).get_all_thoughts()
    assert [t.id for t in store.get_all_thoughts()] == [t.id for t in disk]
    assert first.id in {t.id for t in disk}
    store.add_thought(thought(3))
    assert len(ThoughtStorage(str(tmp_path)).get_all_thoughts()) == len(disk) + 1


def test_partial_record_failure_repairs_before_next_write(tmp_path):
    import builtins

    store = ThoughtStorage(str(tmp_path))
    first = thought()
    store.add_thought(first)
    original = builtins.open

    class PartialWriter:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def write(self, text):
            self.stream.write(text[:30])
            self.stream.flush()
            raise OSError("partial append")

    def open_with_partial_write(path, mode="r", *args, **kwargs):
        stream = original(path, mode, *args, **kwargs)
        if mode == "a" and str(path).endswith(".jsonl"):
            return PartialWriter(stream)
        return stream

    with patch("builtins.open", side_effect=open_with_partial_write):
        with pytest.raises(OSError):
            store.add_thought(thought(2))
    assert [t.id for t in store.get_all_thoughts()] == [first.id]
    store.add_thought(thought(2))
    assert len(ThoughtStorage(str(tmp_path)).get_all_thoughts()) == 2


@pytest.mark.parametrize("argument", ["--help", "--version", "--health"])
def test_diagnostics_with_invalid_storage(tmp_path, argument):
    import os
    import subprocess
    import sys

    invalid = tmp_path / "not-a-directory"
    invalid.write_bytes(b"untouched")
    result = subprocess.run(
        [sys.executable, "-m", "mcp_sequential_thinking.server", argument],
        env={**os.environ, "MCP_STORAGE_DIR": str(invalid)},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == (1 if argument == "--health" else 0)
    assert "Traceback" not in result.stderr
    if argument == "--health":
        assert "UNHEALTHY" in result.stdout
    assert invalid.read_bytes() == b"untouched"


def test_import_has_no_storage_side_effect(tmp_path):
    import os
    import subprocess
    import sys

    target = tmp_path / "must-not-exist"
    result = subprocess.run(
        [sys.executable, "-c", "import mcp_sequential_thinking.server"],
        env={**os.environ, "MCP_STORAGE_DIR": str(target)},
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert not target.exists()


def test_legacy_missing_id_assigned_once_with_backup(tmp_path):
    store = ThoughtStorage(str(tmp_path))
    store.add_thought(thought())
    path = store.current_session_file
    records = [json.loads(line) for line in path.read_bytes().splitlines()]
    del records[1]["id"]
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
    original = path.read_bytes()
    first = ThoughtStorage(str(tmp_path)).get_all_thoughts()[0]
    second = ThoughtStorage(str(tmp_path)).get_all_thoughts()[0]
    assert first.id == second.id
    assert any(backup.read_bytes() == original for backup in tmp_path.glob("*.bak.*"))


def test_malformed_unterminated_tail_is_not_assumed_to_be_truncation(tmp_path):
    store = ThoughtStorage(str(tmp_path))
    store.add_thought(thought())
    path = store.current_session_file
    with path.open("ab") as stream:
        stream.write(b"{not valid json}")
    original = path.read_bytes()
    with pytest.raises(ValueError):
        ThoughtStorage(str(tmp_path))
    assert path.read_bytes() == original


def test_crlf_recovery_does_not_double_carriage_returns(tmp_path):
    store = ThoughtStorage(str(tmp_path))
    store.add_thought(thought())
    path = store.current_session_file
    path.write_bytes(
        path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        + b'{"type":"thought","thought":"partial'
    )
    store = ThoughtStorage(str(tmp_path))
    store.add_thought(thought(2))
    assert len(ThoughtStorage(str(tmp_path)).get_all_thoughts()) == 2
    assert b"\r\r\n" not in path.read_bytes()


def test_empty_existing_jsonl_can_accept_first_confirmed_write(tmp_path):
    (tmp_path / "current_session.jsonl").touch()
    store = ThoughtStorage(str(tmp_path))
    item = thought()
    store.add_thought(item)
    assert [t.id for t in ThoughtStorage(str(tmp_path)).get_all_thoughts()] == [item.id]


def test_revision_of_revision_resolves_to_stored_target(tmp_path):
    from mcp_sequential_thinking.analysis import ThoughtAnalyzer

    store = ThoughtStorage(str(tmp_path))
    store.add_thought(thought())
    revision = thought(2, is_revision=True, revises_thought_number=1)
    store.add_thought(revision)
    latest = thought(3, is_revision=True, revises_thought_number=2)
    store.add_thought(latest)
    result = ThoughtAnalyzer.analyze_thought(latest, store.get_all_thoughts())
    assert result.analysis.revision_of.thought_number == 2


def test_unknown_import_fields_are_not_silently_dropped(tmp_path):
    store = ThoughtStorage(str(tmp_path))
    store.add_thought(thought())
    before = store.current_session_file.read_bytes()
    store.export_dir.mkdir()
    item = thought().to_dict(True)
    item["unrecognized_content"] = "must not silently discard"
    (store.export_dir / "in.json").write_text(json.dumps({"thoughts": [item]}))
    with pytest.raises(ValueError):
        store.import_session("in.json")
    assert store.current_session_file.read_bytes() == before


def test_health_reports_invalid_sqlite_without_traceback_or_mutation(tmp_path):
    import os
    import subprocess
    import sys

    database = tmp_path / "worklog.sqlite3"
    original = b"not a sqlite database; preserve diagnostic evidence"
    database.write_bytes(original)
    result = subprocess.run(
        [sys.executable, "-m", "mcp_sequential_thinking.server", "--health"],
        env={**os.environ, "MCP_STORAGE_DIR": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 1
    assert "UNHEALTHY" in result.stdout
    assert "Traceback" not in result.stderr
    assert database.read_bytes() == original


@pytest.mark.parametrize("allow_nonlocal", [False, True])
def test_nonlocal_http_requires_explicit_operator_opt_in(tmp_path, allow_nonlocal):
    import os
    import subprocess
    import sys

    storage_dir = tmp_path / "unused"
    arguments = [
        sys.executable,
        "-m",
        "mcp_sequential_thinking.server",
        "--transport",
        "streamable-http",
        "--host",
        "0.0.0.0",
        "--ephemeral",
        "--health",
    ]
    if allow_nonlocal:
        arguments.append("--allow-nonlocal-http")
    result = subprocess.run(
        arguments,
        env={**os.environ, "MCP_STORAGE_DIR": str(storage_dir)},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == (0 if allow_nonlocal else 2)
    if allow_nonlocal:
        assert "HEALTHY" in result.stdout
    else:
        assert "requires --allow-nonlocal-http" in result.stderr
    assert not storage_dir.exists()
