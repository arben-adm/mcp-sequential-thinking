"""Real stdio subprocess contract, persistence and error semantics."""

import os
import sys

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client


@pytest.mark.asyncio
async def test_stdio_session_and_legacy_restart(tmp_path):
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_sequential_thinking.server"],
        env={**os.environ, "MCP_STORAGE_DIR": str(tmp_path)},
    )
    async with Client(stdio_client(parameters), raise_exceptions=False) as client:
        tools = await client.list_tools()
        names = {tool.name for tool in tools.tools}
        assert names == {
            "process_thought",
            "generate_summary",
            "clear_history",
            "export_session",
            "import_session",
            "create_session",
            "add_step",
            "list_sessions",
            "read_session",
            "finalize_session",
            "delete_session",
        }
        created = await client.call_tool(
            "create_session", {"title": "Restart example", "request_id": "create"}
        )
        assert not created.is_error
        session_id = created.structured_content["session_id"]
        written = await client.call_tool(
            "add_step",
            {
                "session_id": session_id,
                "content": "Use SQLite",
                "kind": "decision",
                "request_id": "step",
            },
        )
        assert not written.is_error
        step_id = written.structured_content["step_id"]
        bad = await client.call_tool(
            "add_step", {"session_id": "unknown", "content": "bad", "request_id": "bad"}
        )
        assert bad.is_error
        assert "UNKNOWN_SESSION" in bad.content[0].text
        legacy = await client.call_tool(
            "process_thought",
            {
                "thought": "legacy note",
                "total_thoughts": 10,
                "next_thought_needed": True,
                "stage": "Analysis",
            },
        )
        assert not legacy.is_error
    async with Client(stdio_client(parameters), raise_exceptions=False) as client:
        read = await client.call_tool("read_session", {"session_id": session_id})
        assert not read.is_error
        assert read.structured_content["steps"][0]["id"] == step_id
        retry = await client.call_tool(
            "add_step",
            {
                "session_id": session_id,
                "content": "Use SQLite",
                "kind": "decision",
                "request_id": "step",
            },
        )
        assert retry.structured_content["step_id"] == step_id
        assert not (await client.call_tool("generate_summary", {})).is_error
        read_legacy = await client.call_tool("read_session", {"session_id": "legacy"})
        assert read_legacy.structured_content["steps"][0]["content"] == "legacy note"
        finalized = await client.call_tool(
            "finalize_session",
            {
                "session_id": "legacy",
                "completion": {},
                "expected_version": read_legacy.structured_content["version"],
                "request_id": "finish-legacy",
            },
        )
        assert not finalized.is_error
        rejected = await client.call_tool(
            "process_thought",
            {
                "thought": "must not be written",
                "total_thoughts": 10,
                "next_thought_needed": True,
                "stage": "Analysis",
            },
        )
        assert rejected.is_error
        assert "CONFLICT:" in rejected.content[0].text
        preserved = await client.call_tool("read_session", {"session_id": "legacy"})
        assert len(preserved.structured_content["steps"]) == 1
        chunk = await client.call_tool(
            "read_session",
            {
                "session_id": "legacy",
                "step_id": preserved.structured_content["steps"][0]["id"],
                "content_offset": 0,
                "content_chars": 6,
            },
        )
        assert not chunk.is_error
        assert chunk.structured_content["steps"][0]["content"] == "legacy"
        assert chunk.structured_content["steps"][0]["next_content_offset"] == 6


@pytest.mark.asyncio
async def test_two_stdio_servers_same_storage(tmp_path):
    import asyncio

    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_sequential_thinking.server"],
        env={**os.environ, "MCP_STORAGE_DIR": str(tmp_path)},
    )
    async with (
        Client(stdio_client(parameters)) as first,
        Client(stdio_client(parameters)) as second,
    ):
        created = await first.call_tool(
            "create_session", {"title": "Shared", "request_id": "create"}
        )
        session_id = created.structured_content["session_id"]
        results = await asyncio.gather(
            *[
                client.call_tool(
                    "add_step",
                    {"session_id": session_id, "content": f"note {n}", "request_id": str(n)},
                )
                for n in range(20)
                for client in [first if n % 2 else second]
            ]
        )
        assert all(not result.is_error for result in results)
        read = await second.call_tool(
            "read_session", {"session_id": session_id, "limit": 100, "max_chars": 50000}
        )
        assert len(read.structured_content["steps"]) == 20
        assert read.structured_content["version"] == 20


@pytest.mark.asyncio
async def test_ephemeral_stdio_does_not_touch_storage_and_does_not_survive(tmp_path):
    target = tmp_path / "unused"
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_sequential_thinking.server", "--ephemeral"],
        env={**os.environ, "MCP_STORAGE_DIR": str(target)},
    )
    async with Client(stdio_client(parameters)) as client:
        created = await client.call_tool(
            "create_session", {"title": "Private", "request_id": "create"}
        )
        session_id = created.structured_content["session_id"]
        assert created.structured_content["storage"] == "memory_only"
        assert not (
            await client.call_tool(
                "add_step", {"session_id": session_id, "content": "transient", "request_id": "step"}
            )
        ).is_error
        assert (await client.call_tool("export_session", {"file_path": "no.json"})).is_error
    assert not target.exists()
    async with Client(stdio_client(parameters), raise_exceptions=False) as client:
        assert (await client.call_tool("read_session", {"session_id": session_id})).is_error
    assert not target.exists()


@pytest.mark.asyncio
async def test_schema_case_compatibility_error_redaction_and_summary_budget(tmp_path):
    import json

    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_sequential_thinking.server"],
        env={**os.environ, "MCP_STORAGE_DIR": str(tmp_path)},
    )
    async with Client(stdio_client(parameters), raise_exceptions=False) as client:
        listed = await client.list_tools()
        process_schema = next(
            tool.input_schema for tool in listed.tools if tool.name == "process_thought"
        )
        assert "Analysis" in json.dumps(process_schema)
        assert process_schema["properties"]["thought"]["maxLength"] == 100000
        for number in range(30):
            result = await client.call_tool(
                "process_thought",
                {
                    "thought": f"record {number}: " + "x" * 500,
                    "stage": "aNaLySiS",
                    "total_thoughts": 100,
                    "next_thought_needed": True,
                },
            )
            assert not result.is_error
        secret = "UNIQUE_PRIVATE_NOTE_DO_NOT_ECHO"
        bad = await client.call_tool(
            "process_thought",
            {"thought": secret, "stage": secret, "total_thoughts": 1, "next_thought_needed": False},
        )
        assert bad.is_error
        assert "INVALID_INPUT" in bad.content[0].text
        assert secret not in bad.content[0].text
        assert str(tmp_path) not in bad.content[0].text
        assert len(bad.content[0].text) < 500
        summary = await client.call_tool("generate_summary", {"max_chars": 1500})
        assert not summary.is_error
        assert summary.structured_content["truncated"]
        assert summary.structured_content["total_recorded"] == 30
        assert len(json.dumps(summary.structured_content, ensure_ascii=False)) <= 1500
