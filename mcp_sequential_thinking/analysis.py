from collections import Counter
from typing import Any, Dict, List

from .logging_conf import configure_logging
from .models import ThoughtData, ThoughtStage

logger = configure_logging("sequential-thinking.analysis")


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
        current_thought: ThoughtData, all_thoughts: List[ThoughtData], max_results: int = 3
    ) -> List[ThoughtData]:
        """Find thoughts related to the current thought.

        Args:
            current_thought: The current thought to find related thoughts for
            all_thoughts: All available thoughts to search through
            max_results: Maximum number of related thoughts to return

        Returns:
            List[ThoughtData]: Related thoughts, sorted by relevance
        """
        # First, find thoughts in the same stage
        same_stage = [
            t
            for t in all_thoughts
            if t.stage == current_thought.stage and t.id != current_thought.id
        ]

        # Then, find thoughts with similar tags
        if current_thought.tags:
            tag_matches = []
            for thought in all_thoughts:
                if thought.id == current_thought.id:
                    continue

                # Count matching tags
                matching_tags = set(current_thought.tags) & set(thought.tags)
                if matching_tags:
                    tag_matches.append((thought, len(matching_tags)))

            # Sort by number of matching tags (descending)
            tag_matches.sort(key=lambda x: x[1], reverse=True)
            tag_related = [t[0] for t in tag_matches]
        else:
            tag_related = []

        # Combine and deduplicate results
        combined = []
        seen_ids = set()

        # First add same stage thoughts
        for thought in same_stage:
            if thought.id not in seen_ids:
                combined.append(thought)
                seen_ids.add(thought.id)

                if len(combined) >= max_results:
                    break

        # Then add tag-related thoughts
        if len(combined) < max_results:
            for thought in tag_related:
                if thought.id not in seen_ids:
                    combined.append(thought)
                    seen_ids.add(thought.id)

                    if len(combined) >= max_results:
                        break

        return combined

    @staticmethod
    def generate_summary(thoughts: List[ThoughtData]) -> Dict[str, Any]:
        """Generate a summary of the thinking process.

        Args:
            thoughts: List of thoughts to summarize

        Returns:
            Dict[str, Any]: Summary data
        """
        if not thoughts:
            return {"summary": "No thoughts recorded yet"}

        # Group thoughts by stage
        stages: Dict[str, List[ThoughtData]] = {}
        for thought in thoughts:
            if thought.stage.value not in stages:
                stages[thought.stage.value] = []
            stages[thought.stage.value].append(thought)

        # Count tags - using a more readable approach with explicit steps
        # Collect all tags from all thoughts
        all_tags = []
        for thought in thoughts:
            all_tags.extend(thought.tags)

        # Count occurrences of each tag
        tag_counts = Counter(all_tags)

        # Get the 5 most common tags
        top_tags = tag_counts.most_common(5)

        # Create summary
        try:
            # Progress is based on mainline thoughts only; revisions and
            # branch thoughts don't advance the sequence.
            mainline_thoughts = [t for t in thoughts if ThoughtAnalyzer._is_mainline(t)]

            # Safely calculate max total thoughts to avoid division by zero
            max_total = max((t.total_thoughts for t in mainline_thoughts), default=0)

            # Calculate percent complete safely
            percent_complete: float = 0.0
            if max_total > 0:
                percent_complete = (len(mainline_thoughts) / max_total) * 100

            logger.debug(
                f"Calculating completion: {len(mainline_thoughts)}/{max_total} "
                f"= {percent_complete}%"
            )

            # Build the summary dictionary with more readable and
            # maintainable list comprehensions

            # Count thoughts by stage
            stage_counts = {stage: len(thoughts_list) for stage, thoughts_list in stages.items()}

            # Create timeline entries
            sorted_thoughts = sorted(thoughts, key=lambda x: x.thought_number)
            timeline_entries = []
            for t in sorted_thoughts:
                entry: Dict[str, Any] = {"number": t.thought_number, "stage": t.stage.value}
                if t.is_revision:
                    entry["isRevision"] = True
                if t.branch_id is not None:
                    entry["branchId"] = t.branch_id
                timeline_entries.append(entry)

            # Aggregate branches: first occurrence defines the fork point.
            branches: Dict[str, Dict[str, Any]] = {}
            for t in sorted_thoughts:
                if t.branch_id is None:
                    continue
                if t.branch_id not in branches:
                    branches[t.branch_id] = {
                        "fromThought": t.branch_from_thought,
                        "thoughtCount": 0,
                    }
                branches[t.branch_id]["thoughtCount"] += 1

            revision_count = sum(1 for t in thoughts if t.is_revision)

            # Create top tags entries
            top_tags_entries = []
            for tag, count in top_tags:
                top_tags_entries.append({"tag": tag, "count": count})

            # Check if all stages are represented
            all_stages_present = all(stage.value in stages for stage in ThoughtStage)

            # Assemble the final summary
            summary = {
                "totalThoughts": len(thoughts),
                "stages": stage_counts,
                "timeline": timeline_entries,
                "branches": branches,
                "revisionCount": revision_count,
                "topTags": top_tags_entries,
                "completionStatus": {
                    "hasAllStages": all_stages_present,
                    "percentComplete": percent_complete,
                },
            }
        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            summary = {"totalThoughts": len(thoughts), "error": str(e)}

        return {"summary": summary}

    @staticmethod
    def analyze_thought(thought: ThoughtData, all_thoughts: List[ThoughtData]) -> Dict[str, Any]:
        """Analyze a single thought in the context of all thoughts.

        Args:
            thought: The thought to analyze
            all_thoughts: All available thoughts for context

        Returns:
            Dict[str, Any]: Analysis results
        """
        # Find related thoughts
        related_thoughts = ThoughtAnalyzer.find_related_thoughts(thought, all_thoughts)

        # Check if this is the first thought in its stage (lowest thought_number)
        same_stage_thoughts = [t for t in all_thoughts if t.stage == thought.stage]
        is_first_in_stage = all(
            t.thought_number >= thought.thought_number for t in same_stage_thoughts
        )

        # Calculate progress. Revisions and branch thoughts don't advance the
        # sequence, so for them progress reflects the mainline position instead
        # of their own number (which may exceed total_thoughts).
        if ThoughtAnalyzer._is_mainline(thought):
            effective_number = thought.thought_number
        else:
            effective_number = max(
                (t.thought_number for t in all_thoughts if ThoughtAnalyzer._is_mainline(t)),
                default=0,
            )
        progress = (effective_number / thought.total_thoughts) * 100

        # For a revision, surface a snippet of the mainline thought it revises.
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
                revision_of = {
                    "thoughtNumber": revised.thought_number,
                    "stage": revised.stage.value,
                    "snippet": (
                        revised.thought[:100] + "..."
                        if len(revised.thought) > 100
                        else revised.thought
                    ),
                }

        # Create analysis
        analysis_block: Dict[str, Any] = {
            "relatedThoughtsCount": len(related_thoughts),
            "relatedThoughtSummaries": [
                {
                    "thoughtNumber": t.thought_number,
                    "stage": t.stage.value,
                    "snippet": (
                        t.thought[:100] + "..." if len(t.thought) > 100 else t.thought
                    ),
                }
                for t in related_thoughts
            ],
            "progress": progress,
            "isFirstInStage": is_first_in_stage,
            "isRevision": thought.is_revision,
            "revisedThought": thought.revises_thought_number,
            "branchId": thought.branch_id,
        }
        if revision_of is not None:
            analysis_block["revisionOf"] = revision_of

        return {
            "thoughtAnalysis": {
                "currentThought": {
                    "thoughtNumber": thought.thought_number,
                    "totalThoughts": thought.total_thoughts,
                    "nextThoughtNeeded": thought.next_thought_needed,
                    "stage": thought.stage.value,
                    "tags": thought.tags,
                    "timestamp": thought.timestamp,
                },
                "analysis": analysis_block,
                "context": {
                    "thoughtHistoryLength": len(all_thoughts),
                    "currentStage": thought.stage.value,
                },
            }
        }
