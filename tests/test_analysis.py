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
