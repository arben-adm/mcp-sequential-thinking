from __future__ import annotations

import re
from collections import Counter, defaultdict

from .logging_conf import configure_logging
from .models import ThoughtData, ThoughtStage
from .schemas import (
    BranchSummary,
    CurrentThought,
    ProcessThoughtResult,
    RelatedThought,
    RevisionChainEntry,
    RevisionOf,
    SameCategoryThought,
    StageCompletion,
    StageContent,
    SummaryContent,
    SummaryResult,
    SummaryStructure,
    TagCount,
    ThoughtAnalysis,
    ThoughtContext,
    TimelineEntry,
)

logger = configure_logging("sequential-thinking.analysis")

# B4: thresholds for the lexical relatedness match. Kept as module constants
# rather than buried magic numbers so they're easy to revisit; see
# docs/MIGRATION_PLAN.md section 5 for the trade-off discussion.
MIN_SIMILARITY = 0.2
MAX_RELATED = 3
MAX_SAME_CATEGORY = 3
EXCERPT_LENGTH = 100
TOP_TAGS_COUNT = 5

_STOPWORDS_EN = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "has", "have", "if", "in", "into", "is", "it", "its", "of", "on", "or",
    "that", "the", "their", "then", "there", "this", "to", "was", "were",
    "will", "with", "about", "after", "all", "also", "any", "because",
    "been", "being", "between", "both", "can", "could", "did", "does",
    "each", "further", "how", "into", "more", "most", "not", "over",
    "should", "some", "such", "than", "these", "those", "through", "under",
    "very", "what", "when", "where", "which", "while", "who", "why",
}
_STOPWORDS_DE = {
    "aber", "als", "am", "an", "auch", "auf", "aus", "bei", "bin", "bis",
    "bist", "da", "damit", "dann", "das", "dass", "dein", "deine", "dem",
    "den", "der", "des", "dessen", "die", "dies", "diese", "diesem",
    "diesen", "dieser", "dieses", "doch", "dort", "du", "durch", "ein",
    "eine", "einem", "einen", "einer", "eines", "einige", "er", "es",
    "euer", "eure", "für", "hab", "habe", "haben", "hat", "hatte",
    "hatten", "hier", "ich", "ihm", "ihn", "ihnen", "ihr", "ihre", "im",
    "in", "ist", "ja", "jede", "jedem", "jeden", "jeder", "jedes", "jener",
    "jetzt", "kann", "kein", "können", "könnte", "machen", "man", "mehr",
    "mein", "meine", "mit", "muss", "musste", "nach", "nicht", "noch",
    "nun", "nur", "ob", "oder", "seid", "sein", "seine", "sich", "sie",
    "sind", "so", "soll", "sollte", "sondern", "sonst", "über", "um",
    "und", "uns", "unser", "unter", "viel", "vom", "von", "vor", "war",
    "waren", "warum", "was", "weiter", "weitere", "wenn", "wer", "werde",
    "werden", "wie", "wieder", "will", "wir", "wird", "wirst", "wo",
    "wollen", "wollte", "würde", "würden", "zu", "zum", "zur", "zwar",
    "zwischen",
}
STOPWORDS = _STOPWORDS_EN | _STOPWORDS_DE

_TOKEN_RE = re.compile(r"[^\W\d_]+|\d+", re.UNICODE)

# Enum member order defines the canonical stage sequence used for
# stage-coverage percentages (B2) and stage-order warnings (B6).
_STAGE_ORDER: dict[ThoughtStage, int] = {stage: i for i, stage in enumerate(ThoughtStage)}


def _tokenize(text: str) -> set[str]:
    """Lowercase, split into word tokens, strip stopwords and 1-2 char noise."""
    tokens = {t.lower() for t in _TOKEN_RE.findall(text)}
    return {t for t in tokens if t not in STOPWORDS and len(t) > 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


def _excerpt(text: str, length: int = EXCERPT_LENGTH) -> str:
    """First sentence, or a truncated prefix if there's no sentence break."""
    match = re.search(r"[.!?]", text)
    if match and match.end() <= length:
        return text[: match.end()]
    return text[:length] + "…" if len(text) > length else text


class ThoughtAnalyzer:
    """Analyzer for thought data to extract insights and patterns."""

    @staticmethod
    def _is_mainline(thought: ThoughtData) -> bool:
        """Whether a thought belongs to the main line of reasoning.

        Revisions and branch thoughts are excluded from progress metrics:
        counting them would report e.g. 160% for a 5-thought session with
        3 revisions.
        """
        return not thought.is_revision and thought.branch_id is None

    @staticmethod
    def find_related_thoughts(
        current_thought: ThoughtData,
        all_thoughts: list[ThoughtData],
        max_results: int = MAX_RELATED,
    ) -> list[RelatedThought]:
        """Find thoughts that are lexically similar to ``current_thought``,
        regardless of stage (B4: content relevance, not category).

        Args:
            current_thought: The current thought to find related thoughts for
            all_thoughts: All available thoughts to search through
            max_results: Maximum number of related thoughts to return

        Returns:
            Thoughts scored by Jaccard token-set similarity, descending.
        """
        current_tokens = _tokenize(current_thought.thought)
        scored: list[tuple[ThoughtData, float]] = []
        for thought in all_thoughts:
            if thought.id == current_thought.id:
                continue
            score = _jaccard(current_tokens, _tokenize(thought.thought))
            if score >= MIN_SIMILARITY:
                scored.append((thought, score))

        scored.sort(key=lambda pair: (pair[1], pair[0].thought_number), reverse=True)
        return [
            RelatedThought(number=t.thought_number, score=round(score, 4), reason="lexical")
            for t, score in scored[:max_results]
        ]

    @staticmethod
    def find_same_category_thoughts(
        current_thought: ThoughtData,
        all_thoughts: list[ThoughtData],
        max_results: int = MAX_SAME_CATEGORY,
    ) -> list[SameCategoryThought]:
        """Find thoughts sharing a tag with ``current_thought`` (B4 fallback).

        Stage equality alone is deliberately *not* a match here — it isn't
        semantic relevance, just calendar proximity in the thinking process.
        Only a shared tag counts.
        """
        if not current_thought.tags:
            return []

        current_tags = set(current_thought.tags)
        matches: list[tuple[ThoughtData, str]] = []
        for thought in all_thoughts:
            if thought.id == current_thought.id:
                continue
            shared = current_tags & set(thought.tags)
            if shared:
                matches.append((thought, f"tag:{sorted(shared)[0]}"))

        matches.sort(key=lambda pair: pair[0].thought_number)
        return [
            SameCategoryThought(number=t.thought_number, reason=reason)
            for t, reason in matches[:max_results]
        ]

    @staticmethod
    def detect_stage_transition_issue(
        thought: ThoughtData, all_thoughts: list[ThoughtData]
    ) -> str | None:
        """Detect a stage skip or regression relative to the previous
        mainline thought (B6). Returns ``None`` for the first mainline
        thought, a sequential step, a repeated stage, or any
        revision/branch thought (those legitimately explore out of order).
        """
        if not ThoughtAnalyzer._is_mainline(thought):
            return None

        prior_mainline = [
            t
            for t in all_thoughts
            if ThoughtAnalyzer._is_mainline(t)
            and t.id != thought.id
            and t.thought_number < thought.thought_number
        ]
        if not prior_mainline:
            return None

        previous = max(prior_mainline, key=lambda t: t.thought_number)
        prev_idx = _STAGE_ORDER[previous.stage]
        cur_idx = _STAGE_ORDER[thought.stage]

        if cur_idx > prev_idx + 1:
            skipped = [s.value for s in list(ThoughtStage)[prev_idx + 1 : cur_idx]]
            return (
                f"Stage jump: skipped {', '.join(skipped)} going from "
                f"'{previous.stage.value}' (thought #{previous.thought_number}) to "
                f"'{thought.stage.value}' (thought #{thought.thought_number})"
            )
        if cur_idx < prev_idx:
            return (
                f"Stage regression: moved back from '{previous.stage.value}' "
                f"(thought #{previous.thought_number}) to '{thought.stage.value}' "
                f"(thought #{thought.thought_number})"
            )
        return None

    @staticmethod
    def _stage_completion(thoughts: list[ThoughtData]) -> StageCompletion:
        """Stage-coverage percentage (B2): denominator is always
        ``len(ThoughtStage)``, derived from the enum, never hardcoded."""
        stages_total = len(ThoughtStage)
        covered = {t.stage for t in thoughts}
        stages_covered = len(covered)
        percent = (stages_covered / stages_total) * 100 if stages_total else 0.0
        skipped = [s.value for s in ThoughtStage if s not in covered]
        return StageCompletion(
            stages_covered=stages_covered,
            stages_total=stages_total,
            stage_coverage_percent=percent,
            has_all_stages=stages_covered == stages_total,
            skipped_stages=skipped,
        )

    @staticmethod
    def generate_summary(thoughts: list[ThoughtData]) -> SummaryResult:
        """Generate a summary of the thinking process.

        Unlike the pre-0.7.0 version, this includes the actual thought
        content (B5) — excerpts per stage, aggregated challenged
        assumptions, open branches, and revision chains — not just
        structural statistics.

        Args:
            thoughts: List of thoughts to summarize

        Returns:
            SummaryResult: ``content`` (the thinking itself) and
                ``structure`` (counts/timeline/tags), or ``has_thoughts=False``
                with a message if there's nothing recorded yet.
        """
        if not thoughts:
            return SummaryResult(has_thoughts=False, message="No thoughts recorded yet")

        sorted_thoughts = sorted(thoughts, key=lambda t: t.thought_number)
        mainline_thoughts = [t for t in thoughts if ThoughtAnalyzer._is_mainline(t)]

        # --- structure.stage_content / content section -------------------
        by_stage: dict[ThoughtStage, list[ThoughtData]] = defaultdict(list)
        for t in sorted_thoughts:
            by_stage[t.stage].append(t)

        stage_content = [
            StageContent(
                stage=stage.value,
                thought_numbers=[t.thought_number for t in by_stage[stage]],
                excerpts=[_excerpt(t.thought) for t in by_stage[stage]],
            )
            for stage in ThoughtStage
            if stage in by_stage
        ]

        assumptions_challenged: list[str] = []
        seen_assumptions: set[str] = set()
        for t in sorted_thoughts:
            for assumption in t.assumptions_challenged:
                if assumption not in seen_assumptions:
                    seen_assumptions.add(assumption)
                    assumptions_challenged.append(assumption)

        # A branch is "open" if none of its thoughts signaled the sequence
        # was done (next_thought_needed=False).
        branch_thoughts: dict[str, list[ThoughtData]] = defaultdict(list)
        for t in sorted_thoughts:
            if t.branch_id is not None:
                branch_thoughts[t.branch_id].append(t)
        open_branches = [
            branch_id
            for branch_id, ts in branch_thoughts.items()
            if all(t.next_thought_needed for t in ts)
        ]

        revision_map: dict[int, list[int]] = defaultdict(list)
        for t in sorted_thoughts:
            if t.is_revision and t.revises_thought_number is not None:
                revision_map[t.revises_thought_number].append(t.thought_number)
        revision_chains = [
            RevisionChainEntry(original_thought_number=original, replaced_by=sorted(by))
            for original, by in sorted(revision_map.items())
        ]

        gaps: list[str] = []
        for t in mainline_thoughts:
            issue = ThoughtAnalyzer.detect_stage_transition_issue(t, thoughts)
            if issue:
                gaps.append(issue)

        content = SummaryContent(
            stage_content=stage_content,
            assumptions_challenged=assumptions_challenged,
            open_branches=open_branches,
            revision_chains=revision_chains,
            gaps=gaps,
        )

        # --- structure section (statistics only) --------------------------
        stage_counts = {stage.value: len(ts) for stage, ts in by_stage.items()}

        timeline_entries = [
            TimelineEntry(
                number=t.thought_number,
                stage=t.stage.value,
                is_revision=t.is_revision,
                branch_id=t.branch_id,
            )
            for t in sorted_thoughts
        ]

        branches: dict[str, BranchSummary] = {}
        for t in sorted_thoughts:
            if t.branch_id is None:
                continue
            if t.branch_id not in branches:
                branches[t.branch_id] = BranchSummary(
                    branch_id=t.branch_id,
                    from_thought=t.branch_from_thought,
                    thought_count=0,
                    has_conclusion=False,
                )
            branches[t.branch_id].thought_count += 1
            if not t.next_thought_needed:
                branches[t.branch_id].has_conclusion = True

        revision_count = sum(1 for t in thoughts if t.is_revision)

        all_tags = [tag for t in thoughts for tag in t.tags]
        top_tags = [
            TagCount(tag=tag, count=count)
            for tag, count in Counter(all_tags).most_common(TOP_TAGS_COUNT)
        ]

        structure = SummaryStructure(
            total_thoughts=len(thoughts),
            stages=stage_counts,
            timeline=timeline_entries,
            branches=list(branches.values()),
            revision_count=revision_count,
            top_tags=top_tags,
            completion=ThoughtAnalyzer._stage_completion(thoughts),
        )

        return SummaryResult(has_thoughts=True, content=content, structure=structure)

    @staticmethod
    def analyze_thought(
        thought: ThoughtData,
        all_thoughts: list[ThoughtData],
        warnings: list[str] | None = None,
    ) -> ProcessThoughtResult:
        """Analyze a single thought in the context of all thoughts.

        Args:
            thought: The thought to analyze
            all_thoughts: All available thoughts for context (includes ``thought``)
            warnings: Precomputed warnings (e.g. stage-order, from B6) to
                attach to the result. Detection is a policy decision made by
                the caller (permissive vs. ``strict_stages``); this method
                only carries the result through.

        Returns:
            ProcessThoughtResult: Typed analysis results (B3/B4 shapes).
        """
        related_thoughts = ThoughtAnalyzer.find_related_thoughts(thought, all_thoughts)
        same_category_thoughts = ThoughtAnalyzer.find_same_category_thoughts(thought, all_thoughts)

        same_stage_thoughts = [t for t in all_thoughts if t.stage == thought.stage]
        is_first_in_stage = all(
            t.thought_number >= thought.thought_number for t in same_stage_thoughts
        )

        # B3: explicit, unambiguous progress fields instead of a single
        # overloaded "progress" scalar.
        mainline_thoughts = [t for t in all_thoughts if ThoughtAnalyzer._is_mainline(t)]
        main_line_position = len(
            [t for t in mainline_thoughts if t.thought_number <= thought.thought_number]
        )
        if not ThoughtAnalyzer._is_mainline(thought):
            main_line_position = len(mainline_thoughts)
        total_thoughts_recorded = len(all_thoughts)
        branch_count = len({t.branch_id for t in all_thoughts if t.branch_id is not None})
        revision_count = sum(1 for t in all_thoughts if t.is_revision)
        main_line_progress = (
            (main_line_position / thought.total_thoughts) * 100
            if thought.total_thoughts
            else 0.0
        )

        revision_of = None
        if thought.is_revision and thought.revises_thought_number is not None:
            revised = next(
                (
                    t
                    for t in all_thoughts
                    if ThoughtAnalyzer._is_mainline(t)
                    and t.thought_number == thought.revises_thought_number
                ),
                None,
            )
            if revised is not None:
                revision_of = RevisionOf(
                    thought_number=revised.thought_number,
                    stage=revised.stage.value,
                    snippet=_excerpt(revised.thought),
                )

        analysis_block = ThoughtAnalysis(
            related_thoughts=related_thoughts,
            same_category_thoughts=same_category_thoughts,
            main_line_progress=main_line_progress,
            main_line_position=main_line_position,
            total_thoughts_recorded=total_thoughts_recorded,
            branch_count=branch_count,
            revision_count=revision_count,
            is_first_in_stage=is_first_in_stage,
            is_revision=thought.is_revision,
            revised_thought=thought.revises_thought_number,
            branch_id=thought.branch_id,
            revision_of=revision_of,
        )

        return ProcessThoughtResult(
            current_thought=CurrentThought(
                thought_number=thought.thought_number,
                total_thoughts=thought.total_thoughts,
                next_thought_needed=thought.next_thought_needed,
                stage=thought.stage.value,
                tags=thought.tags,
                timestamp=thought.timestamp,
            ),
            analysis=analysis_block,
            context=ThoughtContext(
                thought_history_length=len(all_thoughts),
                current_stage=thought.stage.value,
            ),
            warnings=warnings or [],
        )
