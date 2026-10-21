"""Bound legacy summaries without changing aggregate counters or stored notes."""

import json
from typing import Any


def bounded_summary(data: dict[str, Any], max_chars: int) -> dict[str, Any]:
    lists: list[list[Any]] = []

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            if "thought_numbers" in value and "excerpts" in value:
                if len(value["thought_numbers"]) > 20 or len(value["excerpts"]) > 20:
                    value["thought_numbers"] = value["thought_numbers"][:20]
                    value["excerpts"] = value["excerpts"][:20]
                    data["truncated"] = True
                return
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            if len(value) > 20:
                del value[20:]
                data["truncated"] = True
            lists.append(value)
            for child in value:
                collect(child)

    collect(data)
    while len(json.dumps(data, ensure_ascii=False)) > max_chars:
        nonempty = [value for value in lists if value]
        if not nonempty:
            # Scalar counters and fixed schema metadata fit the minimum limit.
            data["content"] = None
            data["structure"] = None
            data["truncated"] = True
            break
        largest = max(nonempty, key=lambda value: len(json.dumps(value, ensure_ascii=False)))
        largest.pop()
        data["truncated"] = True
    return data
