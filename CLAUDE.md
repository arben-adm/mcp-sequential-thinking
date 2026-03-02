# CLAUDE.md

## Project Overview

This is the **Sequential Thinking MCP Server** — a Python-based Model Context Protocol (MCP) server that facilitates structured, progressive thinking through defined cognitive stages. It allows AI assistants to break down complex problems into sequential thoughts, track thinking progression, and generate summaries.

**Version**: 0.3.0 (pyproject.toml) / 0.5.0 (unreleased, per CHANGELOG.md)

## Tech Stack

- **Language**: Python 3.10+
- **MCP Framework**: FastMCP (`mcp[cli]>=1.2.0`)
- **Data Validation**: Pydantic (via `mcp[cli]` dependency)
- **File Locking**: portalocker (thread-safe persistence)
- **Formatting**: Black (line-length 100), isort (black profile)
- **Type Checking**: mypy (strict mode — `disallow_untyped_defs`, `disallow_incomplete_defs`)
- **Testing**: pytest + pytest-cov (unittest-style test classes)
- **Build System**: Hatchling

## Repository Structure

```
mcp-sequential-thinking/
├── mcp_sequential_thinking/       # Main package
│   ├── __init__.py                # Empty package init
│   ├── server.py                  # MCP server entry point, tool definitions
│   ├── models.py                  # Pydantic models (ThoughtData, ThoughtStage enum)
│   ├── storage.py                 # ThoughtStorage class with thread-safe persistence
│   ├── storage_utils.py           # Shared file I/O utilities (save/load with portalocker)
│   ├── analysis.py                # ThoughtAnalyzer (related thoughts, summaries)
│   ├── testing.py                 # Test-specific helpers (conditional import via importlib)
│   ├── utils.py                   # snake_case/camelCase conversion utilities
│   └── logging_conf.py            # Centralized logging configuration
├── tests/
│   ├── __init__.py
│   ├── test_models.py             # ThoughtStage and ThoughtData tests
│   ├── test_analysis.py           # ThoughtAnalyzer tests
│   └── test_storage.py            # ThoughtStorage tests
├── run_server.py                  # Convenience server runner script
├── debug_mcp_connection.py        # MCP connection debugging utility
├── pyproject.toml                 # Project config, dependencies, tool settings
├── uv.lock                        # UV lockfile
├── CHANGELOG.md                   # Version history
├── example.md                     # Customization/extension examples
├── LICENSE                        # MIT
└── .github/workflows/claude.yml   # Claude Code GitHub Action
```

## Development Setup

```bash
# Create virtual environment
uv venv
source .venv/bin/activate  # Unix

# Install with dev dependencies
uv pip install -e ".[dev]"

# Install all optional dependencies (dev + vis + web)
uv pip install -e ".[all]"
```

## Common Commands

```bash
# Run the MCP server
uv run -m mcp_sequential_thinking.server

# Run tests
pytest

# Run tests with coverage
pytest --cov=mcp_sequential_thinking

# Format code
black .
isort .

# Type check
mypy mcp_sequential_thinking
```

## Architecture & Key Patterns

### MCP Tools (server.py)

The server exposes 5 MCP tools via FastMCP:
- `process_thought` — Records and analyzes a new thought
- `generate_summary` — Summarizes the entire thinking session
- `clear_history` — Resets thought history
- `export_session` — Exports session to a JSON file
- `import_session` — Imports session from a JSON file

### Data Flow

1. Client calls `process_thought` → server creates `ThoughtData` (Pydantic model)
2. `ThoughtData` is validated automatically by Pydantic validators
3. `ThoughtStorage.add_thought()` appends to in-memory list and persists to `~/.mcp_sequential_thinking/current_session.json`
4. `ThoughtAnalyzer.analyze_thought()` finds related thoughts and computes progress
5. Analysis result dict is returned to the client

### Thinking Stages (ThoughtStage enum)

All thoughts must be assigned one of these stages:
- Problem Definition
- Research
- Analysis
- Synthesis
- Conclusion

`ThoughtStage.from_string()` does case-insensitive matching.

### Data Serialization

- Internal Python uses **snake_case** field names
- External API/JSON uses **camelCase** field names
- `ThoughtData.to_dict()` and `ThoughtData.from_dict()` handle conversion
- `utils.py` provides `to_camel_case()` and `to_snake_case()` converters

### Thread Safety

- `ThoughtStorage` uses `threading.RLock` for in-memory data access
- File I/O uses `portalocker.Lock` for cross-process safety
- Corrupted session files are automatically backed up with `.bak.<timestamp>` suffix

### Test Architecture

- Tests use `unittest.TestCase` style (not pytest fixtures)
- `testing.py` contains `TestHelpers` with test-specific logic for analysis
- Test helpers are conditionally imported in production code via `importlib.util.find_spec("pytest")`
- Storage tests use `tempfile.TemporaryDirectory` for isolation

## Code Style Conventions

- **Line length**: 100 characters (Black + isort)
- **Target Python**: 3.10 (uses modern type hints)
- **Imports**: Relative imports within the package (e.g., `from .models import ...`)
- **Fallback imports**: `server.py` has try/except for both relative and absolute imports (for running as script vs package)
- **Logging**: All modules use `configure_logging("sequential-thinking.<module>")` — logs go to stderr
- **Error handling**: MCP tools return `{"error": str, "status": "failed"}` dicts on failure instead of raising exceptions
- **Naming**: Classes use PascalCase, functions/methods use snake_case, constants use UPPER_SNAKE_CASE

## Environment Variables

- `MCP_STORAGE_DIR` — Override default storage directory (default: `~/.mcp_sequential_thinking/`)

## CI/CD

- `.github/workflows/claude.yml` — Claude Code GitHub Action that responds to `@claude` mentions in issues and PRs
- No automated test/lint CI pipeline currently configured

## Optional Dependency Groups

- `dev` — pytest, pytest-cov, black, isort, mypy
- `vis` — matplotlib, numpy (visualization)
- `web` — fastapi, uvicorn, pydantic (web UI)
- `all` — everything above
