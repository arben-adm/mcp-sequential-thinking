"""Structured output models for MCP tool return values.

Field names are snake_case throughout (SDK 2.x convention) rather than the
camelCase dict shape used before v0.7.0. This is a documented breaking
change (see CHANGELOG.md) — clients reading ``structured_content`` need to
switch key names.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RevisionOf(BaseModel):
    """A snippet of the mainline thought a revision replaces."""

    thought_number: int
    stage: str
    snippet: str


class RelatedThought(BaseModel):
    """A lexically similar thought, possibly in a different stage."""

    number: int
    score: float
    reason: str


class SameCategoryThought(BaseModel):
    """A thought sharing a stage or tag with the current one (categorical,
    not necessarily content-related — see docs/MIGRATION_PLAN.md B4)."""

    number: int
    reason: str


class CurrentThought(BaseModel):
    thought_number: int
    total_thoughts: int
    next_thought_needed: bool
    stage: str
    tags: list[str]
    timestamp: str


class ThoughtAnalysis(BaseModel):
    related_thoughts: list[RelatedThought] = Field(default_factory=list)
    same_category_thoughts: list[SameCategoryThought] = Field(default_factory=list)
    main_line_progress: float
    main_line_position: int
    total_thoughts_recorded: int
    branch_count: int
    revision_count: int
    is_first_in_stage: bool
    is_revision: bool
    revised_thought: int | None = None
    branch_id: str | None = None
    revision_of: RevisionOf | None = None


class ThoughtContext(BaseModel):
    thought_history_length: int
    current_stage: str


class ProcessThoughtResult(BaseModel):
    current_thought: CurrentThought
    analysis: ThoughtAnalysis
    context: ThoughtContext
    warnings: list[str] = Field(default_factory=list)


class StageCompletion(BaseModel):
    stages_covered: int
    stages_total: int
    stage_coverage_percent: float
    has_all_stages: bool
    skipped_stages: list[str] = Field(default_factory=list)


class BranchSummary(BaseModel):
    branch_id: str
    from_thought: int | None
    thought_count: int
    has_conclusion: bool


class RevisionChainEntry(BaseModel):
    original_thought_number: int
    replaced_by: list[int]


class TagCount(BaseModel):
    tag: str
    count: int


class TimelineEntry(BaseModel):
    number: int
    stage: str
    is_revision: bool = False
    branch_id: str | None = None


class StageContent(BaseModel):
    stage: str
    thought_numbers: list[int]
    excerpts: list[str]


class SummaryContent(BaseModel):
    stage_content: list[StageContent]
    assumptions_challenged: list[str]
    open_branches: list[str]
    revision_chains: list[RevisionChainEntry]
    gaps: list[str]


class SummaryStructure(BaseModel):
    total_thoughts: int
    stages: dict[str, int]
    timeline: list[TimelineEntry]
    branches: list[BranchSummary]
    revision_count: int
    top_tags: list[TagCount]
    completion: StageCompletion


class SummaryResult(BaseModel):
    has_thoughts: bool
    message: str | None = None
    content: SummaryContent | None = None
    structure: SummaryStructure | None = None


class ExportResult(BaseModel):
    status: str
    message: str
    thought_count: int
    file_path: str


class ImportResult(BaseModel):
    status: str
    message: str
    thought_count: int


class ClearHistoryResult(BaseModel):
    status: str
    message: str
    cleared_count: int
