import time
from typing import Any, Dict, Optional


class LockHelper:
    """Manages all non-persistent, in-memory user locks for the cog using a dictionary for fast lookups."""

    def __init__(self):
        self._locks: Dict[int, Dict[str, Any]] = {}

    def get_user_lock(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Retrieves the lock object for a user if they are locked."""
        return self._locks.get(user_id)

    def add_lock(self, user_id: int, lock_type: str, message: str):
        """
        Applies a lock to a user, including a timestamp.
        Does nothing if the user is already locked.
        """
        if user_id not in self._locks:
            self._locks[user_id] = {
                "user_id": user_id,
                "type": lock_type,
                "message": message,
                "timestamp": time.time()
            }

    def remove_lock_for_user(self, user_id: int):
        """Removes a lock from a specific user."""
        self._locks.pop(user_id, None)

    def clear_all_locks(self):
        """Removes all active locks. To be used on cog unload."""
        self._locks.clear()