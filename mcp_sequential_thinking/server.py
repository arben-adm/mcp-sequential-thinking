from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from typing import TypeVar

import anyio
import portalocker
from mcp import MCPError
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import INVALID_PARAMS, REQUEST_TIMEOUT, ToolAnnotations
from portalocker.exceptions import BaseLockException
from pydantic import ValidationError

# Use absolute imports when running as a script
try:
    # When installed as a package
    from .analysis import ThoughtAnalyzer
    from .logging_conf import configure_logging, log_duration
    from .models import ThoughtData, ThoughtStage
    from .schemas import (
        ClearHistoryResult,
        ExportResult,
        ImportResult,
        ProcessThoughtResult,
        SummaryResult,
    )
    from .storage import DuplicateThoughtNumberError, ThoughtStorage
except ImportError:
    # When run directly
    from mcp_sequential_thinking.analysis import ThoughtAnalyzer
    from mcp_sequential_thinking.logging_conf import configure_logging, log_duration
    from mcp_sequential_thinking.models import ThoughtData, ThoughtStage
    from mcp_sequential_thinking.schemas import (
        ClearHistoryResult,
        ExportResult,
        ImportResult,
        ProcessThoughtResult,
        SummaryResult,
    )
    from mcp_sequential_thinking.storage import DuplicateThoughtNumberError, ThoughtStorage

logger = configure_logging("sequential-thinking.server")

_T = TypeVar("_T")

SERVER_INSTRUCTIONS = (
    "Records and structures a sequential thinking process across five stages "
    "(Problem Definition, Research, Analysis, Synthesis, Conclusion). It "
    "provides an audit trail, structural analysis (progress, lexically "
    "related thoughts, stage coverage) and session export/import. It does "
    "not improve or judge the quality of the reasoning itself."
)

mcp = MCPServer(
    "mcp-sequential-thinking",
    version="0.7.0",
    instructions=SERVER_INSTRUCTIONS,
)

storage_dir = os.environ.get("MCP_STORAGE_DIR", None)
storage = ThoughtStorage(storage_dir)

# B6: permissive by default (backward jumps/skips are legitimate thinking
# moves and only get a warning). --strict-stages / setting this True turns
# a stage skip or regression on the mainline into a rejection instead.
strict_stages = False


async def _call_storage(fn: Callable[..., _T], *args: object, **kwargs: object) -> _T:
    """Run a blocking ThoughtStorage call off the event loop (B7 fix).

    Every ThoughtStorage method takes the same in-process lock, so even a
    "fast" read must go through here too — otherwise it can still stall
    behind a slow write holding the lock on a worker thread, which is how a
    handful of concurrent process_thought calls turned into a multi-minute
    hang. A lock that can't be acquired within its timeout is surfaced as a
    clear protocol error instead of blocking indefinitely.
    """
    try:
        return await anyio.to_thread.run_sync(lambda: fn(*args, **kwargs))
    except BaseLockException as e:
        raise MCPError(
            code=REQUEST_TIMEOUT,
            message=f"Storage is locked by another operation and did not free up in time: {e}",
        ) from e


@mcp.tool(
    annotations=ToolAnnotations(
        title="Process Thought",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
    ),
)
async def process_thought(
    thought: str,
    total_thoughts: int,
    next_thought_needed: bool,
    stage: str,
    thought_number: int | None = None,
    tags: list[str] | None = None,
    axioms_used: list[str] | None = None,
    assumptions_challenged: list[str] | None = None,
    is_revision: bool = False,
    revises_thought_number: int | None = None,
    branch_from_thought: int | None = None,
    branch_id: str | None = None,
    ctx: Context | None = None,
) -> ProcessThoughtResult:
    """Record one thought in the sequential-thinking audit trail.

    Validates and stores the thought (stage name, revision/branch
    consistency, per-line uniqueness of thought_number), then returns
    structural analysis: stage-order warnings, thoughts that are lexically
    related to this one, and progress counters. This does not evaluate,
    critique, or improve the reasoning — it only records and structures it.

    Args:
        thought: The content of the thought
        total_thoughts: The total expected thoughts in the sequence
        next_thought_needed: Whether more thoughts are needed after this one
        stage: The thinking stage (Problem Definition, Research, Analysis, Synthesis, Conclusion)
        thought_number: The sequence number of this thought. Omit to have
            the server assign the next free number on this line (the
            mainline, or the given branch_id).
        tags: Optional keywords or categories for the thought
        axioms_used: Optional list of principles or axioms used in this thought
        assumptions_challenged: Optional list of assumptions challenged by this thought
        is_revision: Whether this thought revises an earlier thought
        revises_thought_number: The number of the earlier thought being
            revised (required if is_revision is true)
        branch_from_thought: The thought number this thought branches from,
            to explore an alternative path
        branch_id: Identifier for the branch (letters, digits, '-', '_'; max
            64 chars; requires branch_from_thought)
        ctx: MCP request context, used to report progress

    Returns:
        Structured analysis of the recorded thought, including any stage-order warnings.
    """
    tags = tags or []
    axioms_used = axioms_used or []
    assumptions_challenged = assumptions_challenged or []

    op_name = f"process_thought #{thought_number if thought_number is not None else '(auto)'}"
    with log_duration(logger, op_name):
        if thought_number is None:
            thought_number = await _call_storage(
                storage.next_thought_number, branch_id, branch_from_thought
            )

        if ctx:
            await ctx.report_progress(thought_number - 1, total_thoughts)

        try:
            thought_stage = ThoughtStage.from_string(stage)
            thought_data = ThoughtData(
                thought=thought,
                thought_number=thought_number,
                total_thoughts=total_thoughts,
                next_thought_needed=next_thought_needed,
                stage=thought_stage,
                tags=tags,
                axioms_used=axioms_used,
                assumptions_challenged=assumptions_challenged,
                is_revision=is_revision,
                revises_thought_number=revises_thought_number,
                branch_from_thought=branch_from_thought,
                branch_id=branch_id,
            )
        except (ValueError, ValidationError) as e:
            # Protocol/validation error: bad parameters, not a runtime
            # failure the model could learn from by retrying blindly.
            raise MCPError(code=INVALID_PARAMS, message=str(e)) from e

        existing_thoughts = await _call_storage(storage.get_all_thoughts)
        transition_issue = ThoughtAnalyzer.detect_stage_transition_issue(
            thought_data, existing_thoughts
        )
        warnings: list[str] = []
        if transition_issue:
            if strict_stages:
                raise MCPError(code=INVALID_PARAMS, message=transition_issue)
            warnings.append(transition_issue)

        try:
            await _call_storage(storage.add_thought, thought_data)
        except DuplicateThoughtNumberError as e:
            raise MCPError(code=INVALID_PARAMS, message=str(e)) from e
        except MCPError:
            raise
        except Exception as e:
            logger.error(f"Storage error while recording thought #{thought_number}: {e}")
            raise ToolError(f"Could not save thought #{thought_number}: {e}") from e

        all_thoughts = await _call_storage(storage.get_all_thoughts)
        return ThoughtAnalyzer.analyze_thought(thought_data, all_thoughts, warnings=warnings)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Generate Summary",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
    ),
)
async def generate_summary() -> SummaryResult:
    """Summarize the recorded thinking process.

    Includes the actual thought content (excerpts per stage), aggregated
    challenged assumptions, open branches without a concluding thought, and
    revision chains, plus structural statistics (stage/branch/tag counts,
    stage coverage). This is a deterministic extraction from the recorded
    thoughts — it does not generate new reasoning or judge its quality.

    Returns:
        The summary (content + structure sections), or a "no thoughts recorded yet" message.
    """
    with log_duration(logger, "generate_summary"):
        all_thoughts = await _call_storage(storage.get_all_thoughts)
        return ThoughtAnalyzer.generate_summary(all_thoughts)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Clear History",
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=True,
    ),
)
async def clear_history() -> ClearHistoryResult:
    """Permanently delete all recorded thoughts in the current session.

    Irreversible: export the session first if it's worth keeping.

    Returns:
        Status message with the number of thoughts that were cleared.
    """
    with log_duration(logger, "clear_history"):
        existing = await _call_storage(storage.get_all_thoughts)
        cleared_count = len(existing)
        try:
            await _call_storage(storage.clear_history)
        except MCPError:
            raise
        except Exception as e:
            logger.error(f"Error clearing history: {e}")
            raise ToolError(f"Could not clear history: {e}") from e

        return ClearHistoryResult(
            status="success", message="Thought history cleared", cleared_count=cleared_count
        )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Export Session",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
    ),
)
async def export_session(file_path: str) -> ExportResult:
    """Export the current session to a file.

    file_path is confined to the storage directory's exports/
    subdirectory — absolute paths and '..' traversal outside it are
    rejected.

    Args:
        file_path: Destination path, resolved against the exports/ directory

    Returns:
        Status message with the exported thought count.
    """
    with log_duration(logger, f"export_session({file_path})"):
        try:
            await _call_storage(storage.export_session, file_path)
        except (ValueError, KeyError) as e:
            raise MCPError(code=INVALID_PARAMS, message=str(e)) from e
        except MCPError:
            raise
        except Exception as e:
            logger.error(f"Error exporting session: {e}")
            raise ToolError(f"Could not export session: {e}") from e

        count = len(await _call_storage(storage.get_all_thoughts))
        return ExportResult(
            status="success",
            message=f"Session exported to {file_path}",
            thought_count=count,
            file_path=file_path,
        )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Import Session",
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
    ),
)
async def import_session(file_path: str) -> ImportResult:
    """Import a session from a file, REPLACING the current session (not appending).

    file_path is confined to the storage directory's exports/
    subdirectory — absolute paths and '..' traversal outside it are
    rejected.

    Args:
        file_path: Source path, resolved against the exports/ directory

    Returns:
        Status message with the imported thought count.
    """
    with log_duration(logger, f"import_session({file_path})"):
        try:
            await _call_storage(storage.import_session, file_path)
        except FileNotFoundError as e:
            # The model can adapt (list/export first, pick a real path) —
            # this is an execution-time condition, not a malformed call.
            raise ToolError(str(e)) from e
        except (ValueError, KeyError) as e:
            raise MCPError(code=INVALID_PARAMS, message=str(e)) from e
        except MCPError:
            raise
        except Exception as e:
            logger.error(f"Error importing session: {e}")
            raise ToolError(f"Could not import session: {e}") from e

        count = len(await _call_storage(storage.get_all_thoughts))
        return ImportResult(
            status="success",
            message=f"Session imported from {file_path}",
            thought_count=count,
        )


def _health_check() -> int:
    """Check the storage path, its writability, and that the session lock
    can be acquired (B7 observability). Prints a human-readable report.

    Returns:
        int: Process exit code (0 healthy, 1 unhealthy).
    """
    healthy = True
    print(f"storage_dir: {storage.storage_dir}")

    if not storage.storage_dir.exists():
        print("  FAIL: storage directory does not exist")
        healthy = False
    elif not os.access(storage.storage_dir, os.W_OK):
        print("  FAIL: storage directory is not writable")
        healthy = False
    else:
        print("  OK: storage directory exists and is writable")

    try:
        with portalocker.Lock(storage.lock_file, timeout=2):
            pass
        print(f"  OK: session lock acquirable ({storage.lock_file})")
    except (BaseLockException, OSError) as e:
        # OSError also covers the directory-missing/unwritable cases above:
        # opening the lock file fails outright rather than raising a lock
        # timeout, and this check must report that cleanly too instead of
        # letting the exception escape _health_check.
        print(f"  FAIL: could not acquire session lock: {e}")
        healthy = False

    print(f"  thoughts recorded: {len(storage.thought_history)}")
    print("HEALTHY" if healthy else "UNHEALTHY")
    return 0 if healthy else 1


def main() -> None:
    """Entry point for the MCP server."""
    global strict_stages

    parser = argparse.ArgumentParser(prog="mcp-sequential-thinking")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="Transport to serve on (default: stdio)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind host for sse/streamable-http")
    parser.add_argument("--port", type=int, default=8000, help="Bind port for sse/streamable-http")
    parser.add_argument(
        "--strict-stages",
        action="store_true",
        help="Reject stage skips/regressions on the mainline instead of just warning (B6)",
    )
    parser.add_argument(
        "--health",
        action="store_true",
        help="Check storage path, writability and lock, print the result, and exit",
    )
    args = parser.parse_args()

    strict_stages = args.strict_stages

    if args.health:
        sys.exit(_health_check())

    logger.info("Starting Sequential Thinking MCP server")

    # Ensure UTF-8 encoding for stdin/stdout
    if hasattr(sys.stdout, "buffer") and sys.stdout.encoding != "utf-8":
        import io

        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
    if hasattr(sys.stdin, "buffer") and sys.stdin.encoding != "utf-8":
        import io

        sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", line_buffering=True)

    # Flush stdout to ensure no buffered content remains
    sys.stdout.flush()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport=args.transport, host=args.host, port=args.port)


if __name__ == "__main__":
    # When running the script directly, ensure we're in the right directory.
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    logger.info(f"Python version: {sys.version}")
    logger.info(f"Current working directory: {os.getcwd()}")
    logger.info(f"Script directory: {os.path.dirname(os.path.abspath(__file__))}")
    logger.info(f"Parent directory added to path: {parent_dir}")

    main()
