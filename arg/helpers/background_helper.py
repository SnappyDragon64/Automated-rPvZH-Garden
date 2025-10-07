from typing import Any, Dict, List, Optional


class BackgroundHelper:
    """Manages garden background definitions and user unlocks."""

    def __init__(self, backgrounds_list: List[Dict[str, Any]]):
        self.all_backgrounds = backgrounds_list
        self.backgrounds_by_id = {bg['id']: bg for bg in backgrounds_list}

    def get_background_by_id(self, bg_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a background's definition by its unique ID."""

        return self.backgrounds_by_id.get(bg_id)

    def check_for_unlocks(self, user_fusions: List[str], user_unlocked_bgs: List[str]) -> List[Dict[str, Any]]:
        """Checks all defined backgrounds against a user's discovered fusions."""

        newly_unlocked = []
        user_fusions_set = set(user_fusions)
        user_unlocked_bgs_set = set(user_unlocked_bgs)

        for bg_def in self.all_backgrounds:
            if bg_def['id'] in user_unlocked_bgs_set:
                continue

            required_set = set(bg_def.get("required_fusions", []))
            if required_set and required_set.issubset(user_fusions_set):
                newly_unlocked.append(bg_def)

        return newly_unlocked