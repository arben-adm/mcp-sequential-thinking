"""Sanitize tool failures at the supported MCPServer call boundary."""

from __future__ import annotations

import re
from typing import Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import ValidationError

from .sessions import SessionError

ERROR_HINTS = {
    "PATH_OUTSIDE_EXPORTS": "Choose an import/export file path within the exports/ directory.",
    "INVALID_INPUT": "Check field types, limits, stage and revision parameters in tools/list.",
    "UNKNOWN_SESSION": "Use list_sessions to select an existing session.",
    "INVALID_REFERENCE": "Use an earlier step in this session; preserve the branch origin.",
    "SESSION_FINALIZED": "Create a new session for further notes; retrying cannot reopen it.",
    "CONFLICT": "Read the current version/position and retry with corrected input.",
    "IDEMPOTENCY_CONFLICT": "Use the original payload or a new request_id.",
    "STORAGE_BUSY": "Storage is locked; retry with the same request_id.",
    "STORAGE_ERROR": "Inspect the session before retry; reuse request_id for session mutations.",
    "STORAGE_UNAVAILABLE": "Initialize the server and check storage health.",
    "UNSUPPORTED_SCHEMA": "Use a compatible server or a verified restore.",
    "MIGRATION_CONFLICT": "Stop old writers and reconcile the preserved legacy source.",
    "RESPONSE_LIMIT": (
        "Increase max_chars, narrow the view, or read step_id with content_offset/content_chars."
    ),
    "NOT_FOUND": "The requested import file was not found in the exports directory.",
}


class WorkingNotesServer(MCPServer[Any]):
    async def call_tool(
        self, name: str, arguments: dict[str, Any], context: Context[Any, Any] | None = None
    ) -> Any:
        try:
            return await super().call_tool(name, arguments, context)
        except ToolError as error:
            # Walk the whole chain before deciding. The adapters re-raise a
            # SessionError as ToolError(str(error)), so the outermost message
            # already carries the code prefix; stopping at that first match would
            # never reach the SessionError itself and would drop both its hint and
            # its current_version.
            validation: ValidationError | None = None
            session_error: SessionError | None = None
            prefix_code: str | None = None
            cause: BaseException | None = error
            while cause is not None:
                if validation is None and isinstance(cause, ValidationError):
                    validation = cause
                if session_error is None and isinstance(cause, SessionError):
                    session_error = cause
                if prefix_code is None:
                    prefix_code = next(
                        (key for key in ERROR_HINTS if str(cause).startswith(key + ":")), None
                    )
                cause = cause.__cause__

            code = "INVALID_INPUT"
            fields: list[str] = []
            specific = ""
            if validation is not None:
                fields = sorted(
                    {
                        str(part)
                        for issue in validation.errors(include_input=False)
                        for part in issue["loc"]
                        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,40}", str(part))
                    }
                )[:5]
            elif session_error is not None and session_error.code in ERROR_HINTS:
                # Prefer the raise site's own hint over the per-code fallback. Every
                # SessionError hint is an author-written literal with no caller
                # content interpolated, so surfacing it leaks nothing and says what
                # the fallback cannot: "A branch's origin cannot change" instead of a
                # blanket instruction to preserve it, and "Import into a store
                # without this session" instead of advice to retry with a version
                # that import_session has no parameter for.
                code = session_error.code
                specific = session_error.hint
            elif prefix_code is not None:
                code = prefix_code

            hint = specific or ERROR_HINTS[code]
            if fields:
                hint += " Fields: " + ", ".join(fields)
            if session_error is not None and session_error.current_version is not None:
                hint += f" current_version={session_error.current_version}"
            raise ToolError(f"{code}: {hint}") from None
