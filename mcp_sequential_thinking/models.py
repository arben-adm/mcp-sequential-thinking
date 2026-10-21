from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic.alias_generators import to_camel

# branch_id ends up in files and tool output, so it is restricted to a short,
# filesystem- and log-safe alphabet.
BRANCH_ID_MAX_LENGTH = 64
BRANCH_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class ThoughtStage(str, Enum):
    """Basic thinking stages for structured sequential thinking."""

    PROBLEM_DEFINITION = "Problem Definition"
    RESEARCH = "Research"
    ANALYSIS = "Analysis"
    SYNTHESIS = "Synthesis"
    CONCLUSION = "Conclusion"

    @classmethod
    def _missing_(cls, value: object) -> ThoughtStage | None:
        if isinstance(value, str):
            return next(
                (stage for stage in cls if stage.value.casefold() == value.casefold()), None
            )
        return None


class ThoughtData(BaseModel):
    """Data structure for a single thought in the sequential thinking process."""

    # Serialized records use camelCase keys; Python callers use field names.
    model_config = ConfigDict(
        alias_generator=to_camel, validate_by_name=True, validate_by_alias=True, extra="forbid"
    )

    thought: str = Field(max_length=100000)
    thought_number: int
    total_thoughts: int
    next_thought_needed: bool
    stage: ThoughtStage
    tags: list[str] = Field(default_factory=list, max_length=100)
    axioms_used: list[str] = Field(default_factory=list, max_length=100)
    assumptions_challenged: list[str] = Field(default_factory=list, max_length=100)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    is_revision: bool = False
    revises_thought_number: int | None = None
    branch_from_thought: int | None = None
    branch_id: str | None = None
    id: UUID = Field(default_factory=uuid4)

    def __hash__(self) -> int:
        """Make ThoughtData hashable based on its ID."""
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        """Compare ThoughtData objects based on their ID."""
        if not isinstance(other, ThoughtData):
            return False
        return self.id == other.id

    @field_validator("thought")
    @classmethod
    def thought_not_empty(cls, v: str) -> str:
        """Validate that thought content is not empty."""
        if not v or not v.strip():
            raise ValueError("Thought content cannot be empty")
        return v

    @field_validator("thought_number")
    @classmethod
    def thought_number_positive(cls, v: int) -> int:
        """Validate that thought number is positive."""
        if v < 1:
            raise ValueError("Thought number must be positive")
        return v

    @field_validator("total_thoughts")
    @classmethod
    def total_thoughts_valid(cls, v: int, info: ValidationInfo) -> int:
        """Validate that total thoughts is valid."""
        thought_number = info.data.get("thought_number")
        if thought_number is not None and v < thought_number:
            raise ValueError("Total thoughts must be greater or equal to current thought number")
        return v

    @model_validator(mode="after")
    def validate_revision_and_branch(self) -> ThoughtData:
        """Validate the cross-field rules for revisions and branches."""
        if self.is_revision and self.revises_thought_number is None:
            raise ValueError("is_revision=True requires revises_thought_number to be set")
        if self.revises_thought_number is not None and not self.is_revision:
            raise ValueError("revises_thought_number requires is_revision=True")
        if self.is_revision and self.branch_from_thought is not None:
            raise ValueError("A thought cannot be a revision and a branch start at the same time")
        if self.branch_id is not None and self.branch_from_thought is None:
            raise ValueError("branch_id requires branch_from_thought to be set")

        for field_name, value in (
            ("revises_thought_number", self.revises_thought_number),
            ("branch_from_thought", self.branch_from_thought),
        ):
            if value is not None and not 1 <= value < self.thought_number:
                raise ValueError(
                    f"{field_name} must be >= 1 and < thought_number "
                    f"({self.thought_number}), got {value}"
                )

        if self.branch_id is not None and (
            len(self.branch_id) > BRANCH_ID_MAX_LENGTH
            or not BRANCH_ID_PATTERN.match(self.branch_id)
        ):
            raise ValueError(
                f"branch_id must be 1-{BRANCH_ID_MAX_LENGTH} characters from [A-Za-z0-9_-]"
            )

        return self

    def to_dict(self, include_id: bool = False) -> dict[str, Any]:
        """Serialize with camelCase keys; ``id`` only when ``include_id``.

        Revision/branch fields are only emitted when set, keeping records
        compact and older v2 files readable without them.
        """
        result = self.model_dump(
            mode="json", by_alias=True, exclude_none=True, exclude=None if include_id else {"id"}
        )
        if not self.is_revision:
            del result["isRevision"]
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ThoughtData:
        """Validate a serialized (camelCase) record; unknown keys are rejected."""
        if not isinstance(data, dict):
            raise ValueError("Thought record must be an object")
        for field in ("tags", "axiomsUsed", "assumptionsChallenged"):
            value = data.get(field, [])
            if not isinstance(value, list) or any(
                not isinstance(v, str) or len(v) > 1000 for v in value
            ):
                raise ValueError("List fields require strings of at most 1000 characters")
        record = {key: value for key, value in data.items() if key != "type"}
        return cls.model_validate(record, by_alias=True, by_name=False)
