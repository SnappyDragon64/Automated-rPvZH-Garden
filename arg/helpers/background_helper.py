from typing import Dict, List, Optional

from ..models import Background


class BackgroundHelper:
    """Manages garden background definitions and user unlocks."""

    def __init__(self, backgrounds_list: List[Background]):
        self.all_backgrounds: List[Background] = backgrounds_list
        self.backgrounds_by_id: Dict[str, Background] = {bg.id: bg for bg in backgrounds_list}

    def get_background_by_id(self, bg_id: str) -> Optional[Background]:
        return self.backgrounds_by_id.get(bg_id)

    def check_for_unlocks(self, user_fusions: List[str], user_unlocked_bgs: List[str]) -> List[Background]:
        """
        Checks all defined backgrounds against a user's discovered fusions
        and returns a list of newly unlocked Background objects.
        """

        newly_unlocked: List[Background] = []
        user_fusions_set = set(user_fusions)
        user_unlocked_bgs_set = set(user_unlocked_bgs)

        for bg_def in self.all_backgrounds:
            if bg_def.id in user_unlocked_bgs_set:
                continue

            required_set = set(bg_def.required_fusions)
            if required_set and required_set.issubset(user_fusions_set):
                newly_unlocked.append(bg_def)

        return newly_unlocked