import os
import sys
from typing import List, Optional  # Optional still needed for ctx: Optional[Context]

from mcp.server.fastmcp import Context, FastMCP

# Use absolute imports when running as a script
try:
    # When installed as a package
    from .analysis import ThoughtAnalyzer
    from .logging_conf import configure_logging
    from .models import ThoughtData, ThoughtStage
    from .storage import ThoughtStorage
except ImportError:
    # When run directly
    from mcp_sequential_thinking.analysis import ThoughtAnalyzer
    from mcp_sequential_thinking.logging_conf import configure_logging
    from mcp_sequential_thinking.models import ThoughtData, ThoughtStage
    from mcp_sequential_thinking.storage import ThoughtStorage

logger = configure_logging("sequential-thinking.server")


mcp = FastMCP("sequential-thinking")

storage_dir = os.environ.get("MCP_STORAGE_DIR", None)
storage = ThoughtStorage(storage_dir)


@mcp.tool()
def process_thought(
    thought: str,
    thought_number: int,
    total_thoughts: int,
    next_thought_needed: bool,
    stage: str,
    tags: List[str] = [],
    axioms_used: List[str] = [],
    assumptions_challenged: List[str] = [],
    ctx: Optional[Context] = None,
) -> dict:
    """Add a sequential thought with its metadata.

    Args:
        thought: The content of the thought
        thought_number: The sequence number of this thought
        total_thoughts: The total expected thoughts in the sequence
        next_thought_needed: Whether more thoughts are needed after this one
        stage: The thinking stage (Problem Definition, Research, Analysis, Synthesis, Conclusion)
        tags: Optional keywords or categories for the thought
        axioms_used: Optional list of principles or axioms used in this thought
        assumptions_challenged: Optional list of assumptions challenged by this thought
        ctx: Optional MCP context object

    Returns:
        dict: Analysis of the processed thought
    """
    try:
        # Log the request
        logger.info(f"Processing thought #{thought_number}/{total_thoughts} in stage '{stage}'")

        # Report progress if context is available
        if ctx:
            ctx.report_progress(thought_number - 1, total_thoughts)

        # Convert stage string to enum
        thought_stage = ThoughtStage.from_string(stage)

        # Create thought data object with defaults for optional fields
        thought_data = ThoughtData(
            thought=thought,
            thought_number=thought_number,
            total_thoughts=total_thoughts,
            next_thought_needed=next_thought_needed,
            stage=thought_stage,
            tags=tags,
            axioms_used=axioms_used,
            assumptions_challenged=assumptions_challenged,
        )

        # Validate and store
        thought_data.validate()
        storage.add_thought(thought_data)

        # Get all thoughts for analysis
        all_thoughts = storage.get_all_thoughts()

        # Analyze the thought
        analysis = ThoughtAnalyzer.analyze_thought(thought_data, all_thoughts)

        # Log success
        logger.info(f"Successfully processed thought #{thought_number}")

        return analysis
    except Exception as e:
        logger.error(f"Error processing thought: {str(e)}")

        return {"error": str(e), "status": "failed"}


@mcp.tool()
def generate_summary() -> dict:
    """Generate a summary of the entire thinking process.

    Returns:
        dict: Summary of the thinking process
    """
    try:
        logger.info("Generating thinking process summary")

        # Get all thoughts
        all_thoughts = storage.get_all_thoughts()

        # Generate summary
        return ThoughtAnalyzer.generate_summary(all_thoughts)
    except Exception as e:
        logger.error(f"Error generating summary: {str(e)}")
        return {"error": str(e), "status": "failed"}


@mcp.tool()
def clear_history() -> dict:
    """Clear the thought history.

    Returns:
        dict: Status message
    """
    try:
        logger.info("Clearing thought history")
        storage.clear_history()
        return {"status": "success", "message": "Thought history cleared"}
    except Exception as e:
        logger.error(f"Error clearing history: {str(e)}")
        return {"error": str(e), "status": "failed"}


@mcp.tool()
def export_session(file_path: str) -> dict:
    """Export the current thinking session to a file.

    Args:
        file_path: Path to save the exported session

    Returns:
        dict: Status message
    """
    try:
        logger.info(f"Exporting session to {file_path}")
        storage.export_session(file_path)
        return {"status": "success", "message": f"Session exported to {file_path}"}
    except Exception as e:
        logger.error(f"Error exporting session: {str(e)}")
        return {"error": str(e), "status": "failed"}


@mcp.tool()
def import_session(file_path: str) -> dict:
    """Import a thinking session from a file.

    Args:
        file_path: Path to the file to import

    Returns:
        dict: Status message
    """
    try:
        logger.info(f"Importing session from {file_path}")
        storage.import_session(file_path)
        return {"status": "success", "message": f"Session imported from {file_path}"}
    except Exception as e:
        logger.error(f"Error importing session: {str(e)}")
        return {"error": str(e), "status": "failed"}


def main():
    """Entry point for the MCP server."""
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

    # Run the MCP server
    mcp.run()


if __name__ == "__main__":
    # When running the script directly, ensure we're in the right directory
    import os
    import sys

    # Add the parent directory to sys.path if needed
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    # Print debug information
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Current working directory: {os.getcwd()}")
    logger.info(f"Script directory: {os.path.dirname(os.path.abspath(__file__))}")
    logger.info(f"Parent directory added to path: {parent_dir}")

    # Run the server
    main()
