import unittest
import tempfile
import json
import os
import threading
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

    # ------------------------------------------------------------------
    # T1: race in _save_session — disk must match memory under concurrency
    # ------------------------------------------------------------------
    def test_concurrent_add_clear_disk_matches_memory(self):
        """Concurrent add_thought + clear_history must never leave a stale
        snapshot on disk (regression for the _save_session race)."""
        session_file = Path(self.temp_dir.name) / "current_session.json"
        mismatches = 0

        for _ in range(200):
            with tempfile.TemporaryDirectory() as d:
                storage = ThoughtStorage(d)
                sfile = Path(d) / "current_session.json"

                thought = ThoughtData(
                    thought="Concurrent thought",
                    thought_number=1,
                    total_thoughts=1,
                    next_thought_needed=False,
                    stage=ThoughtStage.ANALYSIS,
                )

                t_add = threading.Thread(target=storage.add_thought, args=(thought,))
                t_clear = threading.Thread(target=storage.clear_history)

                t_add.start()
                t_clear.start()
                t_add.join()
                t_clear.join()

                with open(sfile, "r", encoding="utf-8") as f:
                    disk_len = len(json.load(f)["thoughts"])

                if disk_len != len(storage.thought_history):
                    mismatches += 1

        self.assertEqual(mismatches, 0, f"{mismatches}/200 disk/memory mismatches")
        # Silence unused-variable linters; session_file documents intent.
        del session_file

    # ------------------------------------------------------------------
    # T2: failed import must not rename foreign file or wipe session
    # ------------------------------------------------------------------
    def test_import_invalid_file_raises_and_preserves_state(self):
        """Importing a non-JSON file raises and leaves both the input file and
        the current session untouched."""
        thought = ThoughtData(
            thought="Existing thought",
            thought_number=1,
            total_thoughts=1,
            next_thought_needed=False,
            stage=ThoughtStage.PROBLEM_DEFINITION,
        )
        self.storage.add_thought(thought)
        self.assertEqual(len(self.storage.thought_history), 1)

        # A plain text file inside the storage dir (passes containment, fails parse).
        notes = Path(self.temp_dir.name) / "notes.txt"
        notes.write_text("just some notes, not json", encoding="utf-8")

        with self.assertRaises(ValueError):
            self.storage.import_session(str(notes))

        # Input file unchanged, not renamed.
        self.assertTrue(notes.exists())
        self.assertEqual(notes.read_text(encoding="utf-8"), "just some notes, not json")
        self.assertEqual(list(Path(self.temp_dir.name).glob("notes.bak.*")), [])

        # Current session unchanged in memory and on disk.
        self.assertEqual(len(self.storage.thought_history), 1)
        session_file = Path(self.temp_dir.name) / "current_session.json"
        with open(session_file, "r", encoding="utf-8") as f:
            self.assertEqual(len(json.load(f)["thoughts"]), 1)

    # ------------------------------------------------------------------
    # T3: server start recovers from semantically corrupt session file
    # ------------------------------------------------------------------
    def test_init_with_invalid_stage_recovers(self):
        """A session file with an invalid stage must not crash startup; it is
        backed up and recovery starts from an empty session."""
        with tempfile.TemporaryDirectory() as d:
            session_file = Path(d) / "current_session.json"
            session_file.write_text(
                json.dumps({"thoughts": [{"thought": "x", "stage": "Brainstorm"}]}),
                encoding="utf-8",
            )

            storage = ThoughtStorage(d)  # must not raise

            self.assertEqual(storage.thought_history, [])
            backups = list(Path(d).glob("current_session.bak.*"))
            self.assertEqual(len(backups), 1)

    # ------------------------------------------------------------------
    # T4: export/import confined to storage_dir (CWE-22)
    # ------------------------------------------------------------------
    def test_export_rejects_path_outside_storage(self):
        """Exporting outside storage_dir is rejected and creates nothing."""
        thought = ThoughtData(
            thought="Test thought",
            thought_number=1,
            total_thoughts=1,
            next_thought_needed=False,
            stage=ThoughtStage.CONCLUSION,
        )
        self.storage.add_thought(thought)

        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "sub" / "owned.json"
            lock = Path(outside) / "sub" / "owned.lock"

            # Absolute path outside storage_dir.
            with self.assertRaises(ValueError):
                self.storage.export_session(str(target))
            self.assertFalse(target.exists())
            self.assertFalse(lock.exists())
            self.assertFalse(target.parent.exists())

            # '..' traversal escaping storage_dir.
            traversal = os.path.join(self.temp_dir.name, "..", "escape.json")
            with self.assertRaises(ValueError):
                self.storage.export_session(traversal)
            self.assertFalse(Path(traversal).resolve().exists())

    def test_import_rejects_path_outside_storage(self):
        """Importing from outside storage_dir is rejected and creates nothing."""
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "payload.json"
            target.write_text(json.dumps({"thoughts": []}), encoding="utf-8")
            lock = Path(outside) / "payload.lock"

            with self.assertRaises(ValueError):
                self.storage.import_session(str(target))
            self.assertFalse(lock.exists())

            traversal = os.path.join(self.temp_dir.name, "..", "escape.json")
            with self.assertRaises(ValueError):
                self.storage.import_session(traversal)

    # ------------------------------------------------------------------
    # T7: atomic write leaves no temp file behind
    # ------------------------------------------------------------------
    def test_save_is_atomic_no_tmp_leftover(self):
        """After saving, no *.tmp file remains and the session file is valid JSON."""
        thought = ThoughtData(
            thought="Test thought",
            thought_number=1,
            total_thoughts=1,
            next_thought_needed=False,
            stage=ThoughtStage.ANALYSIS,
        )
        self.storage.add_thought(thought)

        leftovers = list(Path(self.temp_dir.name).glob("*.tmp"))
        self.assertEqual(leftovers, [])

        session_file = Path(self.temp_dir.name) / "current_session.json"
        with open(session_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(len(data["thoughts"]), 1)


if __name__ == "__main__":
    unittest.main()
