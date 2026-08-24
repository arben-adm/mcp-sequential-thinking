import unittest

from mcp_sequential_thinking.analysis import ThoughtAnalyzer
from mcp_sequential_thinking.models import ThoughtData, ThoughtStage


class TestThoughtAnalyzer(unittest.TestCase):
    """Test cases for the ThoughtAnalyzer class."""

    def setUp(self):
        """Set up test data."""
        self.thought1 = ThoughtData(
            thought="First thought about climate change and emissions policy",
            thought_number=1,
            total_thoughts=5,
            next_thought_needed=True,
            stage=ThoughtStage.PROBLEM_DEFINITION,
            tags=["climate", "global"],
        )

        self.thought2 = ThoughtData(
            thought="Research on emissions data",
            thought_number=2,
            total_thoughts=5,
            next_thought_needed=True,
            stage=ThoughtStage.RESEARCH,
            tags=["climate", "data", "emissions"],
        )

        self.thought3 = ThoughtData(
            thought="Analysis of policy impacts",
            thought_number=3,
            total_thoughts=5,
            next_thought_needed=True,
            stage=ThoughtStage.ANALYSIS,
            tags=["policy", "impact"],
        )

        self.thought4 = ThoughtData(
            thought="Another problem definition thought",
            thought_number=4,
            total_thoughts=5,
            next_thought_needed=True,
            stage=ThoughtStage.PROBLEM_DEFINITION,
            tags=["problem", "definition"],
        )

        self.all_thoughts = [self.thought1, self.thought2, self.thought3, self.thought4]

    # ------------------------------------------------------------------
    # B4: lexical relatedness instead of pure category matching
    # ------------------------------------------------------------------
    def test_related_thoughts_matches_across_stages_by_content(self):
        """Two lexically similar thoughts in different stages must match."""
        a = ThoughtData(
            thought="The project deadline keeps slipping because of scope creep",
            thought_number=1,
            total_thoughts=2,
            next_thought_needed=True,
            stage=ThoughtStage.PROBLEM_DEFINITION,
        )
        b = ThoughtData(
            thought="Scope creep is the main reason the deadline keeps slipping",
            thought_number=2,
            total_thoughts=2,
            next_thought_needed=False,
            stage=ThoughtStage.CONCLUSION,
        )

        related = ThoughtAnalyzer.find_related_thoughts(a, [a, b])

        self.assertEqual(len(related), 1)
        self.assertEqual(related[0].number, 2)
        self.assertEqual(related[0].reason, "lexical")
        self.assertGreater(related[0].score, 0.0)

    def test_related_thoughts_same_stage_unrelated_content_no_match(self):
        """Two unrelated thoughts in the same stage must not match."""
        a = ThoughtData(
            thought="We should interview five customers about pricing",
            thought_number=1,
            total_thoughts=2,
            next_thought_needed=True,
            stage=ThoughtStage.RESEARCH,
        )
        b = ThoughtData(
            thought="The server logs rotate every midnight automatically",
            thought_number=2,
            total_thoughts=2,
            next_thought_needed=False,
            stage=ThoughtStage.RESEARCH,
        )

        related = ThoughtAnalyzer.find_related_thoughts(a, [a, b])

        self.assertEqual(related, [])

    def test_same_category_thoughts_requires_tag_overlap_not_just_stage(self):
        """Stage equality alone is not a same_category match; a shared tag is required."""
        a = ThoughtData(
            thought="Unrelated content A",
            thought_number=1,
            total_thoughts=2,
            next_thought_needed=True,
            stage=ThoughtStage.RESEARCH,
            tags=["alpha"],
        )
        same_stage_no_tag = ThoughtData(
            thought="Unrelated content B",
            thought_number=2,
            total_thoughts=2,
            next_thought_needed=False,
            stage=ThoughtStage.RESEARCH,
            tags=["beta"],
        )
        self.assertEqual(ThoughtAnalyzer.find_same_category_thoughts(a, [a, same_stage_no_tag]), [])

        shared_tag = ThoughtData(
            thought="Unrelated content C",
            thought_number=3,
            total_thoughts=3,
            next_thought_needed=False,
            stage=ThoughtStage.CONCLUSION,
            tags=["alpha"],
        )
        matches = ThoughtAnalyzer.find_same_category_thoughts(a, [a, same_stage_no_tag, shared_tag])
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].number, 3)
        self.assertEqual(matches[0].reason, "tag:alpha")

    # ------------------------------------------------------------------
    # B2: stage-coverage percentage always derived from len(ThoughtStage)
    # ------------------------------------------------------------------
    def test_percent_complete_denominator_matches_enum(self):
        """stage_coverage_percent's denominator is len(ThoughtStage) for every
        count of distinct stages used, 0 through 5."""
        all_stages = list(ThoughtStage)
        self.assertEqual(len(all_stages), 5)

        for k in range(len(all_stages) + 1):
            with self.subTest(stages_used=k):
                thoughts = [
                    ThoughtData(
                        thought=f"Thought number {i + 1} in {all_stages[i].value}",
                        thought_number=i + 1,
                        total_thoughts=max(k, 1),
                        next_thought_needed=True,
                        stage=all_stages[i],
                    )
                    for i in range(k)
                ]

                summary = ThoughtAnalyzer.generate_summary(thoughts)

                if k == 0:
                    self.assertFalse(summary.has_thoughts)
                    continue

                completion = summary.structure.completion
                self.assertEqual(completion.stages_total, 5)
                self.assertEqual(completion.stages_covered, k)
                self.assertAlmostEqual(completion.stage_coverage_percent, (k / 5) * 100)
                self.assertEqual(completion.has_all_stages, k == 5)
                self.assertEqual(len(completion.skipped_stages), 5 - k)

    # ------------------------------------------------------------------
    # B3: explicit progress fields instead of one ambiguous scalar
    # ------------------------------------------------------------------
    def test_progress_fields_after_revision_and_branch(self):
        """main_line_position/total_thoughts_recorded/branch_count/revision_count
        each report something distinct instead of one frozen 'progress' value."""
        mainline = ThoughtData(
            thought="Mainline thought one",
            thought_number=1,
            total_thoughts=3,
            next_thought_needed=True,
            stage=ThoughtStage.PROBLEM_DEFINITION,
        )
        revision = ThoughtData(
            thought="Revision of thought one",
            thought_number=2,
            total_thoughts=3,
            next_thought_needed=True,
            stage=ThoughtStage.PROBLEM_DEFINITION,
            is_revision=True,
            revises_thought_number=1,
        )
        branch = ThoughtData(
            thought="Alternative path from thought one",
            thought_number=3,
            total_thoughts=3,
            next_thought_needed=False,
            stage=ThoughtStage.RESEARCH,
            branch_from_thought=1,
            branch_id="alt",
        )
        all_thoughts = [mainline, revision, branch]

        result = ThoughtAnalyzer.analyze_thought(branch, all_thoughts)
        block = result.analysis

        self.assertEqual(block.main_line_position, 1)
        self.assertEqual(block.total_thoughts_recorded, 3)
        self.assertEqual(block.branch_count, 1)
        self.assertEqual(block.revision_count, 1)
        self.assertAlmostEqual(block.main_line_progress, (1 / 3) * 100)

    def test_progress_ignores_revisions_and_branches(self):
        """Revisions and branch thoughts don't advance main_line_position."""
        revision = ThoughtData(
            thought="Revising the problem definition",
            thought_number=5,
            total_thoughts=5,
            next_thought_needed=True,
            stage=ThoughtStage.PROBLEM_DEFINITION,
            is_revision=True,
            revises_thought_number=1,
        )
        branch = ThoughtData(
            thought="Branching into an alternative",
            thought_number=6,
            total_thoughts=6,
            next_thought_needed=True,
            stage=ThoughtStage.ANALYSIS,
            branch_from_thought=3,
            branch_id="alt",
        )
        all_thoughts = self.all_thoughts + [revision, branch]

        analysis = ThoughtAnalyzer.analyze_thought(revision, all_thoughts).analysis
        # 4 mainline thoughts total; a revision/branch reports the mainline
        # position, not its own (out-of-range) thought_number.
        self.assertEqual(analysis.main_line_position, 4)

    # ------------------------------------------------------------------
    # B6: stage-order detection (permissive by default; policy applied by server.py)
    # ------------------------------------------------------------------
    def test_detect_stage_transition_issue_sequential_is_none(self):
        prev = ThoughtData(
            thought="Research thought",
            thought_number=1,
            total_thoughts=2,
            next_thought_needed=True,
            stage=ThoughtStage.RESEARCH,
        )
        nxt = ThoughtData(
            thought="Analysis thought",
            thought_number=2,
            total_thoughts=2,
            next_thought_needed=False,
            stage=ThoughtStage.ANALYSIS,
        )
        self.assertIsNone(ThoughtAnalyzer.detect_stage_transition_issue(nxt, [prev, nxt]))

    def test_detect_stage_transition_issue_skip_warns(self):
        prev = ThoughtData(
            thought="Problem definition thought",
            thought_number=1,
            total_thoughts=2,
            next_thought_needed=True,
            stage=ThoughtStage.PROBLEM_DEFINITION,
        )
        nxt = ThoughtData(
            thought="Jumps straight to synthesis",
            thought_number=2,
            total_thoughts=2,
            next_thought_needed=False,
            stage=ThoughtStage.SYNTHESIS,
        )
        issue = ThoughtAnalyzer.detect_stage_transition_issue(nxt, [prev, nxt])
        self.assertIsNotNone(issue)
        self.assertIn("skipped", issue)
        self.assertIn("Research", issue)
        self.assertIn("Analysis", issue)

    def test_detect_stage_transition_issue_regression_warns(self):
        prev = ThoughtData(
            thought="Synthesis thought",
            thought_number=1,
            total_thoughts=2,
            next_thought_needed=True,
            stage=ThoughtStage.SYNTHESIS,
        )
        nxt = ThoughtData(
            thought="Back to problem definition",
            thought_number=2,
            total_thoughts=2,
            next_thought_needed=False,
            stage=ThoughtStage.PROBLEM_DEFINITION,
        )
        issue = ThoughtAnalyzer.detect_stage_transition_issue(nxt, [prev, nxt])
        self.assertIsNotNone(issue)
        self.assertIn("regression", issue.lower())

    def test_detect_stage_transition_issue_ignores_revision_and_branch(self):
        prev = ThoughtData(
            thought="Problem definition",
            thought_number=1,
            total_thoughts=3,
            next_thought_needed=True,
            stage=ThoughtStage.PROBLEM_DEFINITION,
        )
        revision = ThoughtData(
            thought="Revision jumping stage on purpose",
            thought_number=2,
            total_thoughts=3,
            next_thought_needed=True,
            stage=ThoughtStage.CONCLUSION,
            is_revision=True,
            revises_thought_number=1,
        )
        self.assertIsNone(ThoughtAnalyzer.detect_stage_transition_issue(revision, [prev, revision]))

    def test_detect_stage_transition_issue_first_thought_is_none(self):
        first = ThoughtData(
            thought="Starting straight in synthesis, no prior thoughts",
            thought_number=1,
            total_thoughts=1,
            next_thought_needed=False,
            stage=ThoughtStage.SYNTHESIS,
        )
        self.assertIsNone(ThoughtAnalyzer.detect_stage_transition_issue(first, [first]))

    # ------------------------------------------------------------------
    # B5: generate_summary carries the actual thinking, not just counters
    # ------------------------------------------------------------------
    def test_generate_summary_empty(self):
        summary = ThoughtAnalyzer.generate_summary([])
        self.assertFalse(summary.has_thoughts)
        self.assertEqual(summary.message, "No thoughts recorded yet")

    def test_summary_contains_thought_content(self):
        """The summary must contain substrings of the actual thoughts, not
        just structural counts (B5)."""
        summary = ThoughtAnalyzer.generate_summary(self.all_thoughts)

        self.assertTrue(summary.has_thoughts)
        all_excerpts = " ".join(
            excerpt for stage in summary.content.stage_content for excerpt in stage.excerpts
        )
        self.assertIn("climate change", all_excerpts)
        self.assertIn("emissions data", all_excerpts)
        self.assertIn("policy impacts", all_excerpts)

    def test_summary_aggregates_assumptions_challenged(self):
        t = ThoughtData(
            thought="Challenging an assumption",
            thought_number=1,
            total_thoughts=1,
            next_thought_needed=False,
            stage=ThoughtStage.ANALYSIS,
            assumptions_challenged=["Growth is always good", "More data is always better"],
        )
        summary = ThoughtAnalyzer.generate_summary([t])
        self.assertEqual(
            summary.content.assumptions_challenged,
            ["Growth is always good", "More data is always better"],
        )

    def test_summary_flags_open_branch_without_conclusion(self):
        mainline = ThoughtData(
            thought="Mainline",
            thought_number=1,
            total_thoughts=2,
            next_thought_needed=True,
            stage=ThoughtStage.ANALYSIS,
        )
        open_branch = ThoughtData(
            thought="Exploring but not done",
            thought_number=2,
            total_thoughts=2,
            next_thought_needed=True,
            stage=ThoughtStage.ANALYSIS,
            branch_from_thought=1,
            branch_id="open-branch",
        )
        closed_branch = ThoughtData(
            thought="Exploring and concluding",
            thought_number=3,
            total_thoughts=3,
            next_thought_needed=False,
            stage=ThoughtStage.CONCLUSION,
            branch_from_thought=1,
            branch_id="closed-branch",
        )
        summary = ThoughtAnalyzer.generate_summary([mainline, open_branch, closed_branch])
        self.assertEqual(summary.content.open_branches, ["open-branch"])

    def test_summary_builds_revision_chains(self):
        original = ThoughtData(
            thought="Original claim",
            thought_number=1,
            total_thoughts=3,
            next_thought_needed=True,
            stage=ThoughtStage.ANALYSIS,
        )
        revision1 = ThoughtData(
            thought="First revision",
            thought_number=2,
            total_thoughts=3,
            next_thought_needed=True,
            stage=ThoughtStage.ANALYSIS,
            is_revision=True,
            revises_thought_number=1,
        )
        revision2 = ThoughtData(
            thought="Second revision of the same claim",
            thought_number=3,
            total_thoughts=3,
            next_thought_needed=False,
            stage=ThoughtStage.ANALYSIS,
            is_revision=True,
            revises_thought_number=1,
        )
        summary = ThoughtAnalyzer.generate_summary([original, revision1, revision2])
        self.assertEqual(len(summary.content.revision_chains), 1)
        chain = summary.content.revision_chains[0]
        self.assertEqual(chain.original_thought_number, 1)
        self.assertEqual(chain.replaced_by, [2, 3])

    def test_summary_counts_branches_and_revisions(self):
        revision = ThoughtData(
            thought="Revision of thought 2",
            thought_number=5,
            total_thoughts=5,
            next_thought_needed=True,
            stage=ThoughtStage.RESEARCH,
            is_revision=True,
            revises_thought_number=2,
        )
        branch_a = ThoughtData(
            thought="First thought on branch alt",
            thought_number=6,
            total_thoughts=6,
            next_thought_needed=True,
            stage=ThoughtStage.ANALYSIS,
            branch_from_thought=3,
            branch_id="alt",
        )
        branch_b = ThoughtData(
            thought="Second thought on branch alt",
            thought_number=7,
            total_thoughts=7,
            next_thought_needed=False,
            stage=ThoughtStage.SYNTHESIS,
            branch_from_thought=3,
            branch_id="alt",
        )
        all_thoughts = self.all_thoughts + [revision, branch_a, branch_b]

        structure = ThoughtAnalyzer.generate_summary(all_thoughts).structure

        self.assertEqual(structure.revision_count, 1)
        self.assertEqual(len(structure.branches), 1)
        self.assertEqual(structure.branches[0].branch_id, "alt")
        self.assertEqual(structure.branches[0].from_thought, 3)
        self.assertEqual(structure.branches[0].thought_count, 2)
        self.assertTrue(structure.branches[0].has_conclusion)

        by_number = {e.number: e for e in structure.timeline}
        self.assertTrue(by_number[5].is_revision)
        self.assertEqual(by_number[6].branch_id, "alt")
        self.assertFalse(by_number[1].is_revision)
        self.assertIsNone(by_number[1].branch_id)

    # ------------------------------------------------------------------
    # analyze_thought: revision-of snippet, first-in-stage, "don't touch"
    # ------------------------------------------------------------------
    def test_analyze_revision_includes_revision_of(self):
        revision = ThoughtData(
            thought="Better framing of the problem",
            thought_number=5,
            total_thoughts=5,
            next_thought_needed=True,
            stage=ThoughtStage.PROBLEM_DEFINITION,
            is_revision=True,
            revises_thought_number=1,
        )
        all_thoughts = self.all_thoughts + [revision]

        analysis = ThoughtAnalyzer.analyze_thought(revision, all_thoughts).analysis

        self.assertTrue(analysis.is_revision)
        self.assertEqual(analysis.revised_thought, 1)
        self.assertIsNone(analysis.branch_id)
        self.assertEqual(analysis.revision_of.thought_number, 1)
        self.assertIn("First thought about climate change", analysis.revision_of.snippet)

    def test_analyze_revision_of_nonexistent_thought_does_not_crash(self):
        """Revising a thought_number that was never actually recorded is a
        no-op for revision_of, not a crash (don't-touch behavior)."""
        revision = ThoughtData(
            thought="Revises a thought that isn't in history",
            thought_number=5,
            total_thoughts=5,
            next_thought_needed=True,
            stage=ThoughtStage.ANALYSIS,
            is_revision=True,
            revises_thought_number=1,
        )
        analysis = ThoughtAnalyzer.analyze_thought(revision, [revision]).analysis
        self.assertIsNone(analysis.revision_of)
        self.assertEqual(analysis.revised_thought, 1)

    def test_analyze_mainline_thought_reports_revision_fields(self):
        analysis = ThoughtAnalyzer.analyze_thought(self.thought1, self.all_thoughts).analysis

        self.assertFalse(analysis.is_revision)
        self.assertIsNone(analysis.revised_thought)
        self.assertIsNone(analysis.branch_id)
        self.assertIsNone(analysis.revision_of)

    def test_analyze_thought(self):
        result = ThoughtAnalyzer.analyze_thought(self.thought1, self.all_thoughts)

        self.assertEqual(result.current_thought.thought_number, 1)
        self.assertEqual(result.current_thought.stage, "Problem Definition")
        self.assertTrue(result.analysis.is_first_in_stage)
        self.assertEqual(result.context.thought_history_length, 4)


if __name__ == "__main__":
    unittest.main()
