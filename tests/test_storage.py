import unittest
import tempfile
import json
import os
import threading
from pathlib import Path

from mcp_sequential_thinking.models import ThoughtStage, ThoughtData
from mcp_sequential_thinking.storage import ThoughtStorage


def read_jsonl_records(session_file):
    """Parse a JSONL session file into (header, thought_records)."""
    lines = session_file.read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines if line.strip()]
    header = records[0]
    thoughts = [r for r in records[1:] if r.get("type") == "thought"]
    return header, thoughts


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
        session_file = Path(self.temp_dir.name) / "current_session.jsonl"
        self.assertTrue(session_file.exists())

        # Check the content of the session file
        header, thoughts = read_jsonl_records(session_file)
        self.assertEqual(header["type"], "header")
        self.assertEqual(header["version"], 2)
        self.assertEqual(len(thoughts), 1)
        self.assertEqual(thoughts[0]["thought"], "Test thought")
    
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

        # Check that the session file was rewritten (header only, no thoughts)
        session_file = Path(self.temp_dir.name) / "current_session.jsonl"
        header, thoughts = read_jsonl_records(session_file)
        self.assertEqual(header["type"], "header")
        self.assertEqual(len(thoughts), 0)
    
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

        # Relative paths resolve inside the exports/ subdirectory.
        self.storage.export_session("nested/export.json")

        export_file = Path(self.temp_dir.name) / "exports" / "nested" / "export.json"
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
        
        # Export the session (relative path lands in the exports/ subdirectory)
        export_file = "export.json"
        self.storage.export_session(export_file)
        self.assertTrue((Path(self.temp_dir.name) / "exports" / "export.json").exists())
        
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
        session_file = Path(self.temp_dir.name) / "current_session.jsonl"
        mismatches = 0

        for _ in range(200):
            with tempfile.TemporaryDirectory() as d:
                storage = ThoughtStorage(d)
                sfile = Path(d) / "current_session.jsonl"

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

                if sfile.exists():
                    _, disk_thoughts = read_jsonl_records(sfile)
                    disk_len = len(disk_thoughts)
                else:
                    disk_len = 0

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

        # A plain text file inside the export dir (passes containment, fails parse).
        export_dir = Path(self.temp_dir.name) / "exports"
        export_dir.mkdir()
        notes = export_dir / "notes.txt"
        notes.write_text("just some notes, not json", encoding="utf-8")

        with self.assertRaises(ValueError):
            self.storage.import_session(str(notes))

        # Input file unchanged, not renamed.
        self.assertTrue(notes.exists())
        self.assertEqual(notes.read_text(encoding="utf-8"), "just some notes, not json")
        self.assertEqual(list(export_dir.glob("notes.bak.*")), [])

        # Current session unchanged in memory and on disk.
        self.assertEqual(len(self.storage.thought_history), 1)
        session_file = Path(self.temp_dir.name) / "current_session.jsonl"
        _, disk_thoughts = read_jsonl_records(session_file)
        self.assertEqual(len(disk_thoughts), 1)

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

    def test_export_cannot_overwrite_session_file(self):
        """An export path traversing out of exports/ onto the session file is
        rejected and the session file is left untouched."""
        thought = ThoughtData(
            thought="Test thought",
            thought_number=1,
            total_thoughts=1,
            next_thought_needed=False,
            stage=ThoughtStage.CONCLUSION,
        )
        self.storage.add_thought(thought)

        session_file = Path(self.temp_dir.name) / "current_session.jsonl"
        before = session_file.read_text(encoding="utf-8")

        with self.assertRaises(ValueError):
            self.storage.export_session("../current_session.jsonl")

        self.assertEqual(session_file.read_text(encoding="utf-8"), before)

    def test_import_rejects_file_without_thoughts_key(self):
        """Importing valid JSON without a 'thoughts' key raises and leaves the
        current session and the source file untouched."""
        thought = ThoughtData(
            thought="Existing thought",
            thought_number=1,
            total_thoughts=1,
            next_thought_needed=False,
            stage=ThoughtStage.PROBLEM_DEFINITION,
        )
        self.storage.add_thought(thought)

        export_dir = Path(self.temp_dir.name) / "exports"
        export_dir.mkdir()
        wrong_file = export_dir / "wrong.json"
        wrong_file.write_text(json.dumps({"foo": 1}), encoding="utf-8")

        with self.assertRaises((KeyError, ValueError)):
            self.storage.import_session(str(wrong_file))

        # Session unchanged, source file unchanged.
        self.assertEqual(len(self.storage.thought_history), 1)
        self.assertEqual(wrong_file.read_text(encoding="utf-8"), json.dumps({"foo": 1}))

    def test_import_missing_file_raises_and_preserves_state(self):
        """Importing a nonexistent file raises instead of silently wiping the
        current session."""
        thought = ThoughtData(
            thought="Existing thought",
            thought_number=1,
            total_thoughts=1,
            next_thought_needed=False,
            stage=ThoughtStage.PROBLEM_DEFINITION,
        )
        self.storage.add_thought(thought)

        with self.assertRaises(FileNotFoundError):
            self.storage.import_session("does-not-exist.json")

        self.assertEqual(len(self.storage.thought_history), 1)

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

        session_file = Path(self.temp_dir.name) / "current_session.jsonl"
        _, disk_thoughts = read_jsonl_records(session_file)
        self.assertEqual(len(disk_thoughts), 1)

    # ------------------------------------------------------------------
    # Schema v2: append-only JSONL session format
    # ------------------------------------------------------------------
    def _make_thought(self, number, total=3, stage=ThoughtStage.ANALYSIS, needed=True):
        return ThoughtData(
            thought=f"Thought {number}",
            thought_number=number,
            total_thoughts=total,
            next_thought_needed=needed,
            stage=stage,
        )

    def test_add_thought_appends_single_line(self):
        """Each add_thought appends exactly one line; the header is written once."""
        for n in range(1, 4):
            self.storage.add_thought(self._make_thought(n))

        session_file = Path(self.temp_dir.name) / "current_session.jsonl"
        lines = session_file.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 4)  # header + 3 thoughts
        self.assertEqual(json.loads(lines[0])["type"], "header")

    def test_jsonl_roundtrip(self):
        """A fresh storage instance on the same directory loads identical thoughts."""
        thought = ThoughtData(
            thought="Roundtrip thought with umlauts äöü",
            thought_number=1,
            total_thoughts=2,
            next_thought_needed=True,
            stage=ThoughtStage.RESEARCH,
            tags=["round", "trip"],
            axioms_used=["axiom1"],
            assumptions_challenged=["assumption1"],
        )
        self.storage.add_thought(thought)

        reloaded = ThoughtStorage(self.temp_dir.name).get_all_thoughts()

        self.assertEqual(len(reloaded), 1)
        self.assertEqual(reloaded[0].id, thought.id)
        self.assertEqual(reloaded[0].thought, thought.thought)
        self.assertEqual(reloaded[0].thought_number, thought.thought_number)
        self.assertEqual(reloaded[0].total_thoughts, thought.total_thoughts)
        self.assertEqual(reloaded[0].next_thought_needed, thought.next_thought_needed)
        self.assertEqual(reloaded[0].stage, thought.stage)
        self.assertEqual(reloaded[0].tags, thought.tags)
        self.assertEqual(reloaded[0].axioms_used, thought.axioms_used)
        self.assertEqual(reloaded[0].assumptions_challenged, thought.assumptions_challenged)
        self.assertEqual(reloaded[0].timestamp, thought.timestamp)

    def test_migration_from_v1_json(self):
        """A legacy v1 current_session.json is migrated losslessly to JSONL."""
        with tempfile.TemporaryDirectory() as d:
            v1_file = Path(d) / "current_session.json"
            v1_file.write_text(
                json.dumps(
                    {
                        "thoughts": [
                            {
                                "thought": "Legacy thought",
                                "thoughtNumber": 1,
                                "totalThoughts": 1,
                                "nextThoughtNeeded": False,
                                "stage": "Conclusion",
                                "timestamp": "2023-01-01T12:00:00",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            storage = ThoughtStorage(d)

            self.assertEqual(len(storage.thought_history), 1)
            self.assertEqual(storage.thought_history[0].thought, "Legacy thought")
            self.assertTrue((Path(d) / "current_session.jsonl").exists())
            self.assertFalse(v1_file.exists())
            self.assertTrue((Path(d) / "current_session.json.migrated-to-v2").exists())

            # Idempotent: a second start only finds the JSONL file.
            storage2 = ThoughtStorage(d)
            self.assertEqual(len(storage2.thought_history), 1)

    def test_truncated_last_line_recovers(self):
        """A truncated final line (interrupted append) is dropped; the valid
        prefix of the session survives."""
        for n in range(1, 3):
            self.storage.add_thought(self._make_thought(n))

        session_file = Path(self.temp_dir.name) / "current_session.jsonl"
        with open(session_file, "a", encoding="utf-8") as f:
            f.write('{"type": "thought", "thought": "half writ')  # no newline, cut off

        storage = ThoughtStorage(self.temp_dir.name)  # must not crash

        self.assertEqual(len(storage.thought_history), 2)
        # No backup created; the file was recoverable.
        self.assertEqual(list(Path(self.temp_dir.name).glob("current_session.bak.*")), [])

    def test_corrupt_middle_line_backs_up(self):
        """A corrupt line in the middle invalidates the file: backup + empty session."""
        for n in range(1, 3):
            self.storage.add_thought(self._make_thought(n))

        session_file = Path(self.temp_dir.name) / "current_session.jsonl"
        lines = session_file.read_text(encoding="utf-8").splitlines()
        lines[1] = "{not json"
        session_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        storage = ThoughtStorage(self.temp_dir.name)  # must not crash

        self.assertEqual(storage.thought_history, [])
        self.assertEqual(len(list(Path(self.temp_dir.name).glob("current_session.bak.*"))), 1)

    def test_jsonl_roundtrip_with_revision_and_branch_fields(self):
        """Revision/branch fields survive the JSONL roundtrip."""
        mainline = self._make_thought(1)
        revision = ThoughtData(
            thought="Revised first thought",
            thought_number=2,
            total_thoughts=3,
            next_thought_needed=True,
            stage=ThoughtStage.ANALYSIS,
            is_revision=True,
            revises_thought_number=1,
        )
        branch = ThoughtData(
            thought="Alternative path",
            thought_number=3,
            total_thoughts=3,
            next_thought_needed=False,
            stage=ThoughtStage.SYNTHESIS,
            branch_from_thought=1,
            branch_id="alt-1",
        )
        for t in (mainline, revision, branch):
            self.storage.add_thought(t)

        reloaded = ThoughtStorage(self.temp_dir.name).get_all_thoughts()

        self.assertEqual(len(reloaded), 3)
        self.assertTrue(reloaded[1].is_revision)
        self.assertEqual(reloaded[1].revises_thought_number, 1)
        self.assertEqual(reloaded[2].branch_from_thought, 1)
        self.assertEqual(reloaded[2].branch_id, "alt-1")
        self.assertFalse(reloaded[0].is_revision)
        self.assertIsNone(reloaded[0].branch_id)

    def test_import_v1_export_still_works(self):
        """A v0.5.0 JSON export (no 'version' field) is still importable."""
        export_dir = Path(self.temp_dir.name) / "exports"
        export_dir.mkdir()
        legacy_export = export_dir / "legacy_export.json"
        legacy_export.write_text(
            json.dumps(
                {
                    "thoughts": [
                        {
                            "thought": "Exported thought",
                            "thoughtNumber": 1,
                            "totalThoughts": 1,
                            "nextThoughtNeeded": False,
                            "stage": "Synthesis",
                        }
                    ],
                    "lastUpdated": "2025-01-01T00:00:00",
                }
            ),
            encoding="utf-8",
        )

        self.storage.import_session(str(legacy_export))

        self.assertEqual(len(self.storage.thought_history), 1)
        self.assertEqual(self.storage.thought_history[0].thought, "Exported thought")

    def test_import_rejects_unknown_newer_version(self):
        """An export claiming a newer schema version is rejected."""
        export_dir = Path(self.temp_dir.name) / "exports"
        export_dir.mkdir()
        future_export = export_dir / "future.json"
        future_export.write_text(
            json.dumps({"version": 99, "thoughts": []}), encoding="utf-8"
        )

        with self.assertRaises(ValueError):
            self.storage.import_session(str(future_export))

    def test_export_includes_schema_version(self):
        """Exports carry the top-level schema version field."""
        self.storage.add_thought(self._make_thought(1, total=1, needed=False))
        self.storage.export_session("versioned.json")

        export_file = Path(self.temp_dir.name) / "exports" / "versioned.json"
        with open(export_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["version"], 2)
        self.assertEqual(len(data["thoughts"]), 1)


if __name__ == "__main__":
    unittest.main()
