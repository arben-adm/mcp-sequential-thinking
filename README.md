# MCP Sequential Thinking — working notes you can resume

<!-- mcp-name: io.github.arben-adm/mcp-sequential-thinking -->

A local MCP server for explicit working notes, evidence, decisions and next actions.
Use it to keep track of a difficult task across interruptions. Simple questions do
not need a session, a tool call, or five reasoning phases. The server neither asks
for hidden internal chain-of-thought nor claims to improve general reasoning quality.

**Development candidate: 0.7.0.** GitHub and PyPI still publish **0.6.1** as checked
on 2026-09-05. The session API described here is in the development branch, not in
that published package. This upgrade is a development candidate and is not
merge/release-ready.

## Try the restart demo

Python 3.10+ is declared; the release gate runs complete tests on Python 3.10–3.14,
Linux and Windows, against the minimum and latest compatible MCP SDK. Current
results are recorded in the CI runs for this branch.

From this branch, install it into a virtual environment:

```sh
python -m venv .venv
# Linux/macOS: . .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e .
python scripts/stdio_smoke.py
```

Once dependencies are installed, the demo takes a few seconds. It starts a real
stdio server, creates a session, stores an evidence note and a decision, stops the
process, starts it again and reads the decision with the same step IDs. It also
checks an invalid call and an idempotent retry. Its temporary demo data is removed
at the end. See [the demo script](scripts/stdio_smoke.py) for the complete calls.

The essential calls in an MCP client are:

```json
{"tool":"create_session","arguments":{"title":"Choose a local store","request_id":"create-1"}}
{"tool":"add_step","arguments":{"session_id":"<returned ID>","content":"Two writers must allocate unique positions.","kind":"evidence","request_id":"step-1"}}
{"tool":"add_step","arguments":{"session_id":"<returned ID>","content":"Use SQLite; verify restore before release.","kind":"decision","request_id":"step-2"}}
{"tool":"read_session","arguments":{"session_id":"<returned ID>"}}
```

These are example tool names/arguments, not raw JSON-RPC envelopes. After a process
restart, `list_sessions` finds the task even if the client lost its ID.

## Three useful workflows

- **Debugging:** record a hypothesis and a test result. Use `supersedes_step_id`
  when a result replaces an earlier claim. Resume omits superseded notes; full
  history still contains them with their superseded status.
- **Decisions:** record alternatives, evidence, risks and an explicit chosen option.
  Finalization stores the caller's outcome and evidence IDs, with a version check.
  It does not generate a conclusion or verify whether a URL proves a claim.
- **Research/planning:** keep source URIs, open questions and next actions. Resume
  shows active decisions/actions and recent notes; paginated reads recover details.

These deterministic storage properties are distinct from a model usefulness
comparison. **No completed model comparison or universal improvement in answer
quality is claimed.**

## Tools

| Tool | Purpose |
| --- | --- |
| `create_session` | Title and optional `mode="freeform"`; returns ID, version, persistence and retention properties. Optional request ID supports a retry. |
| `add_step` | Session ID, content and required `request_id`; kind defaults to `note`. Returns the stored UUID, branch position and version. |
| `list_sessions` | Find by title/status, with cursor and limit. |
| `read_session` | Default `view="resume"`; use `view="steps"` for complete paginated content, optional kind/step-ID filters and `active_only`. |
| `finalize_session` | Caller-supplied completion, `expected_version` and request ID. Finalized sessions reject further steps. |
| `delete_session` | Deletes the selected session's active DB records at `expected_version`; requires request ID. Backups/exports survive. |

Kinds are `note`, `observation`, `evidence`, `assumption`, `option`, `risk`,
`decision`, `next_action`. There is no required confidence number or total-step
estimate in the new API. Sources are explicitly **caller supplied and unverified**;
the base server never fetches their URLs. Imported/source text is data, not an
instruction to the client.

`parent_step_id` records provenance. `supersedes_step_id` revises an earlier note on
the same branch; revise the current replacement when extending a revision chain.
New branches require `branch_from_step_id`; an established branch's origin cannot
change. All references must stay inside the same session. New IDs are allocated
by the server, so references can only point backward to existing records.

Retry a mutation with the **same request ID and identical normalized input** after
an uncertain response. It returns the original result. Reusing the key with new
content yields `IDEMPOTENCY_CONFLICT`. Keys are scoped by operation/session. This
is not an exactly-once network guarantee. Finalization's expected version includes
all steps committed before that version; a concurrent new step causes a conflict.
There is no reopening operation in this version.

Read defaults are 20 entries and 12,000 characters; `limit` and `max_chars` are
configurable per read (hard limits 100 and 50,000). Results report truncation and
limits. Full-history cursors refer to the last returned record; follow them with
`view="steps"`. Resume excerpts are limited to 500 characters per note; use its ID
for the full record. For large legacy notes, pass `step_id`, `content_offset=0`
and optionally `content_chars` (default 4,000; maximum 10,000). Follow the returned
`next_content_offset` until null; offsets count Unicode characters, not bytes.
This preserves access to legacy content larger than one response. A large completion may require `max_chars=50000`. These are
character limits on structured content, not measured token counts or complete
JSON-RPC frame sizes. List responses and legacy summaries are also bounded.

Errors use `isError=true` on the wire (`is_error` in the Python SDK), stable codes
such as `INVALID_INPUT`, `UNKNOWN_SESSION`, `INVALID_REFERENCE`, `CONFLICT`,
`IDEMPOTENCY_CONFLICT`, `STORAGE_BUSY`, and a bounded correction hint. Protocol
errors remain distinct. Client annotations describe effects; they are not an
access-control or confirmation mechanism.

## Existing five tools

`process_thought`, `generate_summary`, `clear_history`, `export_session` and
`import_session` remain available and share the reserved **local `legacy` session**.
They do not separate parallel tasks or users. Create explicit sessions for new tasks.
New `add_step`/`delete_session` calls refuse `legacy`; use its original write/clear
tools. `read_session(session_id="legacy")` can read it.

`process_thought` retains required `total_thoughts`, `next_thought_needed` and
`stage`. `thought_number` is optional and allocated atomically. Stages are Problem
Definition, Research, Analysis, Synthesis, Conclusion; their existing
case-insensitive spelling is accepted. Stage order is advisory unless
`--strict-stages` is selected. Number-based revision targets resolve on the same
line; forks resolve on the mainline, with an immutable origin. New UUID-based
branch revisions belong to the new session API.

Results use the existing 0.7-development snake_case structured output:
`current_thought`, `analysis`, `context`, `warnings`. Related thoughts are a lexical
heuristic; `same_category_thoughts` groups by shared tags, not merely equal stage.
`generate_summary` contains `has_thoughts`, `content`, `structure`, plus
`total_recorded`, `truncated`, `max_chars` and a `read_session` pointer for full
history. Its aggregate counters describe the history even when excerpts are cut.
No structural score should be read as reasoning quality.

Legacy import **replaces** the legacy history: `{"thoughts":[]}` is a valid empty
replacement; wrong containers, duplicate IDs/positions and invalid references are
errors. v1/v2 JSON exports remain v1/v2; no multi-session data is disguised as that
format. Import/export paths are confined to `MCP_STORAGE_DIR/exports`, with limits
of 16 MiB and 10,000 records. Full multi-session snapshots use the separate SQLite
backup/restore command below.

## Storage, privacy and operation

```sh
mcp-sequential-thinking                         # local stdio; protocol only on stdout
mcp-sequential-thinking --version               # no storage access
mcp-sequential-thinking --health                # controlled diagnostic
mcp-sequential-thinking --ephemeral             # memory only; lost on process exit
```

The default directory is `~/.mcp_sequential_thinking`; set `MCP_STORAGE_DIR` to change
it. Normal operation persists **plaintext** SQLite data on a local filesystem.
One connection belongs to each operation/worker thread. SQLite serializes writers,
uses foreign keys, WAL, synchronous FULL and a five-second busy timeout. Shared
NFS/SMB storage and multi-host access are outside this design.

`--ephemeral` uses an in-memory database, ignores persistent storage and disables
file import/export. It cannot survive process restart. There is no automatic
retention policy. Deletion is scoped to active DB records; it is not secure erasure
and does not delete backups, exported copies or other client-held content.

Local stdio trusts the operating-system user. A session ID is not authorization.
HTTP/SSE are experimental; nonlocal binding requires `--allow-nonlocal-http` and
still provides no production multi-user authentication/isolation guarantee.
Optional remote package F is not implemented.

## Migration and restore

Stop old server binaries before upgrade. Controlled startup validates/recoveries
legacy JSONL tails, then migrates the entire history in one SQLite transaction.
Existing UUIDs, content and timestamp strings are preserved; naive old timestamps
retain an unknown timezone. Missing old IDs are assigned once. Conflicts stop
startup; no silent deduplication or renumbering occurs. Unknown future schemas and
complete/middle corruption preserve original files and fail closed.

A checksum-named source backup and number-to-UUID mapping remain available. New
servers hold the old file lock for their lifetime to stop exclusive old writers;
multiple new stdio servers can operate on the SQLite store.

Create a consistent snapshot, including all sessions and retry records:

```sh
python -m mcp_sequential_thinking.backup create /path/to/storage /path/to/snapshot.sqlite3
python -m mcp_sequential_thinking.backup restore /path/to/NEW-storage /path/to/snapshot.sqlite3
```

Snapshot creation uses SQLite's backup API and validates integrity, references and
schema. It refuses an existing destination. Restore requires a new directory;
then point `MCP_STORAGE_DIR` there and run `--health`. Keep the prior store until you
have verified the restored tasks. Never copy only a live main SQLite file while
ignoring its WAL. **An old JSONL backup is not a lossless downgrade after new SQLite
writes.** Legacy export preserves only `legacy`; older releases cannot represent
all new session/typed-record semantics. No automatic downgrade is offered.

Atomic replacement and fsync do not prove survival of every device, filesystem or
power failure. An interrupted response can follow a commit; retry IDs and verified
snapshots address those explicit failure classes, not universal durability.

## Client configuration and test status

An MCP host can run the installed executable directly:

```json
{"mcpServers":{"working-notes":{"command":"/absolute/path/to/venv/bin/mcp-sequential-thinking","env":{"MCP_STORAGE_DIR":"/absolute/path/to/local-notes"}}}}
```

On Windows use the virtual environment's `Scripts/mcp-sequential-thinking.exe`.
This is a conventional host configuration example, not a claim that every host
has been tested.

| Client/SDK | OS | Transport | Date | Evidence |
| --- | --- | --- | --- | --- |
| Python MCP Client 2.1.1, Python 3.12.13 | Linux | stdio | 2026-09-05 | Discovery/write/read/error/restart, isolated wheel smoke |
| Python MCP SDK 2.0.0 and latest, Python 3.10–3.14 | Linux/Windows | stdio/in-memory | 2026-09-06 | 20 combinations passed at `af1c7c5`, [CI run](https://github.com/arben-adm/mcp-sequential-thinking/actions/runs/34004038086); later changes require fresh checks |
| Claude Desktop, Cursor, VS Code, other hosts | untested | stdio | — | Configuration examples only |

## Development and release

```sh
python -m pip install -e '.[dev]' build twine
ruff check .
ruff format --check .
mypy --strict mcp_sequential_thinking
pytest --cov=mcp_sequential_thinking --cov-fail-under=85
python scripts/check_artifacts.py               # starts with an empty dist/
```

The artifact check builds wheel/sdist, checks metadata, installs the wheel in a
separate environment, starts it outside this checkout, runs a real restart/retry
roundtrip, and independently rebuilds the sdist. CI publishes no package. The
release workflow runs the same full gates and publishes precisely their tested
artifact using Trusted Publishing **only after an operator publishes a release**.
Version authority is `mcp_sequential_thinking/_version.py`; release tags must match.

The registry metadata is prepared but not published. The PyPI README marker must
be present in the published package before registry registration. Repository
protection and required checks are an explicit operator task.
