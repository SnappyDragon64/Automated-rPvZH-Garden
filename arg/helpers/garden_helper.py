from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from redbot.core import Config


class GardenHelper:
    """Provides methods for accessing and mutating user-specific garden and inventory data."""

    def __init__(self, all_users_data: Dict[str, Dict[str, Any]], config_object: Config):
        self.users = all_users_data
        self.config = config_object

    async def _save_user_data(self, user_id: int):
        """A private helper to save a specific user's data to config."""

        user_id_str = str(user_id)
        if user_id_str in self.users:
            await self.config.users.set_raw(user_id_str, value=self.users[user_id_str])

    def get_user_data(self, user_id: int) -> Dict[str, Any]:
        """
        Retrieves a user's data dictionary, creating a default one if it doesn't exist.
        Also validates and ensures all required keys are present for existing users.
        """

        user_id_str = str(user_id)

        if user_id_str not in self.users:
            self.users[user_id_str] = {
                "balance": 0, "garden": [None] * 12, "inventory": [], "last_daily": None,
                "fusions": [], "roles": [], "storage_shed_slots": [None] * 8, "mastery": 0,
                "time_mastery": 0, "unlocked_backgrounds": ["default"], "active_background": "default"
            }

        user_entry = self.users[user_id_str]
        defaults = {
            "balance": 0, "garden": [None] * 12, "inventory": [], "last_daily": None,
            "fusions": [], "roles": [], "storage_shed_slots": [None] * 8, "mastery": 0,
            "time_mastery": 0, "unlocked_backgrounds": ["default"], "active_background": "default"
        }

        for key, value in defaults.items():
            user_entry.setdefault(key, value)

        if not isinstance(user_entry["garden"], list) or len(user_entry["garden"]) != 12:
            user_entry["garden"] = [None] * 12

        if not isinstance(user_entry["storage_shed_slots"], list) or len(user_entry["storage_shed_slots"]) != 8:
            user_entry["storage_shed_slots"] = [None] * 8

        return user_entry

    def is_slot_unlocked(self, user_data: Dict[str, Any], slot_1_indexed: int) -> bool:
        """Checks if a garden plot is unlocked for the user."""

        if 1 <= slot_1_indexed <= 6:
            return True

        return f"plot_{slot_1_indexed}" in user_data.get("inventory", [])

    async def update_seedling_progress(self, user_id: int, plot_index_0based: int, progress_increase: float):
        """Updates the progress of a seedling."""
        user_data = self.get_user_data(user_id)

        if 0 <= plot_index_0based < len(user_data["garden"]):
            slot_data = user_data["garden"][plot_index_0based]
            if isinstance(slot_data, dict) and slot_data.get("type") == "seedling":
                current_progress = slot_data.get("progress", 0.0)
                new_progress = min(current_progress + progress_increase, 100.0)
                slot_data["progress"] = new_progress

    async def plant_seedling(self, user_id: int, plot_index_0based: int, seedling_id: str, channel_id: int):
        """Places a new seedling object into a specific garden plot and saves."""

        user_data = self.get_user_data(user_id)
        user_data["garden"][plot_index_0based] = {
            "id": seedling_id, "type": "seedling", "progress": 0.0,
            "name": seedling_id, "notification_channel_id": channel_id
        }
        await self._save_user_data(user_id)

    async def set_garden_plot(self, user_id: int, plot_index_0based: int, plant_data: Optional[Dict[str, Any]]):
        """Sets the content of a single garden plot and saves."""

        user_data = self.get_user_data(user_id)
        if 0 <= plot_index_0based < len(user_data["garden"]):
            user_data["garden"][plot_index_0based] = plant_data
        await self._save_user_data(user_id)

    async def set_full_garden(self, user_id: int, new_garden_list: List[Optional[Dict[str, Any]]]):
        """Replaces the entire garden array for a user and saves."""

        user_data = self.get_user_data(user_id)
        user_data["garden"] = new_garden_list
        await self._save_user_data(user_id)

    def get_text_garden_display(self, user_data: Dict[str, Any]) -> Tuple[str, str]:
        """Generates the two-column text-based garden string for the profile command."""

        garden_display_lines, garden_slots_data = [], user_data.get("garden", [])

        for i in range(12):
            slot_prefix = f"**{i + 1}:**"

            if not self.is_slot_unlocked(user_data, i + 1):
                garden_display_lines.append(f"{slot_prefix} 🔒 Locked")
            else:
                plant = garden_slots_data[i]

                if plant is None:
                    garden_display_lines.append(f"{slot_prefix} 🟫 Unoccupied")
                elif isinstance(plant, dict) and plant.get("type") == "seedling":
                    garden_display_lines.append(f"{slot_prefix} 🌱 Seedling ({plant.get('progress', 0.0):.1f}%)")
                elif isinstance(plant, dict):
                    garden_display_lines.append(f"{slot_prefix} 🌿 {plant.get('name', plant.get('id', 'Unknown'))}")
                else:
                    garden_display_lines.append(f"{slot_prefix} ❓ Unknown State")

        return "\n".join(garden_display_lines[:6]), "\n".join(garden_display_lines[6:])

    def user_has_storage_shed(self, user_data: Dict[str, Any]) -> bool:
        """Checks if the user has purchased the 'storage_shed' item."""
        return "storage_shed" in user_data.get("inventory", [])

    def get_storage_capacity(self, user_data: Dict[str, Any]) -> int:
        """Determines the user's storage shed capacity based on their inventory."""

        if not self.user_has_storage_shed(user_data):
            return 0

        capacity = 4

        if "shed_upgrade" in user_data.get("inventory", []):
            capacity += 4

        return capacity

    def get_formatted_storage_contents(self, user_data: Dict[str, Any]) -> Tuple[List[str], int, int]:
        """Gets a list of formatted strings representing the storage shed's contents."""

        capacity = self.get_storage_capacity(user_data)
        shed_slots = user_data.get("storage_shed_slots", [])
        occupied = sum(1 for slot in shed_slots[:capacity] if slot is not None)
        display_lines = []

        for i in range(capacity):
            slot_content = shed_slots[i]

            if slot_content and isinstance(slot_content, dict):
                display_lines.append(
                    f"**{i + 1}.** {slot_content.get('name', slot_content.get('id', 'Unknown Plant'))}")
            else:
                display_lines.append(f"**{i + 1}.** <Empty>")
        return display_lines, occupied, capacity

    async def store_plant(self, user_id: int, plot_index_0based: int) -> Tuple[bool, str]:
        """Moves a plant from a garden plot to storage and saves."""

        user_data = self.get_user_data(user_id)
        capacity = self.get_storage_capacity(user_data)
        shed_slots = user_data.get("storage_shed_slots", [])

        if sum(1 for s in shed_slots[:capacity] if s is not None) >= capacity:
            return False, "Insufficient storage shed capacity."

        plant_to_move = user_data["garden"][plot_index_0based]
        first_empty_slot = next((i for i, s in enumerate(shed_slots) if s is None), -1)

        if first_empty_slot == -1 or first_empty_slot >= capacity:
            return False, "Internal Error: Could not find an empty storage slot."

        shed_slots[first_empty_slot] = plant_to_move
        user_data["garden"][plot_index_0based] = None
        await self._save_user_data(user_id)
        return True, f"**{plant_to_move.get('name', 'Plant')}** (plot {plot_index_0based + 1}) -> storage slot " \
                     f"{first_empty_slot + 1}"

    async def unstore_plant(self, user_id: int, storage_index_0based: int) -> Tuple[bool, str]:
        """Moves a plant from storage to a garden plot and saves."""

        user_data = self.get_user_data(user_id)
        plots = [i for i, s in enumerate(user_data["garden"]) if self.is_slot_unlocked(user_data, i + 1) and s is None]

        if not plots:
            return False, "Insufficient garden capacity."

        plant_to_move = user_data["storage_shed_slots"][storage_index_0based]
        target_plot_idx = plots[0]
        user_data["garden"][target_plot_idx] = plant_to_move
        user_data["storage_shed_slots"][storage_index_0based] = None
        await self._save_user_data(user_id)
        return True, f"**{plant_to_move.get('name', 'Plant')}** (storage {storage_index_0based + 1}) -> garden plot " \
                     f"{target_plot_idx + 1}"

    async def set_balance(self, user_id: int, amount: int):
        user_data = self.get_user_data(user_id)
        user_data["balance"] = max(0, amount)
        await self._save_user_data(user_id)

    async def set_sun_mastery(self, user_id: int, level: int):
        user_data = self.get_user_data(user_id)
        user_data["mastery"] = max(0, level)
        await self._save_user_data(user_id)

    async def set_time_mastery(self, user_id: int, level: int):
        user_data = self.get_user_data(user_id)
        user_data["time_mastery"] = max(0, level)
        await self._save_user_data(user_id)

    async def add_balance(self, user_id: int, amount: int):
        if amount > 0:
            user_data = self.get_user_data(user_id)
            user_data["balance"] += amount
            await self._save_user_data(user_id)

    async def remove_balance(self, user_id: int, amount: int):
        if amount > 0:
            user_data = self.get_user_data(user_id)
            user_data["balance"] = max(0, user_data["balance"] - amount)
            await self._save_user_data(user_id)

    async def add_item_to_inventory(self, user_id: int, item_id: str, quantity: int = 1):
        user_data = self.get_user_data(user_id)

        for _ in range(quantity):
            user_data["inventory"].append(item_id)

        await self._save_user_data(user_id)

    async def remove_item_from_inventory(self, user_id: int, item_id: str, quantity: int = 1) -> bool:
        user_data = self.get_user_data(user_id)

        if Counter(user_data["inventory"]).get(item_id, 0) < quantity:
            return False

        for _ in range(quantity):
            try:
                user_data["inventory"].remove(item_id)
            except ValueError:
                return False

        await self._save_user_data(user_id)
        return True

    async def set_last_daily(self, user_id: int, date_str: str):
        """Updates the user's last_daily timestamp and saves."""

        user_data = self.get_user_data(user_id)
        user_data["last_daily"] = date_str
        await self._save_user_data(user_id)

    async def increment_mastery(self, user_id: int, amount: int = 1):
        """Increments a user's Sun Mastery level and saves."""

        user_data = self.get_user_data(user_id)
        user_data["mastery"] += amount
        await self._save_user_data(user_id)

    async def increment_time_mastery(self, user_id: int, amount: int = 1):
        """Increments a user's Time Mastery level and saves."""

        user_data = self.get_user_data(user_id)
        user_data["time_mastery"] += amount
        await self._save_user_data(user_id)

    async def add_fusion_discovery(self, user_id: int, fusion_id: str):
        """Adds a new fusion to the user's discovered list and saves."""

        user_data = self.get_user_data(user_id)

        if fusion_id not in user_data["fusions"]:
            user_data["fusions"].append(fusion_id)
            await self._save_user_data(user_id)

    async def add_unlocked_background(self, user_id: int, bg_id: str):
        """Adds a new background to the user's unlocked list and saves."""

        user_data = self.get_user_data(user_id)

        if bg_id not in user_data["unlocked_backgrounds"]:
            user_data["unlocked_backgrounds"].append(bg_id)
            await self._save_user_data(user_id)

    async def set_active_background(self, user_id: int, bg_id: str):
        """Sets the user's active background and saves."""

        user_data = self.get_user_data(user_id)
        user_data["active_background"] = bg_id
        await self._save_user_data(user_id)

    def get_sorted_leaderboard(self) -> List[Dict[str, Any]]:
        """Filters and sorts all users by balance to generate leaderboard data."""

        users = [{"user_id": uid, "balance": u_data["balance"]} for uid, u_data in self.users.items() if
                 isinstance(u_data, dict) and "balance" in u_data]
        return sorted(users, key=lambda u: u["balance"], reverse=True)

    def get_user_rank(self, user_id_to_find: int) -> Optional[int]:
        """Calculates the leaderboard rank for a specific user."""

        sorted_users = self.get_sorted_leaderboard()
        for i, user_entry in enumerate(sorted_users):
            if user_entry["user_id"] == str(user_id_to_find):
                return i + 1

        return None