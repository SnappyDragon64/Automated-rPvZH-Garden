import time
from typing import Any, Dict, List, Optional


class LockHelper:
    """Manages all non-persistent, in-memory user locks for the cog."""

    def __init__(self):
        self._locks: List[Dict[str, Any]] = []

    def get_user_lock(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Retrieves the lock object for a user if they are locked."""

        for lock in self._locks:
            if lock.get("user_id") == user_id:
                return lock

        return None

    def add_lock(self, user_id: int, lock_type: str, message: str):
        """Applies a lock to a user. Does nothing if the user is already locked."""

        if not self.get_user_lock(user_id):
            self._locks.append({
                "user_id": user_id,
                "type": lock_type,
                "message": message,
                "timestamp": time.time()
            })

    def remove_lock_for_user(self, user_id: int):
        """Removes a lock from a specific user."""

        self._locks = [lock for lock in self._locks if lock.get("user_id") != user_id]

    def clear_all_locks(self):
        """Removes all active locks. To be used on cog unload."""

        self._locks = []