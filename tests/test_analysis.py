import unittest

from mcp_sequential_thinking.analysis import ThoughtAnalyzer
from mcp_sequential_thinking.models import ThoughtData, ThoughtStage


class TestThoughtAnalyzer(unittest.TestCase):
    """Test cases for the ThoughtAnalyzer class."""

    def setUp(self):
        """Set up test data."""
        self.thought1 = ThoughtData(
            thought="First thought about climate change",
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

    def test_find_related_thoughts_by_stage(self):
        """Test finding related thoughts by stage and tags."""
        related = ThoughtAnalyzer.find_related_thoughts(self.thought1, self.all_thoughts)

        # Should find thought4 (same stage) and thought2 (shared "climate" tag)
        self.assertEqual(len(related), 2)
        self.assertEqual(related[0], self.thought4)
        self.assertEqual(related[1], self.thought2)

    def test_find_related_thoughts_by_tags(self):
        """Test finding related thoughts by tags."""
        # Create a new thought with tags that match thought1 and thought2
        new_thought = ThoughtData(
            thought="New thought with climate tag",
            thought_number=5,
            total_thoughts=5,
            next_thought_needed=False,
            stage=ThoughtStage.SYNTHESIS,
            tags=["climate", "synthesis"],
        )

        all_thoughts = self.all_thoughts + [new_thought]

        related = ThoughtAnalyzer.find_related_thoughts(new_thought, all_thoughts)

        # Should find thought1 and thought2 which have the "climate" tag
        self.assertEqual(len(related), 2)
        self.assertTrue(self.thought1 in related)
        self.assertTrue(self.thought2 in related)

    def test_generate_summary_empty(self):
        """Test generating summary with no thoughts."""
        summary = ThoughtAnalyzer.generate_summary([])

        self.assertEqual(summary, {"summary": "No thoughts recorded yet"})

    def test_generate_summary(self):
        """Test generating summary with thoughts."""
        summary = ThoughtAnalyzer.generate_summary(self.all_thoughts)

        self.assertEqual(summary["summary"]["totalThoughts"], 4)
        self.assertEqual(summary["summary"]["stages"]["Problem Definition"], 2)
        self.assertEqual(summary["summary"]["stages"]["Research"], 1)
        self.assertEqual(summary["summary"]["stages"]["Analysis"], 1)
        self.assertEqual(len(summary["summary"]["timeline"]), 4)
        self.assertTrue("topTags" in summary["summary"])
        self.assertTrue("completionStatus" in summary["summary"])

    def test_progress_ignores_revisions_and_branches(self):
        """Revisions and branch thoughts don't advance progress metrics."""
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

        # Summary: 4 mainline thoughts of max_total 5 => 80%, not 120%.
        summary = ThoughtAnalyzer.generate_summary(all_thoughts)
        self.assertEqual(summary["summary"]["completionStatus"]["percentComplete"], 80.0)

        # analyze_thought for the revision uses the mainline position (4/5),
        # not its own number (5/5).
        analysis = ThoughtAnalyzer.analyze_thought(revision, all_thoughts)
        self.assertEqual(analysis["thoughtAnalysis"]["analysis"]["progress"], 80.0)

    def test_summary_counts_branches_and_revisions(self):
        """Summary reports a branches object and a revision count."""
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

        summary = ThoughtAnalyzer.generate_summary(all_thoughts)["summary"]

        self.assertEqual(summary["revisionCount"], 1)
        self.assertEqual(summary["branches"], {"alt": {"fromThought": 3, "thoughtCount": 2}})

        # Timeline entries flag revisions and branches.
        by_number = {e["number"]: e for e in summary["timeline"]}
        self.assertTrue(by_number[5]["isRevision"])
        self.assertEqual(by_number[6]["branchId"], "alt")
        self.assertNotIn("isRevision", by_number[1])
        self.assertNotIn("branchId", by_number[1])

    def test_analyze_revision_includes_revision_of(self):
        """Analyzing a revision surfaces a snippet of the revised thought."""
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

        analysis = ThoughtAnalyzer.analyze_thought(revision, all_thoughts)
        block = analysis["thoughtAnalysis"]["analysis"]

        self.assertTrue(block["isRevision"])
        self.assertEqual(block["revisedThought"], 1)
        self.assertIsNone(block["branchId"])
        self.assertEqual(block["revisionOf"]["thoughtNumber"], 1)
        self.assertIn("First thought about climate change", block["revisionOf"]["snippet"])

    def test_analyze_mainline_thought_reports_revision_fields(self):
        """Mainline thoughts report the revision fields with null/false values."""
        analysis = ThoughtAnalyzer.analyze_thought(self.thought1, self.all_thoughts)
        block = analysis["thoughtAnalysis"]["analysis"]

        self.assertFalse(block["isRevision"])
        self.assertIsNone(block["revisedThought"])
        self.assertIsNone(block["branchId"])
        self.assertNotIn("revisionOf", block)

    def test_analyze_thought(self):
        """Test analyzing a thought."""
        analysis = ThoughtAnalyzer.analyze_thought(self.thought1, self.all_thoughts)

        self.assertEqual(analysis["thoughtAnalysis"]["currentThought"]["thoughtNumber"], 1)
        self.assertEqual(
            analysis["thoughtAnalysis"]["currentThought"]["stage"], "Problem Definition"
        )
        self.assertEqual(analysis["thoughtAnalysis"]["analysis"]["relatedThoughtsCount"], 2)
        self.assertEqual(analysis["thoughtAnalysis"]["analysis"]["progress"], 20.0)  # 1/5 * 100
        self.assertTrue(analysis["thoughtAnalysis"]["analysis"]["isFirstInStage"])
        self.assertEqual(analysis["thoughtAnalysis"]["context"]["thoughtHistoryLength"], 4)


if __name__ == "__main__":
    unittest.main()
