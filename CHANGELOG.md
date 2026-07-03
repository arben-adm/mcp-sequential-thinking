# Changelog

## [0.6.0] - 2026-07-03

### Added
- **Thought revisions and branching**: `process_thought` accepts new optional
  parameters `is_revision`, `revises_thought_number`, `branch_from_thought` and
  `branch_id` to revise an earlier thought or fork an alternative line of
  reasoning. Cross-field validation enforces consistent usage. Analysis output
  reports `isRevision`/`revisedThought`/`branchId` (plus a `revisionOf` snippet
  for revisions), and `generate_summary` gains a `branches` object and a
  `revisionCount`. Progress metrics are based on mainline thoughts only, so
  revisions and branches no longer inflate completion beyond 100%.
- **Append-only JSONL session format (schema v2)**: the session now lives in
  `current_session.jsonl` (header record + one thought per line). `process_thought`
  is O(1) per call instead of rewriting the full history, and the file doubles as
  an audit trail. A truncated final line (interrupted write) is dropped on load
  instead of invalidating the whole session. Existing v1 `current_session.json`
  files are migrated automatically and losslessly on first start; the original is
  kept as `current_session.json.migrated-to-v2`.
- JSON exports now carry a top-level `"version": 2` field. Legacy v0.5.0 exports
  (no version field) remain importable.
- CI workflow (GitHub Actions): test matrix on Linux/Windows with Python 3.10
  and 3.12, running pytest and mypy on every push and pull request.
- Release workflow publishing to PyPI via Trusted Publishing when a GitHub
  release is published (requires one-time Trusted Publisher setup on pypi.org).
- Dependabot configuration for pip and GitHub Actions dependencies.
- `SECURITY.md` with a private disclosure contact.

### Changed
- **Package renamed** from `sequential-thinking` to `mcp-sequential-thinking` for the PyPI
  release (the old name is occupied by a third-party fork). The console script
  `mcp-sequential-thinking` and the import package `mcp_sequential_thinking` are unchanged.
- **Breaking:** `export_session` and `import_session` are now confined to the
  `exports/` subdirectory of the storage directory (relative paths resolve to
  `~/.mcp_sequential_thinking/exports/` by default). This prevents an export from
  overwriting the active session file or its lock file.

### Fixed
- `import_session` no longer silently replaces the active session with an empty
  one when the given file is a valid JSON file without a `thoughts` key, or when
  the file does not exist. Both cases now raise and leave the session untouched.
- Path-validation errors returned to the MCP client no longer leak the absolute
  storage path (e.g. the user's home directory); the full path is only logged
  server-side.
- `mypy` now passes cleanly: added missing type annotations in `analysis.py`
  (`stages`, `percent_complete`) and `server.py` (`main() -> None`), and removed
  duplicate `import os` / `import sys` in the `__main__` block of `server.py`.

## Version 0.5.0 (Unreleased)

### Code Quality Improvements

#### 1. Reduced Code Duplication in Storage Layer
- Created a new `storage_utils.py` module with shared utility functions
- Implemented reusable functions for file operations and serialization
- Standardized error handling and backup creation
- Improved consistency across serialization operations
- Optimized resource management with cleaner context handling

#### 2. API and Data Structure Improvements
- Added explicit parameter for ID inclusion in `to_dict()` method
- Created utility module with snake_case/camelCase conversion functions
- Eliminated flag-based solution in favor of explicit method parameters
- Improved readability with clearer, more explicit list comprehensions
- Eliminated duplicate calculations in analysis methods

## Version 0.4.0

### Major Improvements

#### 1. Serialization & Validation with Pydantic
- Converted `ThoughtData` from dataclass to Pydantic model
- Added automatic validation with field validators
- Maintained backward compatibility with existing code

#### 2. Thread-Safety in Storage Layer
- Added file locking with `portalocker` to prevent race conditions
- Added thread locks to protect shared data structures
- Made all methods thread-safe

#### 3. Fixed Division-by-Zero in Analysis
- Added proper error handling in `generate_summary` method
- Added safe calculation of percent complete with default values

#### 4. Case-Insensitive Stage Comparison
- Updated `ThoughtStage.from_string` to use case-insensitive comparison
- Improved user experience by accepting any case for stage names

#### 5. Added UUID to ThoughtData
- Added a unique identifier to each thought for better tracking
- Maintained backward compatibility with existing code

#### 6. Consolidated Logging Setup
- Created a central logging configuration in `logging_conf.py`
- Standardized logging across all modules

#### 7. Improved Package Entry Point
- Cleaned up the path handling in `run_server.py`
- Removed redundant code

### New Dependencies
- Added `portalocker` for file locking
- Added `pydantic` for data validation

## Version 0.3.0

Initial release with basic functionality:
- Sequential thinking process with defined stages
- Thought storage and retrieval
- Analysis and summary generation
