# Changelog

## [0.7.0] — Unreleased development candidate

### Reliability upgrade (2026-09-05)

- Serialize JSONL recovery and mutations; repair incomplete UTF-8/JSON tails with
  exact backups; reject complete corruption, future schemas and identity conflicts.
- Add transactional SQLite sessions, ID references, request-ID retries, versioned
  finalization, bounded resume/full reads and explicit typed completion records.
- Migrate legacy UUIDs and contents without deduplication; keep the five tools on
  the explicit legacy session, with guarded old-writer exclusion and snapshot restore.
- Add memory-only operation, controlled diagnostics, schema limits and sanitized
  correctable tool errors. Legacy stage spelling remains case insensitive.
- Extend process/crash/fault/stdio tests and complete Python/Windows/SDK gates;
  test installed artifacts outside the checkout and publish the same tested files.
- Prepare a bilingual evaluation collection and registry metadata. A completed
  model usefulness comparison is still required; no general quality claim is made.

Compatibility changes: corrupt storage fails closed rather than starting empty;
correctable legacy errors are now isError tool results; inputs/outputs have explicit
limits; source imports no longer initialize storage. SQLite snapshots are required
for complete restore after new writes; legacy JSONL alone cannot downgrade all
session semantics. See the README for details.

### Earlier 0.7 development work (2026-08-24; not a published release)

### Breaking

- **`mcp` dependency moves to the 2.x line**: `mcp>=2,<3` (was
  `>=1.2.0,<2.0.0`). `mcp.server.fastmcp.FastMCP` is gone upstream; the
  server is rewritten against `mcp.server.mcpserver.MCPServer`. If you
  vendor or subclass anything from this package's server module, the SDK
  types you get back changed from camelCase to snake_case (`isError` →
  `is_error`, `structuredContent` → `structured_content`, etc.) — this
  package's own request/response shapes below are affected the same way.
- **Every tool now returns structured, typed output** (a Pydantic model,
  surfaced as `structured_content`) instead of an untyped dict serialized
  to JSON text. Field names are snake_case throughout, replacing the old
  camelCase dict shape end to end — not just the fields called out below.
  `tools/list` now advertises an `output_schema` for all five tools.
- **`process_thought` analysis output**: the old single `progress` float
  (which froze/misreported once revisions or branches entered the
  picture) is replaced by four explicit fields: `main_line_progress`,
  `main_line_position`, `total_thoughts_recorded`, `branch_count`,
  `revision_count`. `relatedThoughtsCount`/`relatedThoughtSummaries` —
  which matched on stage equality or tag overlap and called that
  "related" — are replaced by `related_thoughts` (lexical similarity
  across the actual thought text, stage-independent) and
  `same_category_thoughts` (the honest name for the old categorical
  match, now requiring an actual shared tag rather than stage alone).
  Every response also carries a `warnings` list (stage-order issues; see
  below).
- **`thought_number` is now optional** on `process_thought` — omit it to
  have the server assign the next free number on the current line
  (mainline, or the given `branch_id`). Sending a `thought_number` that's
  already used on that line is now rejected (previously accepted
  silently, corrupting progress accounting).
- **`generate_summary` output restructured**: a new `content` section
  (per-stage thought excerpts, aggregated `assumptions_challenged`,
  `open_branches`, `revision_chains`) sits alongside the old counters,
  now under `structure`. `completionStatus.percentComplete` is replaced
  by `structure.completion.stage_coverage_percent`, whose denominator is
  always `len(ThoughtStage)` (5), never hardcoded.
- **Export/import path errors, invalid stage names, and duplicate
  `thought_number`** now fail the tool call as a protocol-level error
  (`MCPError`, JSON-RPC `INVALID_PARAMS`/`REQUEST_TIMEOUT`) instead of
  being swallowed into a `{"status": "failed"}` response. Execution
  failures the model can retry past (a missing import file, an
  unexpected storage error) instead come back as `is_error=True` tool
  results.
- Session/export files on disk are unaffected — no schema migration
  needed, existing `current_session.jsonl` and v1/v2 exports keep
  working (see `docs/MIGRATION_PLAN.md` §6).

### Added

- **Stage-order warnings**: every `process_thought` response includes a
  `warnings` list noting a skipped or backward stage transition on the
  mainline. Permissive by default. New `--strict-stages` CLI flag (and
  `ThoughtStorage`-adjacent server state) rejects such transitions with
  `MCPError` instead of just warning.
- **`--health` CLI subcommand**: checks the storage directory exists, is
  writable, and that the session lock can be acquired; prints a report
  and exits 0/1.
- **`--transport {stdio,sse,streamable-http}`** CLI flag (plus
  `--host`/`--port`); `stdio` remains the default.
- Structured stderr logging: each tool call logs start/completion (or
  failure) with elapsed time in milliseconds.
- Tool annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`)
  are now set per tool — `clear_history` and `import_session` are marked
  destructive.

### Fixed

- A handful of concurrent `process_thought` calls against the same
  session could stall for minutes: blocking file I/O (a file lock
  acquire plus `fsync`) ran synchronously inside an `async def` handler,
  serializing every concurrent request behind it on the single event-loop
  thread. Storage calls now run in worker threads
  (`anyio.to_thread.run_sync`); a lock that can't be acquired within its
  timeout now fails fast with a clear error instead of blocking.
- `generate_summary` previously reported only structural statistics
  (stage/branch/tag counts) with no actual thinking content — it now
  includes per-stage excerpts of the recorded thoughts, aggregated
  challenged assumptions, open branches, and revision chains.

## [0.6.1] - 2026-08-23

### Fixed
- `uvx mcp-sequential-thinking` failed with `ModuleNotFoundError: No module
  named 'mcp.server.fastmcp'` because the `mcp` dependency had no upper bound
  and `uvx` (unlike a `uv.lock`-pinned install) re-resolves against the
  published index, pulling in `mcp` 2.0.0, which removed `mcp.server.fastmcp`.
  The dependency is now pinned to `mcp>=1.2.0,<2.0.0`. The `[cli]` extra was
  also dropped since nothing in this project uses `mcp.cli`, `mcp dev`, or
  `mcp install`; it only pulled in unused packages (`typer`, `rich`, etc.).
  (#27)

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
