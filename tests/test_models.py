import unittest
from datetime import datetime

from mcp_sequential_thinking.models import ThoughtStage, ThoughtData


class TestThoughtStage(unittest.TestCase):
    """Test cases for the ThoughtStage enum."""

    def test_from_string_valid(self):
        """Test converting valid strings to ThoughtStage enum values."""
        self.assertEqual(ThoughtStage.from_string("Problem Definition"), ThoughtStage.PROBLEM_DEFINITION)
        self.assertEqual(ThoughtStage.from_string("Research"), ThoughtStage.RESEARCH)
        self.assertEqual(ThoughtStage.from_string("Analysis"), ThoughtStage.ANALYSIS)
        self.assertEqual(ThoughtStage.from_string("Synthesis"), ThoughtStage.SYNTHESIS)
        self.assertEqual(ThoughtStage.from_string("Conclusion"), ThoughtStage.CONCLUSION)

    def test_from_string_invalid(self):
        """Test that invalid strings raise ValueError."""
        with self.assertRaises(ValueError):
            ThoughtStage.from_string("Invalid Stage")


class TestThoughtData(unittest.TestCase):
    """Test cases for the ThoughtData class."""

    def test_validate_valid(self):
        """Test that valid thought data is accepted at construction time."""
        thought = ThoughtData(
            thought="Test thought",
            thought_number=1,
            total_thoughts=3,
            next_thought_needed=True,
            stage=ThoughtStage.PROBLEM_DEFINITION
        )
        # Validation is handled by Pydantic during construction; a successfully
        # constructed instance is valid.
        self.assertEqual(thought.thought, "Test thought")
        self.assertEqual(thought.thought_number, 1)
        self.assertEqual(thought.total_thoughts, 3)

    def test_validate_invalid_thought_number(self):
        """Test validation fails with invalid thought number."""
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            ThoughtData(
                thought="Test thought",
                thought_number=0,  # Invalid: must be positive
                total_thoughts=3,
                next_thought_needed=True,
                stage=ThoughtStage.PROBLEM_DEFINITION
            )

    def test_validate_invalid_total_thoughts(self):
        """Test validation fails with invalid total thoughts."""
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            ThoughtData(
                thought="Test thought",
                thought_number=3,
                total_thoughts=2,  # Invalid: less than thought_number
                next_thought_needed=True,
                stage=ThoughtStage.PROBLEM_DEFINITION
            )

    def test_validate_empty_thought(self):
        """Test validation fails with empty thought."""
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            ThoughtData(
                thought="",  # Invalid: empty thought
                thought_number=1,
                total_thoughts=3,
                next_thought_needed=True,
                stage=ThoughtStage.PROBLEM_DEFINITION
            )

    def test_to_dict(self):
        """Test conversion to dictionary."""
        thought = ThoughtData(
            thought="Test thought",
            thought_number=1,
            total_thoughts=3,
            next_thought_needed=True,
            stage=ThoughtStage.PROBLEM_DEFINITION,
            tags=["tag1", "tag2"],
            axioms_used=["axiom1"],
            assumptions_challenged=["assumption1"]
        )

        # Save the timestamp for comparison
        timestamp = thought.timestamp

        expected_dict = {
            "thought": "Test thought",
            "thoughtNumber": 1,
            "totalThoughts": 3,
            "nextThoughtNeeded": True,
            "stage": "Problem Definition",
            "tags": ["tag1", "tag2"],
            "axiomsUsed": ["axiom1"],
            "assumptionsChallenged": ["assumption1"],
            "timestamp": timestamp
        }

        self.assertEqual(thought.to_dict(), expected_dict)

    def test_from_dict(self):
        """Test creation from dictionary."""
        data = {
            "thought": "Test thought",
            "thoughtNumber": 1,
            "totalThoughts": 3,
            "nextThoughtNeeded": True,
            "stage": "Problem Definition",
            "tags": ["tag1", "tag2"],
            "axiomsUsed": ["axiom1"],
            "assumptionsChallenged": ["assumption1"],
            "timestamp": "2023-01-01T12:00:00"
        }

        thought = ThoughtData.from_dict(data)

        self.assertEqual(thought.thought, "Test thought")
        self.assertEqual(thought.thought_number, 1)
        self.assertEqual(thought.total_thoughts, 3)
        self.assertTrue(thought.next_thought_needed)
        self.assertEqual(thought.stage, ThoughtStage.PROBLEM_DEFINITION)
        self.assertEqual(thought.tags, ["tag1", "tag2"])
        self.assertEqual(thought.axioms_used, ["axiom1"])
        self.assertEqual(thought.assumptions_challenged, ["assumption1"])
        self.assertEqual(thought.timestamp, "2023-01-01T12:00:00")


if __name__ == "__main__":
    unittest.main()
