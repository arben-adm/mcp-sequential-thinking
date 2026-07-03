import re
from typing import List, Optional
from enum import Enum
from datetime import datetime
from uuid import uuid4, UUID
from pydantic import BaseModel, Field, field_validator, model_validator, ValidationInfo

# branch_id ends up in files and tool output, so it is restricted to a short,
# filesystem- and log-safe alphabet.
BRANCH_ID_MAX_LENGTH = 64
BRANCH_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class ThoughtStage(Enum):
    """Basic thinking stages for structured sequential thinking."""
    PROBLEM_DEFINITION = "Problem Definition"
    RESEARCH = "Research"
    ANALYSIS = "Analysis"
    SYNTHESIS = "Synthesis"
    CONCLUSION = "Conclusion"

    @classmethod
    def from_string(cls, value: str) -> 'ThoughtStage':
        """Convert a string to a thinking stage.

        Args:
            value: The string representation of the thinking stage

        Returns:
            ThoughtStage: The corresponding ThoughtStage enum value

        Raises:
            ValueError: If the string does not match any valid thinking stage
        """
        # Case-insensitive comparison
        for stage in cls:
            if stage.value.casefold() == value.casefold():
                return stage

        # If no match found
        valid_stages = ", ".join(stage.value for stage in cls)
        raise ValueError(f"Invalid thinking stage: '{value}'. Valid stages are: {valid_stages}")


class ThoughtData(BaseModel):
    """Data structure for a single thought in the sequential thinking process."""
    thought: str
    thought_number: int
    total_thoughts: int
    next_thought_needed: bool
    stage: ThoughtStage
    tags: List[str] = Field(default_factory=list)
    axioms_used: List[str] = Field(default_factory=list)
    assumptions_challenged: List[str] = Field(default_factory=list)
    is_revision: bool = False
    revises_thought_number: Optional[int] = None
    branch_from_thought: Optional[int] = None
    branch_id: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    id: UUID = Field(default_factory=uuid4)

    def __hash__(self) -> int:
        """Make ThoughtData hashable based on its ID."""
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        """Compare ThoughtData objects based on their ID."""
        if not isinstance(other, ThoughtData):
            return False
        return self.id == other.id

    @field_validator('thought')
    @classmethod
    def thought_not_empty(cls, v: str) -> str:
        """Validate that thought content is not empty."""
        if not v or not v.strip():
            raise ValueError("Thought content cannot be empty")
        return v

    @field_validator('thought_number')
    @classmethod
    def thought_number_positive(cls, v: int) -> int:
        """Validate that thought number is positive."""
        if v < 1:
            raise ValueError("Thought number must be positive")
        return v

    @field_validator('total_thoughts')
    @classmethod
    def total_thoughts_valid(cls, v: int, info: ValidationInfo) -> int:
        """Validate that total thoughts is valid."""
        thought_number = info.data.get('thought_number')
        if thought_number is not None and v < thought_number:
            raise ValueError("Total thoughts must be greater or equal to current thought number")
        return v

    @model_validator(mode='after')
    def validate_revision_and_branch(self) -> 'ThoughtData':
        """Validate the cross-field rules for revisions and branches."""
        if self.is_revision and self.revises_thought_number is None:
            raise ValueError("is_revision=True requires revises_thought_number to be set")
        if self.revises_thought_number is not None and not self.is_revision:
            raise ValueError("revises_thought_number requires is_revision=True")
        if self.is_revision and self.branch_from_thought is not None:
            raise ValueError(
                "A thought cannot be a revision and a branch start at the same time"
            )
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
                f"branch_id must be 1-{BRANCH_ID_MAX_LENGTH} characters from "
                "[A-Za-z0-9_-]"
            )

        return self

    def to_dict(self, include_id: bool = False) -> dict:
        """Convert the thought data to a dictionary representation.

        Args:
            include_id: Whether to include the ID in the dictionary representation.
                        Default is False to omit it from external representations.

        Returns:
            dict: Dictionary representation of the thought data, with camelCase
                keys for API consistency.
        """
        result = {
            "thought": self.thought,
            "thoughtNumber": self.thought_number,
            "totalThoughts": self.total_thoughts,
            "nextThoughtNeeded": self.next_thought_needed,
            "stage": self.stage.value,
            "tags": self.tags,
            "axiomsUsed": self.axioms_used,
            "assumptionsChallenged": self.assumptions_challenged,
            "timestamp": self.timestamp,
        }

        # Revision/branch fields are only emitted when set, keeping records
        # compact and older v2 files readable without them.
        if self.is_revision:
            result["isRevision"] = self.is_revision
        if self.revises_thought_number is not None:
            result["revisesThoughtNumber"] = self.revises_thought_number
        if self.branch_from_thought is not None:
            result["branchFromThought"] = self.branch_from_thought
        if self.branch_id is not None:
            result["branchId"] = self.branch_id

        if include_id:
            result["id"] = str(self.id)

        return result

    @classmethod
    def from_dict(cls, data: dict) -> 'ThoughtData':
        """Create a ThoughtData instance from a dictionary.

        Args:
            data: Dictionary containing thought data

        Returns:
            ThoughtData: A new ThoughtData instance
        """
        # Convert any camelCase keys to snake_case
        snake_data = {}
        mappings = {
            "thoughtNumber": "thought_number",
            "totalThoughts": "total_thoughts",
            "nextThoughtNeeded": "next_thought_needed",
            "axiomsUsed": "axioms_used",
            "assumptionsChallenged": "assumptions_challenged",
            "isRevision": "is_revision",
            "revisesThoughtNumber": "revises_thought_number",
            "branchFromThought": "branch_from_thought",
            "branchId": "branch_id"
        }
        
        # Process known direct mappings
        for camel_key, snake_key in mappings.items():
            if camel_key in data:
                snake_data[snake_key] = data[camel_key]
        
        # Copy fields that don't need conversion
        for key in ["thought", "tags", "timestamp"]:
            if key in data:
                snake_data[key] = data[key]
                
        # Handle special fields
        if "stage" in data:
            snake_data["stage"] = ThoughtStage.from_string(data["stage"])
            
        # Set default values for missing fields
        snake_data.setdefault("tags", [])
        snake_data.setdefault("axioms_used", data.get("axiomsUsed", []))
        snake_data.setdefault("assumptions_challenged", data.get("assumptionsChallenged", []))
        snake_data.setdefault("timestamp", datetime.now().isoformat())

        # Add ID if present, otherwise generate a new one
        if "id" in data:
            try:
                snake_data["id"] = UUID(data["id"])
            except (ValueError, TypeError):
                snake_data["id"] = uuid4()

        return cls(**snake_data)

    model_config = {
        "arbitrary_types_allowed": True
    }
