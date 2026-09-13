# Migration Plan — v0.7.0 (MCP SDK 2.x + test findings)

Status: living document, updated as phases land. Written before any code
changes per the task mandate.

## 0. Ground truth check

Before touching code, the SDK 2.x claim was verified independently of the
task text (which could itself be wrong or stale):

- `pip index` via the PyPI JSON API confirms `mcp` 2.0.0 is published
  (releases up to `2.0.0rc1` then `2.0.0`; last 1.x release was `1.9.4`).
- `httpx2` exists as a real PyPI package (not used by this repo — see §3).
- A throwaway venv with `mcp==2.0.0` installed was introspected directly
  (`inspect.signature`, `pkgutil.iter_modules`) rather than trusting
  documentation prose. Confirmed by introspection:
  - `mcp.server.mcpserver.MCPServer` and `mcp.server.mcpserver.Context` exist.
  - `MCPServer.__init__` takes `instructions` as keyword-only-by-convention
    (it's a plain kwarg, but passing it positionally after `version` would
    land on `website_url`/`icons` depending on position — always pass by
    keyword).
  - `MCPServer.run(transport="stdio"|"sse"|"streamable-http", **kwargs)` —
    transport-specific args (`host`, `port`, `json_response`,
    `stateless_http`) are `**kwargs` forwarded to `run_streamable_http_async`
    / `run_sse_async`, confirming they no longer belong on the constructor.
  - `mcp.MCPError.__init__(self, code: int, message: str, data: Any = None)`.
  - `mcp.server.mcpserver.exceptions.ToolError` — subclass of
    `MCPServerError`; raising it inside a tool produces
    `CallToolResult(is_error=True, content=[TextContent(text=str(err))])`
    instead of failing the JSON-RPC call.
  - `mcp.types.CallToolResult` fields: `meta, content, structured_content,
    is_error, result_type` — confirms `structuredContent`/`isError` are gone
    in favor of snake_case.
  - `mcp.types.Tool` fields include `input_schema` and `output_schema`
    (snake_case, confirming `inputSchema` is gone as an attribute name; wire
    format still uses the camelCase alias, handled by pydantic's
    `by_alias=True` at serialization time — we don't touch that ourselves
    since we let the SDK serialize `Tool`/`CallToolResult` for us).
  - `mcp.Client(server, raise_exceptions=True, ...)` — in-memory client for
    tests, takes an `MCPServer` instance directly.

This means: no reliance on trained-in 1.x knowledge, and no reliance on raw
doc-page prose either — the parts of this plan that talk about SDK types are
backed by `inspect` output against the actually-installed 2.0.0 wheel.

## 1. Repo inventory (as of `master` @ f0a405d, mcp-sequential-thinking 0.6.1)

```
mcp_sequential_thinking/
  server.py        - FastMCP instance + 5 @mcp.tool() handlers + main()
  models.py        - ThoughtStage(Enum), ThoughtData(BaseModel)
  storage.py        - ThoughtStorage: in-memory list + JSONL session file,
                       threading.RLock, portalocker file lock (timeout=10s)
  storage_utils.py  - JSONL/JSON read-write helpers, atomic write, schema
                       version handling (v1 legacy JSON, v2 JSONL)
  analysis.py       - ThoughtAnalyzer: find_related_thoughts, generate_summary,
                       analyze_thought
  logging_conf.py   - stderr logger factory
  utils.py          - to_camel_case (unused outside tests currently)
tests/
  test_models.py    - 17 tests, ThoughtData validation incl. revision/branch
  test_storage.py   - 24 tests, JSONL schema, locking, path traversal,
                       migration v1->v2, corruption recovery
  test_analysis.py  - 10 tests, related-thoughts, summary, progress
  test_server.py    - 4 tests, process_thought via asyncio.run() directly
                       (no protocol round-trip, no MCP Client)
```

Public tools exposed via `@mcp.tool()`: `process_thought`, `generate_summary`,
`clear_history`, `export_session`, `import_session`. All currently return
plain `dict` (untyped from the SDK's perspective — no output schema).

Pydantic models: `ThoughtData` (the only one). Tool return shapes are
hand-built dicts in `analysis.py` / `server.py`, not modeled — this is what
Phase A's structured-output work replaces.

**Already correct and NOT to be touched** (nine points from the task's "not
anfassen" list, all currently covered by `test_storage.py` /
`test_models.py`):

1. Stage validation with enumeration of valid values —
   `ThoughtStage.from_string` (`test_from_string_invalid`).
2. `branch_id` without `branch_from_thought` rejected —
   `test_branch_id_requires_branch_from`.
3. `thought_number > total_thoughts` rejected —
   `test_validate_invalid_total_thoughts`.
4. Revision of a nonexistent thought — covered indirectly by
   `test_revises_number_must_be_earlier` (bounds check); a regression test
   naming this explicitly is added in Phase B (analysis-level: revising a
   number that was never recorded doesn't crash, just yields no
   `revisionOf`).
5. Sandbox blockade on export — `test_export_rejects_path_outside_storage`.
6. Path traversal blockade (`../../../`) — same test, `..` case.
7. Lossless export→clear→import round-trip —
   `test_export_import_session`.
8. Import of a nonexistent file — `test_import_missing_file_raises_and_preserves_state`.
9. Import replaces rather than appends — asserted implicitly by
   `test_export_import_session` (history length 2 after import, not 4);
   made explicit in Phase B.

Phase B adds the two regression tests that aren't yet explicit (4 and 9)
plus keeps 1/2/3/5/6/7/8 exactly as they run today — none of the B1–B7 fixes
touch that code path.

## 2. Planned order

1. **Phase A (this doc's §3–§5)**: SDK migration only, no behavior changes
   to thinking logic. Must be fully green (existing test suite, adapted to
   new SDK types) before Phase B starts.
2. **Phase B**: B1–B7 fixes, one commit per finding, each with its named
   regression test(s), plus the nine "don't touch" regression tests made
   explicit.
3. **Phase C**: tool descriptions/annotations honesty pass, README.
4. **Phase D**: CI matrix, coverage gate, lint/type gate, CHANGELOG, this
   doc finalized.

## 3. SDK 2.x migration — concrete changes

- `pyproject.toml`: `mcp>=2,<3` (drop the `<2.0.0` cap from 0.6.1's
  workaround — that cap is now the wrong direction).
- No `httpx` import exists anywhere in this repo today (`grep -rn httpx`
  returns nothing outside `.venv`). The SDK's own `httpx2` dependency is
  transitive and not our concern to pin. §5's "if httpx is imported"
  instruction is therefore N/A — noted here so it isn't silently missed.
- `server.py`:
  - `from mcp.server.mcpserver import MCPServer, Context`
  - `mcp = MCPServer("mcp-sequential-thinking", version="0.7.0", instructions="...")`
    — `instructions` passed strictly by keyword (confirmed necessary: it's
    positionally the 4th param after `name, title, description`, so a
    positional call would silently land the text in the wrong field).
  - All handlers become `async def`. Storage calls that do file I/O
    (`add_thought`, `clear_history`, `export_session`, `import_session`)
    are wrapped in `anyio.to_thread.run_sync(...)` so the event loop thread
    is never blocked on `fsync`/`portalocker`. This is the direct fix for
    B7 (see there for the causal chain). `generate_summary` is read-only
    and fast (in-memory list scan) — no thread offload needed, but stays
    `async def` for a consistent handler shape and Context access.
  - Structured output: every tool gets a Pydantic return model (§4).
  - Error semantics split (§ Phase B / error handling): `MCPError` for
    protocol/validation problems the model can't fix by retrying,
    `ToolError` (→ `CallToolResult(is_error=True)`) for execution problems
    it can learn from and retry.
- Tests: `tests/test_server.py`'s direct `asyncio.run(server.process_thought(...))`
  calls are replaced with `mcp.Client(server.mcp, raise_exceptions=True)`
  in-memory protocol round-trips, per
  `py.sdk.modelcontextprotocol.io/get-started/testing/`. This is also where
  `structured_content` gets asserted instead of parsing dict returns.

## 4. Structured output design

One Pydantic model per tool in a new `mcp_sequential_thinking/schemas.py`:

- `ProcessThoughtResult` — mirrors the current `thoughtAnalysis` shape but
  as a typed model; adds `warnings: list[str]` (B6) and replaces the old
  ambiguous `progress` float with the four explicit fields from B3.
- `SummaryResult` — adds the `content` section from B5 alongside the
  existing `structure` section (renamed from the flat shape).
- `ExportResult` / `ImportResult` — `status`, `message`, `record_count`.
- `ClearHistoryResult` — `status`, `message`, `cleared_count`.

All existing dict keys are camelCase (hand-rolled via `to_dict`-style
methods) for backward compatibility with any client parsing `content[0].text`
as JSON. The Pydantic models themselves use snake_case field names (SDK
convention) with `Field(alias=...)` where a camelCase wire name must be
preserved for `structured_content`, and `model_config = ConfigDict(populate_by_name=True)`.

## 5. B4 — related-thoughts decision

**Chosen: option (b) with (a) as a fallback/explanatory field**, as the task
recommends.

Trade-offs considered:

- **(a) only (rename to `same_category_thoughts`)**: honest about what the
  code does today, zero risk, but doesn't fix the actual complaint — it
  still can't find two thoughts about the same underlying idea if they land
  in different stages and don't share a tag. Cheapest, weakest.
- **(b) only (lexical similarity)**: solves the actual problem — two
  thoughts about "the deadline slipping" match even if one is tagged
  `#risk` and the other `#schedule` and they're in different stages.
  Downside: a pure lexical/Jaccard measure will miss synonyms and can be
  fooled by short thoughts with few tokens in common; it needs a documented
  threshold and a "why did this match" reason so the result stays
  debuggable rather than a black box.
- **scikit-learn / embeddings**: rejected per the task's explicit
  instruction — no new heavy dependencies for this. A 5-minute overkill for
  a local stdio tool that shouldn't need a C-extension ML stack.

Implementation: stdlib-only tokenizer (lowercase, split on non-alphanumerics,
strip a combined DE+EN stopword list), Jaccard similarity over token sets
(TF-IDF-cosine was considered but Jaccard is simpler, has no corpus-wide
state to maintain across a growing session, and is adequate at the token-set
sizes involved — single sentences to short paragraphs). Threshold and top-N
are constants (`MIN_SIMILARITY = 0.2`, `MAX_RESULTS = 3`), revisited if real
usage shows they're wrong.

Output: `related_thoughts: list[{number, score, reason="lexical"}]` for the
content-relevance signal. `same_category_thoughts:
list[{number, reason="tag:<name>"}]` is the (a) fallback field — but per
(a)'s own rule, stage equality *alone* is not a match there either; only a
shared tag qualifies (stage proximity without a tag in common isn't a
meaningful signal, just calendar adjacency in the thinking process).
`same_category_thoughts` is kept as a separately-named field so nothing
pretends categorical proximity is semantic relevance.

## 6. Session file compatibility

No on-disk schema version bump. B1–B7 change tool *output* shapes and
in-memory analysis behavior, not the stored `ThoughtData` record format
(`storage_utils.SCHEMA_VERSION` stays `2`). Existing `current_session.jsonl`
files and v1/v2 exports remain readable without a migration routine —
verified by keeping `test_migration_from_v1_json` and
`test_import_v1_export_still_works` green unmodified through Phase B.

## 7. Open items / risk register

- `anyio.to_thread.run_sync` changes concurrency behavior for the storage
  layer under real parallel load; B7's stress test
  (`test_concurrent_process_thought_no_deadlock`) is the acceptance check.
- Structured output requires every tool's return value to validate against
  its declared Pydantic model on every call — a bug in a hand-built dict
  now fails loudly (SDK-level validation error) instead of silently
  shipping malformed JSON. Treated as a feature, not a risk, but called out
  since it's a behavior change from "always returns whatever dict I built".


## 8. Manual Claude MCP audit follow-up (2026-09-08)

The seven reported findings are covered by `tests/test_claude_findings.py`:
version-safe excerpts; explicit-session archive roundtrip and atomic rejection;
SESSION_FINALIZED; current_version on MCP conflicts; branch-qualified analysis;
resume pagination; completion only on the first page unless requested.
Resume prioritization is intentional and now returned as ordering metadata.
Legacy calls remain compatible but are deprecated for new workflows. Single-session
archives exclude retry keys; SQLite snapshots remain the complete restore path.
The qualitative feedback supports positioning as durable notes and an auditable
record, not a demonstrated reasoning improvement. It is one manual evaluation,
not a completed comparative benchmark.


## 9. Second manual audit (2026-09-08)

- Add PATH_OUTSIDE_EXPORTS through the MCP error boundary for both archive formats.
- Expose the legacy deprecation notice in process_thought results without removing tools.
- Explain progress and sequence semantics in results, preserving compatibility.
- The quoted German sentences match at Jaccard 0.6 with the existing DE/EN tokenizer;
  shared tags match independently. Test both SQLite legacy and JSONL paths through MCP.
  Do not tune the heuristic based on abbreviated inputs; full failing inputs are needed.
- finalize_session already validates evidence IDs against the same session before
  writing. MCP tests now explicitly reject invented and cross-session IDs, verify
  no state change, and show that a corrected retry succeeds.
