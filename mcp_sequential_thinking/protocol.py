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
            code = "INVALID_INPUT"
            fields: list[str] = []
            cause: BaseException | None = error
            while cause is not None:
                if isinstance(cause, ValidationError):
                    code = "INVALID_INPUT"
                    fields = sorted(
                        {
                            str(part)
                            for issue in cause.errors(include_input=False)
                            for part in issue["loc"]
                            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,40}", str(part))
                        }
                    )[:5]
                    break
                found = next((key for key in ERROR_HINTS if str(cause).startswith(key + ":")), None)
                if found:
                    code = found
                    break
                cause = cause.__cause__
            current_version = None
            cause = error
            while cause is not None:
                if isinstance(cause, SessionError):
                    current_version = cause.current_version
                    break
                cause = cause.__cause__
            hint = ERROR_HINTS[code] + (" Fields: " + ", ".join(fields) if fields else "")
            if current_version is not None:
                hint += f" current_version={current_version}"
            raise ToolError(f"{code}: {hint}") from None
