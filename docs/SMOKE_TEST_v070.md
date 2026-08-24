# Manual Smoke Test — v0.7.0

Run on 2026-08-24 against the worktree `feat/v0.7.0-sdk2-hardening`
(`mcp==2.0.0` installed from PyPI, Python 3.14.7), as required by the merge
gate: a real stdio subprocess (not the in-memory test client), driven with
the SDK's own `mcp.client.stdio.stdio_client` + `mcp.Client`.

## Setup

```
$ .venv/bin/python -m mcp_sequential_thinking.server   # started as a subprocess by the client below
```

Client script (`stdio_client(StdioServerParameters(command=".venv/bin/python",
args=["-m", "mcp_sequential_thinking.server"], env={"MCP_STORAGE_DIR": <tmp>}))`)
connects, lists tools, then drives one full session: all five stages, a
revision, a branch, export, clear, and import.

## `tools/list`

All five tools are present and every one declares an `output_schema`
(structured output, per Phase A) with the annotations set in Phase C:

```
- process_thought:   output_schema=yes, read_only=False, destructive=False, idempotent=False
- generate_summary:  output_schema=yes, read_only=True,  destructive=False, idempotent=True
- clear_history:     output_schema=yes, read_only=False, destructive=True,  idempotent=True
- export_session:    output_schema=yes, read_only=False, destructive=False, idempotent=False
- import_session:    output_schema=yes, read_only=False, destructive=True,  idempotent=False
```

## Full session walkthrough

Seven `process_thought` calls: Problem Definition → Research → Analysis →
(revision of #2) → (branch from #3) → Synthesis → Conclusion. Numbers 1, 2,
3, 5, 6 omitted `thought_number` and were server-assigned; the revision and
the branch also omitted it and were assigned 4 each (different lines —
mainline vs. the `alt-form-theory` branch — so no collision, matching the
B1 design in `docs/MIGRATION_PLAN.md`).

| # | Stage | Notes | `main_line_position` | `warnings` |
|---|-------|-------|----------------------|------------|
| 1 | Problem Definition | auto-numbered | 1 | [] |
| 2 | Research | auto-numbered | 2 | [] |
| 3 | Analysis | `same_category_thoughts` finds #2 via shared tag `payment` | 3 | [] |
| 4 | Research (revision of #2) | `related_thoughts` finds #2 lexically (score 0.75); `revision_of` snippet present | 3 (unchanged — revisions don't advance the mainline) | [] |
| 4 (branch `alt-form-theory`, from #3) | Analysis | own line, own numbering; `branch_count`→1 | 3 (unchanged — branches don't advance the mainline) | [] |
| 5 | Synthesis | auto-numbered, continues mainline; `related_thoughts` finds #3 lexically (score 0.24) | 4 | [] |
| 6 | Conclusion | auto-numbered | 5 | [] |

No stage-order warnings were expected or produced — the mainline went
Problem Definition → Research → Analysis → Synthesis → Conclusion in
order (permissive-mode `--strict-stages` was not needed here; that path is
covered by `test_stage_skip_rejected_in_strict_mode` /
`test_stage_skip_warns_in_permissive_mode` in the automated suite instead
of this manual run).

Full JSON for thought #1 (`current_thought` / `analysis` / `context` /
`warnings` shape — every later call returns the same shape):

```json
{
  "current_thought": {
    "thought_number": 1,
    "total_thoughts": 6,
    "next_thought_needed": true,
    "stage": "Problem Definition",
    "tags": ["onboarding", "funnel"],
    "timestamp": "2026-08-24T20:30:19.913096"
  },
  "analysis": {
    "related_thoughts": [],
    "same_category_thoughts": [],
    "main_line_progress": 16.666666666666664,
    "main_line_position": 1,
    "total_thoughts_recorded": 1,
    "branch_count": 0,
    "revision_count": 0,
    "is_first_in_stage": true,
    "is_revision": false,
    "revised_thought": null,
    "branch_id": null,
    "revision_of": null
  },
  "context": { "thought_history_length": 1, "current_stage": "Problem Definition" },
  "warnings": []
}
```

Thought #4 (the revision of #2) showing `revision_of` and a lexical
`related_thoughts` match:

```json
{
  "current_thought": { "thought_number": 4, "stage": "Research", "...": "..." },
  "analysis": {
    "related_thoughts": [{ "number": 2, "score": 0.75, "reason": "lexical" }],
    "is_revision": true,
    "revised_thought": 2,
    "revision_of": {
      "thought_number": 2,
      "stage": "Research",
      "snippet": "Session replay data shows most drop-offs happen on the payment step."
    }
  }
}
```

## `generate_summary`

Contains the actual thinking (B5), not just counters — per-stage
excerpts, the aggregated challenged assumption, the still-open branch, and
the revision chain, alongside the structural statistics:

```json
{
  "has_thoughts": true,
  "content": {
    "stage_content": [
      { "stage": "Problem Definition", "thought_numbers": [1],
        "excerpts": ["The problem is our onboarding funnel drops 40% of users at step 3."] },
      { "stage": "Research", "thought_numbers": [2, 4],
        "excerpts": [
          "Session replay data shows most drop-offs happen on the payment step.",
          "Session replay data shows most drop-offs happen on the payment step, specifically the CVV field."
        ] },
      { "stage": "Analysis", "thought_numbers": [3, 4],
        "excerpts": [
          "Payment step requires a credit card even for the free tier, which is the likely cause.",
          "Alternative theory: drop-off is really about a confusing multi-page form, not payment at all."
        ] },
      { "stage": "Synthesis", "thought_numbers": [5],
        "excerpts": ["Make the free tier fully card-free; only ask for payment info at upgrade time."] },
      { "stage": "Conclusion", "thought_numbers": [6],
        "excerpts": ["Conclusion: remove the card requirement from free-tier signup; re-measure funnel drop-off in two wee…"] }
    ],
    "assumptions_challenged": ["Users expect to enter payment info upfront"],
    "open_branches": ["alt-form-theory"],
    "revision_chains": [{ "original_thought_number": 2, "replaced_by": [4] }],
    "gaps": []
  },
  "structure": {
    "total_thoughts": 7,
    "branches": [{ "branch_id": "alt-form-theory", "from_thought": 3, "thought_count": 1, "has_conclusion": false }],
    "revision_count": 1,
    "top_tags": [{ "tag": "payment", "count": 2 }, "..."],
    "completion": {
      "stages_covered": 5, "stages_total": 5,
      "stage_coverage_percent": 100.0, "has_all_stages": true, "skipped_stages": []
    }
  }
}
```

`stages_total` is `5` (from `len(ThoughtStage)`, B2) and
`stage_coverage_percent` is exactly `100.0` for 5/5 stages used — not the
`66.67` (4/6) miscalculation the bug report described.

## Export → clear → import round trip

```
export_session  -> {"status": "success", "message": "Session exported to smoke_export.json", "thought_count": 7, "file_path": "smoke_export.json"}
clear_history   -> {"status": "success", "message": "Thought history cleared", "cleared_count": 7}
generate_summary -> {"has_thoughts": false, "message": "No thoughts recorded yet", "content": null, "structure": null}
import_session  -> {"status": "success", "message": "Session imported from smoke_export.json", "thought_count": 7}
generate_summary -> identical to the "generate_summary" block above (all 7 thoughts, all content and structure fields byte-identical) — the round trip is lossless.
```

## Result

- All 5 tools present with `output_schema` and correct `readOnlyHint`/
  `destructiveHint`/`idempotentHint` annotations. ✅
- Full 7-stage-and-revision-and-branch session completed with no errors,
  auto-numbering worked correctly across the mainline and a branch. ✅
- `generate_summary` carries real content (excerpts, assumptions,
  open branches, revision chains), not just counters. ✅
- `stage_coverage_percent` denominator is `5`, matches `len(ThoughtStage)`. ✅
- Export → clear → import round trip is lossless. ✅
- Every call completed in well under 1ms (logged via `log_duration`,
  visible on stderr) — no call approached the 2s merge-gate ceiling. ✅
- Automated concurrency/timeout coverage for the B7 hang and the stale-lock
  scenario lives in `tests/test_server.py`
  (`test_concurrent_process_thought_no_deadlock`,
  `test_stale_lock_raises_clean_mcp_error_not_hang`) rather than this
  manual run — both pass as part of the test suite (see merge-gate report).
