import dataclasses
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple
from types import MappingProxyType

from .game_state_helper import GameStateHelper

from ..models import (
    UserProfile,
    UserProfileView,
    PlantedPlant,
    PlantedSeedling,
    SlotItem,
)


class GardenHelper:
    """
    Manages user data. Enforces encapsulation by using an internal mutable UserProfile
    and exposing an immutable UserProfileView.
    """

    def __init__(self, game_state_helper: GameStateHelper):
        self.game_state_helper = game_state_helper  # Use a short alias for convenience
        self._user_cache: Dict[int, UserProfile] = {}

    @staticmethod
    def _dict_to_slot_item(item_dict: Optional[Dict[str, Any]]) -> SlotItem:
        if not isinstance(item_dict, dict):
            return None

        item_type = item_dict.get("type")

        if item_type == "seedling":
            return PlantedSeedling(**item_dict)
        elif item_type:
            return PlantedPlant(**item_dict)

        return None

    def _deserialize_user(self, user_id: int, user_dict: Dict[str, Any]) -> UserProfile:
        defaults = {
            "balance": 0, "garden": [None] * 12, "inventory": {}, "last_daily": None,
            "discovered_fusions": [], "storage_shed_slots": [None] * 8, "mastery": 0,
            "time_mastery": 0, "unlocked_backgrounds": ["default"], "active_background": "default"
        }

        for key, value in defaults.items():
            user_dict.setdefault(key, value)

        return UserProfile(
            user_id=user_id,
            balance=user_dict["balance"],
            sun_mastery=user_dict["mastery"],
            time_mastery=user_dict["time_mastery"],
            last_daily=user_dict["last_daily"],
            active_background=user_dict["active_background"],
            garden=[self._dict_to_slot_item(p) for p in user_dict["garden"]],
            storage_shed=[self._dict_to_slot_item(p) for p in user_dict["storage_shed_slots"]],
            inventory=user_dict["inventory"],
            discovered_fusions=user_dict["discovered_fusions"],
            unlocked_backgrounds=user_dict["unlocked_backgrounds"],
        )

    def _save_user_profile(self, user_profile: UserProfile):
        """Converts a UserProfile object back to a dict and saves it to the IN-MEMORY state."""
        serializable_data = dataclasses.asdict(user_profile)

        serializable_data['mastery'] = serializable_data.pop('sun_mastery')
        serializable_data.pop('user_id')

        self.game_state_helper.set_user_data(user_profile.user_id, serializable_data)

    def _get_or_create_user_profile(self, user_id: int) -> UserProfile:
        if user_id in self._user_cache:
            return self._user_cache[user_id]

        raw_data = self.game_state_helper.get_user_data(user_id)

        user_profile = self._deserialize_user(user_id, raw_data)
        self._user_cache[user_id] = user_profile

        return user_profile

    def get_user_profile_view(self, user_id: int) -> UserProfileView:
        user_profile = self._get_or_create_user_profile(user_id)
        return UserProfileView(
            user_id=user_profile.user_id,
            balance=user_profile.balance,
            sun_mastery=user_profile.sun_mastery,
            time_mastery=user_profile.time_mastery,
            last_daily=user_profile.last_daily,
            active_background=user_profile.active_background,
            garden=tuple(user_profile.garden),
            storage_shed=tuple(user_profile.storage_shed),
            inventory=MappingProxyType(user_profile.inventory),
            discovered_fusions=tuple(user_profile.discovered_fusions),
            unlocked_backgrounds=tuple(user_profile.unlocked_backgrounds),
        )

    def get_all_user_ids(self) -> List[int]:
        all_users = self.game_state_helper.get_all_user_data()
        return [int(uid) for uid in all_users.keys()]

    def is_slot_unlocked(self, profile: UserProfileView, slot_1_indexed: int) -> bool:
        if 1 <= slot_1_indexed <= 6:
            return True

        return f"plot_{slot_1_indexed}" in profile.inventory

    def update_seedling_progress(self, user_id: int, plot_index_0based: int, progress_increase: float):
        profile = self._get_or_create_user_profile(user_id)

        if 0 <= plot_index_0based < len(profile.garden):
            slot_data = profile.garden[plot_index_0based]

            if isinstance(slot_data, PlantedSeedling):
                slot_data.progress = min(slot_data.progress + progress_increase, 100.0)

        self._save_user_profile(profile)

    def plant_seedling(self, user_id: int, plot_index_0based: int, seedling_id: str, channel_id: int):
        profile = self._get_or_create_user_profile(user_id)
        new_seedling = PlantedSeedling(id=seedling_id, notification_channel_id=channel_id)

        if 0 <= plot_index_0based < len(profile.garden):
            profile.garden[plot_index_0based] = new_seedling

        self._save_user_profile(profile)

    def set_garden_plot(self, user_id: int, plot_index_0based: int, plant_obj: Optional[SlotItem]):
        profile = self._get_or_create_user_profile(user_id)

        if 0 <= plot_index_0based < len(profile.garden):
            profile.garden[plot_index_0based] = plant_obj

        self._save_user_profile(profile)

    def set_full_garden(self, user_id: int, new_garden_list: List[SlotItem]):
        profile = self._get_or_create_user_profile(user_id)
        profile.garden = new_garden_list
        self._save_user_profile(profile)

    def get_text_garden_display(self, profile: UserProfileView) -> Tuple[str, str]:
        garden_display_lines = []

        for i, plant in enumerate(profile.garden):
            slot_prefix = f"**{i + 1}:**"

            if not self.is_slot_unlocked(profile, i + 1):
                garden_display_lines.append(f"{slot_prefix} 🔒 Locked")
            elif plant is None:
                garden_display_lines.append(f"{slot_prefix} 🟫 Unoccupied")
            elif isinstance(plant, PlantedSeedling):
                garden_display_lines.append(f"{slot_prefix} 🌱 Seedling ({plant.progress:.1f}%)")
            elif isinstance(plant, PlantedPlant):
                garden_display_lines.append(f"{slot_prefix} 🌿 {plant.name}")
            else:
                garden_display_lines.append(f"{slot_prefix} ❓ Unknown State")

        return "\n".join(garden_display_lines[:6]), "\n".join(garden_display_lines[6:])

    def user_has_storage_shed(self, profile: UserProfileView) -> bool:
        return "storage_shed" in profile.inventory

    def get_storage_capacity(self, profile: UserProfileView) -> int:
        if not self.user_has_storage_shed(profile):
            return 0

        capacity = 4
        if "shed_upgrade" in profile.inventory:
            capacity += 4
        return capacity

    def get_formatted_storage_contents(self, profile: UserProfileView) -> Tuple[List[str], int, int]:
        capacity = self.get_storage_capacity(profile)
        shed_slots = profile.storage_shed
        occupied = sum(1 for slot in shed_slots[:capacity] if slot is not None)
        display_lines = []

        for i in range(capacity):
            slot_content = shed_slots[i] if i < len(shed_slots) else None

            if isinstance(slot_content, PlantedPlant):
                display_lines.append(f"**{i + 1}.** {slot_content.name}")
            else:
                display_lines.append(f"**{i + 1}.** <Empty>")

        return display_lines, occupied, capacity

    def store_plant(self, user_id: int, plot_index_0based: int) -> Tuple[bool, str]:
        profile = self._get_or_create_user_profile(user_id)
        profile_view = self.get_user_profile_view(user_id)
        capacity = self.get_storage_capacity(profile_view)

        if sum(1 for s in profile.storage_shed[:capacity] if s is not None) >= capacity:
            return False, "Insufficient storage shed capacity."

        plant_to_move = profile.garden[plot_index_0based]
        first_empty_slot = next((i for i, s in enumerate(profile.storage_shed) if s is None), -1)

        if first_empty_slot == -1 or first_empty_slot >= capacity:
            return False, "Internal Error: Could not find an empty storage slot."

        profile.storage_shed[first_empty_slot] = plant_to_move
        profile.garden[plot_index_0based] = None
        self._save_user_profile(profile)
        return True, f"**{plant_to_move.name}** (plot {plot_index_0based + 1}) -> storage slot {first_empty_slot + 1}"

    def unstore_plant(self, user_id: int, storage_index_0based: int) -> Tuple[bool, str]:
        profile = self._get_or_create_user_profile(user_id)
        profile_view = self.get_user_profile_view(user_id)

        open_plots = [i for i, s in enumerate(profile_view.garden) if
                      self.is_slot_unlocked(profile_view, i + 1) and s is None]

        if not open_plots:
            return False, "Insufficient garden capacity."

        plant_to_move = profile.storage_shed[storage_index_0based]
        target_plot_idx = open_plots[0]
        profile.garden[target_plot_idx] = plant_to_move
        profile.storage_shed[storage_index_0based] = None
        self._save_user_profile(profile)
        return True, f"**{plant_to_move.name}** (storage {storage_index_0based + 1}) -> garden plot {target_plot_idx + 1}"

    def set_balance(self, user_id: int, amount: int):
        profile = self._get_or_create_user_profile(user_id)
        profile.balance = max(0, amount)
        self._save_user_profile(profile)

    def set_sun_mastery(self, user_id: int, level: int):
        profile = self._get_or_create_user_profile(user_id)
        profile.sun_mastery = max(0, level)
        self._save_user_profile(profile)

    def set_time_mastery(self, user_id: int, level: int):
        profile = self._get_or_create_user_profile(user_id)
        profile.time_mastery = max(0, level)
        self._save_user_profile(profile)

    def add_balance(self, user_id: int, amount: int):
        if amount > 0:
            profile = self._get_or_create_user_profile(user_id)
            profile.balance += amount
            self._save_user_profile(profile)

    def remove_balance(self, user_id: int, amount: int):
        if amount > 0:
            profile = self._get_or_create_user_profile(user_id)
            profile.balance = max(0, profile.balance - amount)
            self._save_user_profile(profile)

    def add_item_to_inventory(self, user_id: int, item_id: str, quantity: int = 1):
        profile = self._get_or_create_user_profile(user_id)
        profile.inventory[item_id] = profile.inventory.get(item_id, 0) + quantity
        self._save_user_profile(profile)

    def remove_item_from_inventory(self, user_id: int, item_id: str, quantity: int = 1) -> bool:
        profile = self._get_or_create_user_profile(user_id)
        current_amount = profile.inventory.get(item_id, 0)

        if current_amount < quantity:
            return False

        new_amount = current_amount - quantity
        if new_amount <= 0:
            del profile.inventory[item_id]
        else:
            profile.inventory[item_id] = new_amount

        self._save_user_profile(profile)
        return True

    def set_last_daily(self, user_id: int, date_str: str):
        profile = self._get_or_create_user_profile(user_id)
        profile.last_daily = date_str
        self._save_user_profile(profile)

    def increment_mastery(self, user_id: int, amount: int = 1):
        profile = self._get_or_create_user_profile(user_id)
        profile.sun_mastery += amount
        self._save_user_profile(profile)

    def increment_time_mastery(self, user_id: int, amount: int = 1):
        profile = self._get_or_create_user_profile(user_id)
        profile.time_mastery += amount
        self._save_user_profile(profile)

    def add_fusion_discovery(self, user_id: int, fusion_id: str):
        profile = self._get_or_create_user_profile(user_id)

        if fusion_id not in profile.discovered_fusions:
            profile.discovered_fusions.append(fusion_id)
            self._save_user_profile(profile)

    def add_unlocked_background(self, user_id: int, bg_id: str):
        profile = self._get_or_create_user_profile(user_id)

        if bg_id not in profile.unlocked_backgrounds:
            profile.unlocked_backgrounds.append(bg_id)
            self._save_user_profile(profile)

    def set_active_background(self, user_id: int, bg_id: str):
        profile = self._get_or_create_user_profile(user_id)
        profile.active_background = bg_id
        self._save_user_profile(profile)

    def get_sorted_leaderboard(self) -> List[Dict[str, Any]]:
        all_user_ids = self.get_all_user_ids()
        profiles = [self._get_or_create_user_profile(uid) for uid in all_user_ids]
        users = [{"user_id": p.user_id, "balance": p.balance} for p in profiles]
        return sorted(users, key=lambda u: u["balance"], reverse=True)

    def get_user_rank(self, user_id_to_find: int) -> Optional[int]:
        sorted_users = self.get_sorted_leaderboard()

        for i, user_entry in enumerate(sorted_users):
            if user_entry["user_id"] == user_id_to_find:
                return i + 1

        return None