import asyncio
import os
import tempfile
import unittest


class TestProcessThought(unittest.TestCase):
    """Test cases for the process_thought server tool."""

    @classmethod
    def setUpClass(cls):
        # Point storage at a throwaway directory before importing the server,
        # since the module creates a ThoughtStorage at import time.
        cls._tmp = tempfile.TemporaryDirectory()
        os.environ["MCP_STORAGE_DIR"] = cls._tmp.name
        from mcp_sequential_thinking import server  # noqa: E402
        cls.server = server

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()
        os.environ.pop("MCP_STORAGE_DIR", None)

    def setUp(self):
        self.server.storage.clear_history()

    def test_process_thought_returns_analysis(self):
        """Awaiting process_thought (ctx=None) returns analysis without raising
        or emitting an unawaited-coroutine RuntimeWarning."""
        result = asyncio.run(
            self.server.process_thought(
                thought="A first thought",
                thought_number=1,
                total_thoughts=2,
                next_thought_needed=True,
                stage="Analysis",
                ctx=None,
            )
        )

        self.assertIsInstance(result, dict)
        self.assertIn("thoughtAnalysis", result)

    def test_process_thought_omitting_optional_lists(self):
        """Calling without the optional list args still returns analysis
        (regression for mutable-default replacement)."""
        result = asyncio.run(
            self.server.process_thought(
                thought="Another thought",
                thought_number=1,
                total_thoughts=1,
                next_thought_needed=False,
                stage="Conclusion",
            )
        )

        self.assertIsInstance(result, dict)
        self.assertIn("thoughtAnalysis", result)


if __name__ == "__main__":
    unittest.main()
