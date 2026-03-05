import unittest
import tempfile
import json
import os
from pathlib import Path

from mcp_sequential_thinking.models import ThoughtStage, ThoughtData
from mcp_sequential_thinking.storage import ThoughtStorage


class TestThoughtStorage(unittest.TestCase):
    """Test cases for the ThoughtStorage class."""
    
    def setUp(self):
        """Set up a temporary directory for storage tests."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage = ThoughtStorage(self.temp_dir.name)
    
    def tearDown(self):
        """Clean up temporary directory."""
        self.temp_dir.cleanup()
    
    def test_add_thought(self):
        """Test adding a thought to storage."""
        thought = ThoughtData(
            thought="Test thought",
            thought_number=1,
            total_thoughts=3,
            next_thought_needed=True,
            stage=ThoughtStage.PROBLEM_DEFINITION
        )
        
        self.storage.add_thought(thought)
        
        # Check that the thought was added to memory
        self.assertEqual(len(self.storage.thought_history), 1)
        self.assertEqual(self.storage.thought_history[0], thought)
        
        # Check that the session file was created
        session_file = Path(self.temp_dir.name) / "current_session.json"
        self.assertTrue(session_file.exists())
        
        # Check the content of the session file
        with open(session_file, 'r') as f:
            data = json.load(f)
            self.assertEqual(len(data["thoughts"]), 1)
            self.assertEqual(data["thoughts"][0]["thought"], "Test thought")
    
    def test_get_all_thoughts(self):
        """Test getting all thoughts from storage."""
        thought1 = ThoughtData(
            thought="Test thought 1",
            thought_number=1,
            total_thoughts=3,
            next_thought_needed=True,
            stage=ThoughtStage.PROBLEM_DEFINITION
        )
        
        thought2 = ThoughtData(
            thought="Test thought 2",
            thought_number=2,
            total_thoughts=3,
            next_thought_needed=True,
            stage=ThoughtStage.RESEARCH
        )
        
        self.storage.add_thought(thought1)
        self.storage.add_thought(thought2)
        
        thoughts = self.storage.get_all_thoughts()
        
        self.assertEqual(len(thoughts), 2)
        self.assertEqual(thoughts[0], thought1)
        self.assertEqual(thoughts[1], thought2)
    
    def test_get_thoughts_by_stage(self):
        """Test getting thoughts by stage."""
        thought1 = ThoughtData(
            thought="Test thought 1",
            thought_number=1,
            total_thoughts=3,
            next_thought_needed=True,
            stage=ThoughtStage.PROBLEM_DEFINITION
        )
        
        thought2 = ThoughtData(
            thought="Test thought 2",
            thought_number=2,
            total_thoughts=3,
            next_thought_needed=True,
            stage=ThoughtStage.RESEARCH
        )
        
        thought3 = ThoughtData(
            thought="Test thought 3",
            thought_number=3,
            total_thoughts=3,
            next_thought_needed=False,
            stage=ThoughtStage.PROBLEM_DEFINITION
        )
        
        self.storage.add_thought(thought1)
        self.storage.add_thought(thought2)
        self.storage.add_thought(thought3)
        
        problem_def_thoughts = self.storage.get_thoughts_by_stage(ThoughtStage.PROBLEM_DEFINITION)
        research_thoughts = self.storage.get_thoughts_by_stage(ThoughtStage.RESEARCH)
        
        self.assertEqual(len(problem_def_thoughts), 2)
        self.assertEqual(problem_def_thoughts[0], thought1)
        self.assertEqual(problem_def_thoughts[1], thought3)
        
        self.assertEqual(len(research_thoughts), 1)
        self.assertEqual(research_thoughts[0], thought2)
    
    def test_clear_history(self):
        """Test clearing thought history."""
        thought = ThoughtData(
            thought="Test thought",
            thought_number=1,
            total_thoughts=3,
            next_thought_needed=True,
            stage=ThoughtStage.PROBLEM_DEFINITION
        )
        
        self.storage.add_thought(thought)
        self.assertEqual(len(self.storage.thought_history), 1)
        
        self.storage.clear_history()
        self.assertEqual(len(self.storage.thought_history), 0)
        
        # Check that the session file was updated
        session_file = Path(self.temp_dir.name) / "current_session.json"
        with open(session_file, 'r') as f:
            data = json.load(f)
            self.assertEqual(len(data["thoughts"]), 0)
    
    def test_export_creates_parent_directory(self):
        """Test exporting a session to a nested directory creates parents."""
        thought = ThoughtData(
            thought="Test thought",
            thought_number=1,
            total_thoughts=1,
            next_thought_needed=False,
            stage=ThoughtStage.CONCLUSION,
        )
        self.storage.add_thought(thought)

        nested_dir = Path(self.temp_dir.name) / "exports" / "nested"
        export_file = nested_dir / "export.json"

        self.storage.export_session(str(export_file))

        self.assertTrue(export_file.exists())

    def test_export_import_session(self):
        """Test exporting and importing a session."""
        thought1 = ThoughtData(
            thought="Test thought 1",
            thought_number=1,
            total_thoughts=2,
            next_thought_needed=True,
            stage=ThoughtStage.PROBLEM_DEFINITION
        )
        
        thought2 = ThoughtData(
            thought="Test thought 2",
            thought_number=2,
            total_thoughts=2,
            next_thought_needed=False,
            stage=ThoughtStage.CONCLUSION
        )
        
        self.storage.add_thought(thought1)
        self.storage.add_thought(thought2)
        
        # Export the session
        export_file = os.path.join(self.temp_dir.name, "export.json")
        self.storage.export_session(export_file)
        
        # Clear the history
        self.storage.clear_history()
        self.assertEqual(len(self.storage.thought_history), 0)
        
        # Import the session
        self.storage.import_session(export_file)
        
        # Check that the thoughts were imported correctly
        self.assertEqual(len(self.storage.thought_history), 2)
        self.assertEqual(self.storage.thought_history[0].thought, "Test thought 1")
        self.assertEqual(self.storage.thought_history[1].thought, "Test thought 2")


if __name__ == "__main__":
    unittest.main()
