"""Installed-package smoke test. Run outside the source checkout."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client

import mcp_sequential_thinking


async def main() -> None:
    checkout = os.environ.get("SMOKE_SOURCE_CHECKOUT")
    if checkout:
        assert not Path(mcp_sequential_thinking.__file__).resolve().is_relative_to(Path(checkout))
    with tempfile.TemporaryDirectory() as directory:
        environment = {**os.environ, "MCP_STORAGE_DIR": directory}
        environment.pop("PYTHONPATH", None)
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "mcp_sequential_thinking.server"],
            env=environment,
            cwd=Path.cwd(),
        )
        async with Client(stdio_client(parameters), raise_exceptions=False) as client:
            listed = await client.list_tools()
            assert len(listed.tools) == 11
            created = await client.call_tool(
                "create_session", {"title": "60-second restart demo", "request_id": "create"}
            )
            assert not created.is_error
            session_id = created.structured_content["session_id"]
            first = await client.call_tool(
                "add_step",
                {
                    "session_id": session_id,
                    "content": "SQLite transaction preserves atomic writes.",
                    "kind": "evidence",
                    "request_id": "evidence",
                },
            )
            assert not first.is_error
            step_id = first.structured_content["step_id"]
            second = await client.call_tool(
                "add_step",
                {
                    "session_id": session_id,
                    "content": "Use a local SQLite database; verify restore before release.",
                    "kind": "decision",
                    "parent_step_id": step_id,
                    "request_id": "decision",
                },
            )
            assert not second.is_error
            error = await client.call_tool(
                "add_step", {"session_id": "missing", "content": "invalid", "request_id": "missing"}
            )
            assert error.is_error and "UNKNOWN_SESSION" in error.content[0].text
            legacy = await client.call_tool(
                "process_thought",
                {
                    "thought": "Legacy API stays available.",
                    "stage": "analysis",
                    "total_thoughts": 10,
                    "next_thought_needed": True,
                },
            )
            assert not legacy.is_error
        async with Client(stdio_client(parameters), raise_exceptions=False) as client:
            resumed = await client.call_tool("read_session", {"session_id": session_id})
            assert not resumed.is_error
            assert resumed.structured_content["version"] == 2
            assert resumed.structured_content["steps"][0]["kind"] == "decision"
            repeated = await client.call_tool(
                "add_step",
                {
                    "session_id": session_id,
                    "content": "SQLite transaction preserves atomic writes.",
                    "kind": "evidence",
                    "request_id": "evidence",
                },
            )
            assert repeated.structured_content["step_id"] == step_id
            full = await client.call_tool(
                "read_session", {"session_id": session_id, "view": "steps"}
            )
            assert [row["id"] for row in full.structured_content["steps"]][0] == step_id
            assert not (await client.call_tool("generate_summary", {})).is_error
            print(
                json.dumps(
                    {
                        "version": mcp_sequential_thinking.__version__,
                        "tools": len(listed.tools),
                        "discovery_write_read_error_restart_retry": "passed",
                        "resume": resumed.structured_content,
                    },
                    ensure_ascii=False,
                )
            )


if __name__ == "__main__":
    asyncio.run(main())
