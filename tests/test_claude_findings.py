"""Regressions from the manual multi-branch MCP audit."""

import json
from uuid import uuid4

import pytest
from mcp import Client

from mcp_sequential_thinking import session_archive
from mcp_sequential_thinking.analysis import ThoughtAnalyzer, _excerpt
from mcp_sequential_thinking.models import ThoughtData, ThoughtStage
from mcp_sequential_thinking.sessions import Completion, SessionError, SessionRepository, StepInput


@pytest.mark.parametrize(
    "text",
    [
        "Der Upper Bound <2.0 bleibt bestehen.",
        "Alternative Linie: 0.7.0 unterstützt das.",
        "harter Cut in 0.8.0! Danach weiter.",
        "Wert 3.14159 ist gültig.",
    ],
)
def test_technical_excerpt(text):
    assert _excerpt(text) == text.split(" Danach")[0]
    assert _excerpt("x" * 101) == "x" * 100 + "…"


def test_branch_analysis_references():
    def thought(number, branch=None, revision=None):
        return ThoughtData(
            thought="Version 0.7.0 verwendet SQLite",
            thought_number=number,
            total_thoughts=10,
            next_thought_needed=True,
            stage=ThoughtStage.ANALYSIS,
            tags=["storage"],
            branch_id=branch,
            branch_from_thought=1 if branch else None,
            is_revision=revision is not None,
            revises_thought_number=revision,
        )

    root = thought(1)
    main = thought(2)
    branch = thought(2, "alt")
    revisions = [thought(3, revision=2)]
    notes = [root, main, branch, *revisions]
    matches = ThoughtAnalyzer.find_same_category_thoughts(root, notes)
    assert {(m.step_id, m.branch_id) for m in matches} >= {
        (str(main.id), None),
        (str(branch.id), "alt"),
    }
    chains = ThoughtAnalyzer.generate_summary(notes).content.revision_chains
    assert {(c.branch_id, c.original_thought_number, tuple(c.replaced_by)) for c in chains} == {
        (None, 2, (3,)),
    }


def populated(tmp_path):
    repo = SessionRepository(str(tmp_path))
    sid = repo.create_session("Version 0.7.0", "create")["session_id"]
    root = repo.add_step(
        sid, StepInput(content="root", sources=[{"uri": "https://example.com"}]), "one"
    )
    branch = repo.add_step(
        sid,
        StepInput(content="option", branch_id="alt", branch_from_step_id=root["step_id"]),
        "two",
    )
    repo.add_step(
        sid,
        StepInput(
            content="decision",
            kind="decision",
            branch_id="alt",
            supersedes_step_id=branch["step_id"],
        ),
        "three",
    )
    repo.finalize_session(
        sid, Completion(outcome="done", evidence_step_ids=[root["step_id"]]), 3, "final"
    )
    return repo, sid


def test_archive_roundtrip_and_no_overwrite(tmp_path):
    repo, sid = populated(tmp_path)
    before = repo.read_session(sid)
    assert session_archive.export_session(repo, "nested/session.json", sid) == 3
    with pytest.raises(SessionError, match="CONFLICT"):
        session_archive.import_session(repo, "nested/session.json", sid)
    repo.delete_session(sid, 4, "delete")
    assert session_archive.import_session(repo, "nested/session.json", sid) == 3
    assert repo.read_session(sid) == before
    assert repo.resume_session(sid)["steps"][0]["content"] == "decision"
    with repo._connection() as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    with pytest.raises(SessionError, match="SESSION_FINALIZED"):
        repo.add_step(sid, StepInput(content="root"), "one")
    # The old delete replay cannot hide an actual new deletion.
    assert repo.delete_session(sid, 4, "delete")["deleted_steps"] == 3


@pytest.mark.parametrize(
    "mutation", ["reference", "position", "origin", "completion", "version", "id"]
)
def test_archive_invalid_input_is_atomic(tmp_path, mutation):
    repo, sid = populated(tmp_path)
    session_archive.export_session(repo, "session.json", sid)
    path = tmp_path / "exports/session.json"
    archive = json.loads(path.read_text())
    if mutation == "reference":
        archive["steps"][0]["parent_step_id"] = str(uuid4())
    elif mutation == "position":
        archive["steps"][1]["position"] = 10
    elif mutation == "origin":
        archive["steps"][1]["branch_from_step_id"] = None
    elif mutation == "completion":
        archive["completion"]["evidence_step_ids"] = [str(uuid4())]
    elif mutation == "version":
        archive["version"] = 999
    else:
        archive["steps"][1]["id"] = archive["steps"][0]["id"]
    path.write_text(json.dumps(archive))
    repo.delete_session(sid, 4, "delete")
    with pytest.raises(ValueError):
        session_archive.import_session(repo, "session.json", sid)
    assert repo.list_sessions()["sessions"] == []


@pytest.mark.parametrize("operation", ["export_session", "import_session"])
def test_archive_path_and_ephemeral_guards(tmp_path, operation):
    repo, sid = populated(tmp_path)
    with pytest.raises(ValueError):
        getattr(session_archive, operation)(repo, "../../../outside.json", sid)
    memory = SessionRepository(ephemeral=True)
    try:
        with pytest.raises(SessionError):
            getattr(session_archive, operation)(memory, "archive.json", sid)
    finally:
        memory.close()


async def test_mcp_pagination_errors_and_archive(tmp_path, monkeypatch):
    from mcp_sequential_thinking import server

    repo, sid = populated(tmp_path)
    monkeypatch.setattr(server, "sessions", repo)
    async with Client(server.mcp, raise_exceptions=False) as client:
        for view in ("resume", "steps"):
            seen, cursor = [], 0
            while cursor is not None:
                result = await client.call_tool(
                    "read_session",
                    {
                        "session_id": sid,
                        "view": view,
                        "cursor": cursor,
                        "limit": 1,
                    },
                )
                assert not result.is_error
                page = result.structured_content
                assert page["completion_available"]
                assert (page["completion"] is not None) == (cursor == 0)
                seen.extend(step["id"] for step in page["steps"])
                next_cursor = page["cursor"]
                assert next_cursor is None or next_cursor > cursor
                cursor = next_cursor
            assert len(seen) == len(set(seen)) == (2 if view == "resume" else 3)
        stale = await client.call_tool(
            "delete_session",
            {
                "session_id": sid,
                "expected_version": 0,
                "request_id": "stale",
            },
        )
        assert stale.is_error
        assert "CONFLICT:" in stale.content[0].text
        assert "current_version=4" in stale.content[0].text
        for tool, extra in [
            ("add_step", {"content": "new"}),
            (
                "finalize_session",
                {
                    "completion": {},
                    "expected_version": 0,
                },
            ),
        ]:
            result = await client.call_tool(tool, {"session_id": sid, "request_id": "new", **extra})
            assert result.is_error
            assert "SESSION_FINALIZED:" in result.content[0].text
        exported = await client.call_tool(
            "export_session", {"session_id": sid, "file_path": "mcp.json"}
        )
        assert not exported.is_error
        repo.delete_session(sid, 4, "delete")
        imported = await client.call_tool(
            "import_session", {"session_id": sid, "file_path": "mcp.json"}
        )
        assert not imported.is_error
        assert imported.structured_content["session_id"] == sid


@pytest.mark.parametrize("backend", ["legacy_adapter", "jsonl"])
@pytest.mark.parametrize("tags", [[], ["stage-order"]])
async def test_german_related_thoughts_and_deprecation_via_mcp(
    tmp_path, monkeypatch, backend, tags
):
    from mcp_sequential_thinking import server
    from mcp_sequential_thinking.legacy import LegacyAdapter
    from mcp_sequential_thinking.storage import ThoughtStorage

    repo = SessionRepository(str(tmp_path))
    storage = LegacyAdapter(repo) if backend == "legacy_adapter" else ThoughtStorage(str(tmp_path))
    monkeypatch.setattr(server, "storage", storage)
    monkeypatch.setattr(server, "strict_stages", False)
    try:
        async with Client(server.mcp, raise_exceptions=False) as client:
            results = []
            for number, (text, stage) in enumerate(
                [
                    ("Datenbank sichert lokale Arbeitsnotizen", "analysis"),
                    ("sollte eine Stage-Order-Warnung auslösen", "conclusion"),
                    ("Stage-Order-Warnung funktioniert", "problem definition"),
                ],
                1,
            ):
                result = await client.call_tool(
                    "process_thought",
                    {
                        "thought": text,
                        "thought_number": number,
                        "total_thoughts": 3,
                        "next_thought_needed": number < 3,
                        "stage": stage,
                        "tags": tags if number > 1 else [],
                        "is_revision": number == 3,
                        **({"revises_thought_number": 2} if number == 3 else {}),
                    },
                )
                assert not result.is_error
                results.append(result.structured_content)
            analysis = results[-1]["analysis"]
            assert [(item["number"], item["score"]) for item in analysis["related_thoughts"]] == [
                (2, 0.6)
            ]
            assert [item["number"] for item in analysis["same_category_thoughts"]] == (
                [2] if tags else []
            )
            assert "deprecated" in results[-1]["deprecation_notice"]
            assert "create_session/add_step/read_session" in results[-1]["deprecation_notice"]
            assert analysis["total_thoughts_recorded"] == 3
            assert analysis["main_line_position"] == 2
            assert analysis["main_line_progress"] == pytest.approx(200 / 3)
            assert "not task completion" in analysis["main_line_progress_basis"]
    finally:
        if isinstance(storage, LegacyAdapter):
            storage.close()
        repo.close()


@pytest.mark.parametrize("foreign", [False, True])
async def test_finalize_rejects_invented_and_foreign_evidence_via_mcp(
    tmp_path, monkeypatch, foreign
):
    from mcp_sequential_thinking import server

    repo = SessionRepository(str(tmp_path))
    monkeypatch.setattr(server, "sessions", repo)
    sid = repo.create_session("Evidence test", "create")["session_id"]
    valid = repo.add_step(sid, StepInput(content="observation"), "step")["step_id"]
    other = repo.create_session("Other", "other")["session_id"]
    invalid = (
        repo.add_step(other, StepInput(content="foreign"), "foreign")["step_id"]
        if foreign
        else str(uuid4())
    )
    before = repo.read_session(sid)
    async with Client(server.mcp, raise_exceptions=False) as client:
        result = await client.call_tool(
            "finalize_session",
            {
                "session_id": sid,
                "expected_version": 1,
                "request_id": "final",
                "completion": {"evidence_step_ids": [valid, invalid]},
            },
        )
        assert result.is_error
        assert "INVALID_REFERENCE:" in result.content[0].text
        assert repo.read_session(sid) == before
        repaired = await client.call_tool(
            "finalize_session",
            {
                "session_id": sid,
                "expected_version": 1,
                "request_id": "final",
                "completion": {"evidence_step_ids": [valid]},
            },
        )
        assert not repaired.is_error
        assert repo.read_session(sid)["completion"]["evidence_step_ids"] == [valid]


@pytest.mark.parametrize("tool", ["export_session", "import_session"])
@pytest.mark.parametrize("explicit", [False, True])
async def test_path_error_is_actionable_and_sanitized(tmp_path, monkeypatch, tool, explicit):
    from mcp_sequential_thinking import server
    from mcp_sequential_thinking.legacy import LegacyAdapter

    repo = SessionRepository(str(tmp_path))
    adapter = LegacyAdapter(repo)
    monkeypatch.setattr(server, "sessions", repo)
    monkeypatch.setattr(server, "storage", adapter)
    sid = repo.create_session("Path test", "create")["session_id"]
    try:
        async with Client(server.mcp, raise_exceptions=False) as client:
            result = await client.call_tool(
                tool,
                {
                    "file_path": "../../../private-canary.json",
                    **({"session_id": sid} if explicit else {}),
                },
            )
            assert result.is_error
            assert "PATH_OUTSIDE_EXPORTS:" in result.content[0].text
            assert "exports/" in result.content[0].text
            assert str(tmp_path) not in result.content[0].text
            assert "private-canary" not in result.content[0].text
    finally:
        adapter.close()
        repo.close()


def test_sequence_is_a_cursor_and_position_is_branch_local(tmp_path):
    repo = SessionRepository(str(tmp_path))
    one = repo.create_session("One", "one")["session_id"]
    two = repo.create_session("Two", "two")["session_id"]
    repo.add_step(one, StepInput(content="first"), "one")
    second = repo.add_step(two, StepInput(content="second"), "two")
    page = repo.read_session(two)
    assert page["steps"][0]["position"] == second["position"] == 1
    assert page["steps"][0]["sequence"] == 2
    assert "database_cursor" in page["sequence_scope"]
