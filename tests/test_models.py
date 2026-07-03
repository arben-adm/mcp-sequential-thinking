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

    def _base_kwargs(self, **overrides):
        kwargs = {
            "thought": "Test thought",
            "thought_number": 3,
            "total_thoughts": 5,
            "next_thought_needed": True,
            "stage": ThoughtStage.ANALYSIS,
        }
        kwargs.update(overrides)
        return kwargs

    def test_revision_valid(self):
        """A revision with a valid earlier thought number is accepted."""
        thought = ThoughtData(**self._base_kwargs(is_revision=True, revises_thought_number=1))
        self.assertTrue(thought.is_revision)
        self.assertEqual(thought.revises_thought_number, 1)

    def test_revision_without_number_rejected(self):
        """is_revision=True without revises_thought_number is rejected."""
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            ThoughtData(**self._base_kwargs(is_revision=True))

    def test_revises_number_without_flag_rejected(self):
        """revises_thought_number without is_revision=True is rejected."""
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            ThoughtData(**self._base_kwargs(revises_thought_number=1))

    def test_revises_number_must_be_earlier(self):
        """revises_thought_number must be >= 1 and < thought_number."""
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            ThoughtData(**self._base_kwargs(is_revision=True, revises_thought_number=3))
        with self.assertRaises(ValidationError):
            ThoughtData(**self._base_kwargs(is_revision=True, revises_thought_number=0))

    def test_branch_valid(self):
        """A branch with a valid fork point and id is accepted."""
        thought = ThoughtData(
            **self._base_kwargs(branch_from_thought=2, branch_id="alt-path_1")
        )
        self.assertEqual(thought.branch_from_thought, 2)
        self.assertEqual(thought.branch_id, "alt-path_1")

    def test_branch_from_must_be_earlier(self):
        """branch_from_thought must be >= 1 and < thought_number."""
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            ThoughtData(**self._base_kwargs(branch_from_thought=3, branch_id="alt"))
        with self.assertRaises(ValidationError):
            ThoughtData(**self._base_kwargs(branch_from_thought=0, branch_id="alt"))

    def test_branch_id_requires_branch_from(self):
        """branch_id without branch_from_thought is rejected."""
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            ThoughtData(**self._base_kwargs(branch_id="alt"))

    def test_branch_id_invalid_characters_rejected(self):
        """branch_id outside [A-Za-z0-9_-] or longer than 64 chars is rejected."""
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            ThoughtData(**self._base_kwargs(branch_from_thought=1, branch_id="bad id!"))
        with self.assertRaises(ValidationError):
            ThoughtData(**self._base_kwargs(branch_from_thought=1, branch_id="x" * 65))

    def test_revision_and_branch_mutually_exclusive(self):
        """A thought cannot be a revision and a branch start at the same time."""
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            ThoughtData(
                **self._base_kwargs(
                    is_revision=True,
                    revises_thought_number=1,
                    branch_from_thought=2,
                    branch_id="alt",
                )
            )

    def test_to_dict_omits_default_revision_fields(self):
        """Revision/branch fields are omitted from to_dict when at defaults."""
        thought = ThoughtData(**self._base_kwargs())
        d = thought.to_dict()
        for key in ("isRevision", "revisesThoughtNumber", "branchFromThought", "branchId"):
            self.assertNotIn(key, d)

    def test_revision_branch_dict_roundtrip(self):
        """to_dict/from_dict preserve revision and branch fields."""
        revision = ThoughtData(**self._base_kwargs(is_revision=True, revises_thought_number=2))
        d = revision.to_dict()
        self.assertTrue(d["isRevision"])
        self.assertEqual(d["revisesThoughtNumber"], 2)
        restored = ThoughtData.from_dict(d)
        self.assertTrue(restored.is_revision)
        self.assertEqual(restored.revises_thought_number, 2)

        branch = ThoughtData(**self._base_kwargs(branch_from_thought=1, branch_id="alt"))
        restored_branch = ThoughtData.from_dict(branch.to_dict())
        self.assertEqual(restored_branch.branch_from_thought, 1)
        self.assertEqual(restored_branch.branch_id, "alt")

    def test_from_dict_defaults_missing_revision_fields(self):
        """Records without revision/branch fields (pre-revision v2 files) load
        with defaults."""
        data = {
            "thought": "Old record",
            "thoughtNumber": 1,
            "totalThoughts": 1,
            "nextThoughtNeeded": False,
            "stage": "Conclusion",
        }
        thought = ThoughtData.from_dict(data)
        self.assertFalse(thought.is_revision)
        self.assertIsNone(thought.revises_thought_number)
        self.assertIsNone(thought.branch_from_thought)
        self.assertIsNone(thought.branch_id)

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
