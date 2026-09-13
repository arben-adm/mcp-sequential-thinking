import asyncio
import os
import sys
import tempfile
import time
import unittest

import portalocker
import pytest
from mcp import Client, MCPError


class TestServerTools(unittest.TestCase):
    """Protocol-level tests for the MCP tool handlers, via the in-memory
    Client (real JSON-RPC round trips, no subprocess/socket)."""

    @classmethod
    def setUpClass(cls):
        # Point storage at a throwaway directory before importing the server,
        # since the module creates a ThoughtStorage at import time.
        cls._tmp = tempfile.TemporaryDirectory()
        os.environ["MCP_STORAGE_DIR"] = cls._tmp.name
        from mcp_sequential_thinking import server  # noqa: E402

        cls.server = server
        from mcp_sequential_thinking.storage import ThoughtStorage

        cls.server.storage = ThoughtStorage(cls._tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()
        os.environ.pop("MCP_STORAGE_DIR", None)

    def setUp(self):
        self.server.storage.clear_history()
        self.server.strict_stages = False

    def _call(self, name, args):
        """Call a tool via the in-memory Client and return its result.

        A protocol-level MCPError raised by a tool must be caught *inside*
        the ``async with Client(...)`` block and handed back as a plain
        return value, then re-raised outside it. Letting it propagate
        through the client's ``__aexit__`` instead has it pass through an
        internal anyio task group, which (per structured-concurrency
        semantics) wraps even a single exception in a ``BaseExceptionGroup``
        — callers would need ``except*`` instead of a plain
        ``assertRaises(MCPError)``.
        """

        async def run():
            async with Client(self.server.mcp, raise_exceptions=True) as c:
                try:
                    return await c.call_tool(name, args)
                except MCPError as e:
                    return e

        result = asyncio.run(run())
        if isinstance(result, MCPError):
            raise result
        return result

    # ------------------------------------------------------------------
    # Baseline behavior (formerly test_process_thought.py-style checks)
    # ------------------------------------------------------------------
    def test_process_thought_returns_structured_analysis(self):
        result = self._call(
            "process_thought",
            {
                "thought": "A first thought",
                "thought_number": 1,
                "total_thoughts": 2,
                "next_thought_needed": True,
                "stage": "Analysis",
            },
        )
        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content["current_thought"]["thought_number"], 1)

    def test_process_thought_omitting_optional_lists(self):
        result = self._call(
            "process_thought",
            {
                "thought": "Another thought",
                "thought_number": 1,
                "total_thoughts": 1,
                "next_thought_needed": False,
                "stage": "Conclusion",
            },
        )
        self.assertFalse(result.is_error)

    def test_process_thought_revision_returns_revision_of(self):
        self._call(
            "process_thought",
            {
                "thought": "Original take on the problem",
                "thought_number": 1,
                "total_thoughts": 3,
                "next_thought_needed": True,
                "stage": "Problem Definition",
            },
        )
        result = self._call(
            "process_thought",
            {
                "thought": "Sharper framing of the problem",
                "thought_number": 2,
                "total_thoughts": 3,
                "next_thought_needed": True,
                "stage": "Problem Definition",
                "is_revision": True,
                "revises_thought_number": 1,
            },
        )
        block = result.structured_content["analysis"]
        self.assertTrue(block["is_revision"])
        self.assertEqual(block["revised_thought"], 1)
        self.assertEqual(block["revision_of"]["thought_number"], 1)
        self.assertIn("Original take", block["revision_of"]["snippet"])

    def test_process_thought_invalid_stage_raises_mcp_error(self):
        """D: schema errors are correctable isError results without echoing inputs."""
        result = self._call(
            "process_thought",
            {
                "thought": "Bad stage",
                "thought_number": 1,
                "total_thoughts": 1,
                "next_thought_needed": False,
                "stage": "Not A Real Stage",
            },
        )
        self.assertTrue(result.is_error)
        self.assertIn("INVALID_INPUT", result.content[0].text)

    def test_process_thought_invalid_revision_params_raise_mcp_error(self):
        result = self._call(
            "process_thought",
            {
                "thought": "Bad revision",
                "thought_number": 1,
                "total_thoughts": 1,
                "next_thought_needed": False,
                "stage": "Conclusion",
                "is_revision": True,  # missing revises_thought_number
            },
        )
        self.assertTrue(result.is_error)

    # ------------------------------------------------------------------
    # B1: duplicate thought_number rejected; omitted number auto-assigned
    # ------------------------------------------------------------------
    def test_duplicate_thought_number_rejected(self):
        self._call(
            "process_thought",
            {
                "thought": "First",
                "thought_number": 1,
                "total_thoughts": 2,
                "next_thought_needed": True,
                "stage": "Analysis",
            },
        )
        result = self._call(
            "process_thought",
            {
                "thought": "Duplicate number",
                "thought_number": 1,
                "total_thoughts": 2,
                "next_thought_needed": False,
                "stage": "Conclusion",
            },
        )
        self.assertTrue(result.is_error)
        self.assertIn("CONFLICT", result.content[0].text)
        # Rejected call must not have grown history (B1: "silently accepted,
        # history grows to 3" is exactly what must NOT happen anymore).
        self.assertEqual(len(self.server.storage.get_all_thoughts()), 1)

    def test_thought_number_autoassigned(self):
        r1 = self._call(
            "process_thought",
            {
                "thought": "First, no number given",
                "total_thoughts": 2,
                "next_thought_needed": True,
                "stage": "Analysis",
            },
        )
        self.assertEqual(r1.structured_content["current_thought"]["thought_number"], 1)

        r2 = self._call(
            "process_thought",
            {
                "thought": "Second, no number given",
                "total_thoughts": 2,
                "next_thought_needed": False,
                "stage": "Conclusion",
            },
        )
        self.assertEqual(r2.structured_content["current_thought"]["thought_number"], 2)

    # ------------------------------------------------------------------
    # B6: permissive warns, strict_stages rejects
    # ------------------------------------------------------------------
    def test_stage_skip_warns_in_permissive_mode(self):
        self._call(
            "process_thought",
            {
                "thought": "Problem def",
                "thought_number": 1,
                "total_thoughts": 2,
                "next_thought_needed": True,
                "stage": "Problem Definition",
            },
        )
        result = self._call(
            "process_thought",
            {
                "thought": "Jump straight to synthesis",
                "thought_number": 2,
                "total_thoughts": 2,
                "next_thought_needed": False,
                "stage": "Synthesis",
            },
        )
        self.assertFalse(result.is_error)
        self.assertTrue(any("skipped" in w for w in result.structured_content["warnings"]))

    def test_stage_skip_rejected_in_strict_mode(self):
        self.server.strict_stages = True
        try:
            self._call(
                "process_thought",
                {
                    "thought": "Problem def",
                    "thought_number": 1,
                    "total_thoughts": 2,
                    "next_thought_needed": True,
                    "stage": "Problem Definition",
                },
            )
            result = self._call(
                "process_thought",
                {
                    "thought": "Jump straight to synthesis",
                    "thought_number": 2,
                    "total_thoughts": 2,
                    "next_thought_needed": False,
                    "stage": "Synthesis",
                },
            )
            self.assertTrue(result.is_error)
        finally:
            self.server.strict_stages = False

    # ------------------------------------------------------------------
    # Structured output / tool metadata
    # ------------------------------------------------------------------
    def test_all_tools_have_output_schema_and_expected_annotations(self):
        async def run():
            async with Client(self.server.mcp, raise_exceptions=True) as c:
                return await c.list_tools()

        tools = {t.name: t for t in asyncio.run(run()).tools}
        self.assertEqual(
            set(tools),
            {
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
            },
        )
        for tool in tools.values():
            self.assertIsNotNone(tool.output_schema)

        self.assertTrue(tools["clear_history"].annotations.destructive_hint)
        self.assertTrue(tools["import_session"].annotations.destructive_hint)
        self.assertTrue(tools["export_session"].annotations.destructive_hint)
        self.assertTrue(tools["generate_summary"].annotations.read_only_hint)

    def test_generate_summary_and_clear_history_round_trip(self):
        self._call(
            "process_thought",
            {
                "thought": "Only thought",
                "thought_number": 1,
                "total_thoughts": 1,
                "next_thought_needed": False,
                "stage": "Conclusion",
            },
        )
        summary = self._call("generate_summary", {})
        self.assertTrue(summary.structured_content["has_thoughts"])

        cleared = self._call("clear_history", {})
        self.assertEqual(cleared.structured_content["cleared_count"], 1)
        self.assertEqual(len(self.server.storage.get_all_thoughts()), 0)

    # ------------------------------------------------------------------
    # B7: no event-loop stall under concurrent calls
    # ------------------------------------------------------------------
    @pytest.mark.timeout(15)
    def test_concurrent_process_thought_no_deadlock(self):
        """Regression for the ~4 minute hang: N concurrent process_thought
        calls against the same session must all complete quickly instead of
        serializing behind blocking file I/O on the event loop thread."""
        n = 25

        async def run():
            async with Client(self.server.mcp, raise_exceptions=True) as c:
                start = time.monotonic()
                tasks = [
                    c.call_tool(
                        "process_thought",
                        {
                            "thought": f"Concurrent thought {i}",
                            "thought_number": i + 1,
                            "total_thoughts": n,
                            "next_thought_needed": i < n - 1,
                            "stage": "Analysis",
                        },
                    )
                    for i in range(n)
                ]
                results = await asyncio.gather(*tasks)
                return results, time.monotonic() - start

        results, elapsed = asyncio.run(run())

        self.assertEqual(len(results), n)
        for r in results:
            self.assertFalse(r.is_error)
        self.assertLess(
            elapsed, 5.0, f"{n} concurrent calls took {elapsed:.2f}s — event loop likely blocked"
        )
        self.assertEqual(len(self.server.storage.get_all_thoughts()), n)

    def test_stale_lock_raises_clean_mcp_error_not_hang(self):
        """B7: if the session lock can't be acquired within its timeout
        (e.g. an orphaned/held lock file), the call fails fast with a clear
        MCPError instead of hanging."""
        original_timeout = self.server.storage.lock_timeout
        self.server.storage.lock_timeout = 0.5
        try:
            with portalocker.Lock(self.server.storage.lock_file, timeout=5):
                start = time.monotonic()
                result = self._call(
                    "process_thought",
                    {
                        "thought": "Should fail fast, not hang",
                        "thought_number": 1,
                        "total_thoughts": 1,
                        "next_thought_needed": False,
                        "stage": "Analysis",
                    },
                )
                self.assertTrue(result.is_error)
                elapsed = time.monotonic() - start
                self.assertLess(
                    elapsed, 3.0, f"took {elapsed:.2f}s — should fail near the 0.5s lock timeout"
                )
                self.assertIn("locked", result.content[0].text.lower())
        finally:
            self.server.storage.lock_timeout = original_timeout

    # ------------------------------------------------------------------
    # export_session / import_session: success + error-mapping paths
    # ------------------------------------------------------------------
    def test_export_and_import_round_trip_via_tools(self):
        self._call(
            "process_thought",
            {
                "thought": "Exportable thought",
                "thought_number": 1,
                "total_thoughts": 1,
                "next_thought_needed": False,
                "stage": "Conclusion",
            },
        )
        export_result = self._call("export_session", {"file_path": "roundtrip.json"})
        self.assertEqual(export_result.structured_content["record_count"], 1)

        self._call("clear_history", {})
        import_result = self._call("import_session", {"file_path": "roundtrip.json"})
        self.assertEqual(import_result.structured_content["record_count"], 1)

    def test_export_path_traversal_raises_mcp_error(self):
        result = self._call("export_session", {"file_path": "../escape.json"})
        self.assertTrue(result.is_error)
        self.assertIn("PATH_OUTSIDE_EXPORTS", result.content[0].text)

    def test_import_missing_file_is_tool_error_not_mcp_error(self):
        """A missing import file is an execution-time condition (the model
        can adapt), not a malformed call — so is_error=True, not MCPError."""
        result = self._call("import_session", {"file_path": "does-not-exist.json"})
        self.assertTrue(result.is_error)
        self.assertIn("not found", result.content[0].text.lower())

    def test_clear_history_wraps_unexpected_storage_error_as_tool_error(self):
        from unittest.mock import patch

        with patch.object(
            self.server.storage, "clear_history", side_effect=OSError("disk exploded")
        ):
            result = self._call("clear_history", {})
        self.assertTrue(result.is_error)
        self.assertIn("STORAGE_ERROR", result.content[0].text)
        self.assertNotIn("disk exploded", result.content[0].text)

    def test_process_thought_wraps_unexpected_storage_error_as_tool_error(self):
        from unittest.mock import patch

        with patch.object(
            self.server.storage, "record_thought", side_effect=OSError("disk exploded")
        ):
            result = self._call(
                "process_thought",
                {
                    "thought": "Should surface as is_error, not hang or crash",
                    "thought_number": 1,
                    "total_thoughts": 1,
                    "next_thought_needed": False,
                    "stage": "Analysis",
                },
            )
        self.assertTrue(result.is_error)

    def test_clear_history_mcp_error_passes_through_unwrapped(self):
        from unittest.mock import patch

        from mcp import MCPError
        from mcp.types import INVALID_PARAMS

        with patch.object(
            self.server.storage,
            "clear_history",
            side_effect=MCPError(code=INVALID_PARAMS, message="synthetic"),
        ):
            with self.assertRaises(MCPError):
                self._call("clear_history", {})

    def test_export_mcp_error_passes_through_unwrapped(self):
        from unittest.mock import patch

        from mcp import MCPError
        from mcp.types import INVALID_PARAMS

        with patch.object(
            self.server.storage,
            "export_session",
            side_effect=MCPError(code=INVALID_PARAMS, message="synthetic"),
        ):
            with self.assertRaises(MCPError):
                self._call("export_session", {"file_path": "x.json"})

    def test_export_unexpected_error_is_tool_error(self):
        from unittest.mock import patch

        with patch.object(
            self.server.storage, "export_session", side_effect=OSError("disk exploded")
        ):
            result = self._call("export_session", {"file_path": "x.json"})
        self.assertTrue(result.is_error)
        self.assertIn("STORAGE_ERROR", result.content[0].text)
        self.assertNotIn("disk exploded", result.content[0].text)

    def test_import_bad_schema_version_is_mcp_error(self):
        """A ValueError from the storage layer (e.g. unknown schema version)
        maps to MCPError, not is_error=True (B: bad input, not bad luck)."""
        export_dir = self.server.storage.export_dir
        export_dir.mkdir(parents=True, exist_ok=True)
        (export_dir / "future.json").write_text('{"version": 99, "thoughts": []}')

        result = self._call("import_session", {"file_path": "future.json"})
        self.assertTrue(result.is_error)
        self.assertIn("INVALID_INPUT", result.content[0].text)

    def test_import_mcp_error_passes_through_unwrapped(self):
        from unittest.mock import patch

        from mcp import MCPError as MCPErrorCls
        from mcp.types import INVALID_PARAMS

        with patch.object(
            self.server.storage,
            "import_session",
            side_effect=MCPErrorCls(code=INVALID_PARAMS, message="synthetic"),
        ):
            with self.assertRaises(MCPError):
                self._call("import_session", {"file_path": "x.json"})

    def test_import_unexpected_error_is_tool_error(self):
        from unittest.mock import patch

        with patch.object(
            self.server.storage, "import_session", side_effect=OSError("disk exploded")
        ):
            result = self._call("import_session", {"file_path": "x.json"})
        self.assertTrue(result.is_error)
        self.assertIn("STORAGE_ERROR", result.content[0].text)
        self.assertNotIn("disk exploded", result.content[0].text)


class TestHealthCheckAndCli(unittest.TestCase):
    """Tests for the --health diagnostic and CLI argument wiring.

    Points the existing server module's ``storage`` at a throwaway
    directory for the duration of each test (restored after) rather than
    reloading the module — a reload would re-execute the whole module
    (re-registering tools on a fresh MCPServer) and, since Python modules
    are singletons, would also repoint the *other* test class's already-
    bound ``server`` reference.
    """

    def setUp(self):
        from mcp_sequential_thinking import server
        from mcp_sequential_thinking.storage import ThoughtStorage

        self.server = server
        self._tmp = tempfile.TemporaryDirectory()
        self._original_storage = server.storage
        server.storage = ThoughtStorage(self._tmp.name)

    def tearDown(self):
        self.server.storage = self._original_storage
        self.server.strict_stages = False
        self._tmp.cleanup()

    def test_health_check_healthy(self):
        self.assertEqual(self.server._health_check(), 0)

    def test_health_check_unhealthy_on_held_lock(self):
        with portalocker.Lock(self.server.storage.lock_file, timeout=5):
            self.assertEqual(self.server._health_check(), 1)

    def test_health_check_unhealthy_on_missing_storage_dir(self):
        import shutil

        shutil.rmtree(self.server.storage.storage_dir)
        self.assertEqual(self.server._health_check(), 1)

    @unittest.skipIf(
        sys.platform == "win32", "chmod doesn't reliably restrict directory writes on Windows"
    )
    def test_health_check_unhealthy_on_unwritable_storage_dir(self):
        os.chmod(self.server.storage.storage_dir, 0o500)
        try:
            self.assertEqual(self.server._health_check(), 1)
        finally:
            os.chmod(self.server.storage.storage_dir, 0o700)

    def test_main_health_flag_exits_with_health_check_code(self):
        from unittest.mock import patch

        with (
            patch.dict(os.environ, {"MCP_STORAGE_DIR": self._tmp.name}),
            patch.object(sys, "argv", ["mcp-sequential-thinking", "--health"]),
        ):
            with self.assertRaises(SystemExit) as ctx:
                self.server.main()
        self.assertEqual(ctx.exception.code, 0)

    def test_main_strict_stages_flag_sets_module_state(self):
        from unittest.mock import patch

        with (
            patch.dict(os.environ, {"MCP_STORAGE_DIR": self._tmp.name}),
            patch.object(sys, "argv", ["mcp-sequential-thinking", "--strict-stages", "--health"]),
        ):
            with self.assertRaises(SystemExit):
                self.server.main()
        self.assertTrue(self.server.strict_stages)


if __name__ == "__main__":
    unittest.main()
