import json
import logging
from typing import List, Dict, Any
from pathlib import Path
from datetime import datetime
import portalocker

from .models import ThoughtData
from .logging_conf import configure_logging

logger = configure_logging("sequential-thinking.storage-utils")


def prepare_thoughts_for_serialization(thoughts: List[ThoughtData]) -> List[Dict[str, Any]]:
    """Prepare thoughts for serialization with IDs included.

    Args:
        thoughts: List of thought data objects to prepare

    Returns:
        List[Dict[str, Any]]: List of thought dictionaries with IDs
    """
    return [thought.to_dict(include_id=True) for thought in thoughts]


def save_thoughts_to_file(
    file_path: Path,
    thoughts: List[Dict[str, Any]],
    lock_file: Path,
    metadata: Dict[str, Any] | None = None,
) -> None:
    """Save thoughts to a file with proper locking.

    Args:
        file_path: Path to the file to save
        thoughts: List of thought dictionaries to save
        lock_file: Path to the lock file
        metadata: Optional additional metadata to include
    """
    data = {
        "thoughts": thoughts,
        "lastUpdated": datetime.now().isoformat()
    }
    
    # Add any additional metadata if provided
    if metadata:
        data.update(metadata)
    
    # Ensure destination directories exist before acquiring the lock.
    file_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file.parent.mkdir(parents=True, exist_ok=True)

    # Use file locking to ensure thread safety when writing
    with portalocker.Lock(lock_file, timeout=10) as _:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            
    logger.debug(f"Saved {len(thoughts)} thoughts to {file_path}")


def load_thoughts_from_file(file_path: Path, lock_file: Path) -> List[ThoughtData]:
    """Load thoughts from a file with proper locking.

    Args:
        file_path: Path to the file to load
        lock_file: Path to the lock file

    Returns:
        List[ThoughtData]: Loaded thought data objects
        
    Raises:
        json.JSONDecodeError: If the file is not valid JSON
        KeyError: If the file doesn't contain valid thought data
    """
    if not file_path.exists():
        return []
        
    try:
        # Use file locking and file handling in a single with statement
        # for cleaner resource management
        with portalocker.Lock(lock_file, timeout=10) as _, open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Convert data to ThoughtData objects after file is closed
        thoughts = [
            ThoughtData.from_dict(thought_dict)
            for thought_dict in data.get("thoughts", [])
        ]
            
        logger.debug(f"Loaded {len(thoughts)} thoughts from {file_path}")
        return thoughts
        
    except (json.JSONDecodeError, KeyError) as e:
        # Handle corrupted file
        logger.error(f"Error loading from {file_path}: {e}")
        # Create backup of corrupted file
        backup_file = file_path.with_suffix(f".bak.{datetime.now().strftime('%Y%m%d%H%M%S')}")
        file_path.rename(backup_file)
        logger.info(f"Created backup of corrupted file at {backup_file}")
        return []