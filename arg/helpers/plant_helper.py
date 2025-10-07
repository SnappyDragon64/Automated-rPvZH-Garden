import random
from typing import Any, Dict, List, Optional


class PlantHelper:
    """
    Manages the master list of all plant and seedling definitions.
    This class loads and provides access to base plant data, categorized for different game mechanics.
    """

    def __init__(self, base_plants_list: List[Dict[str, Any]], seedlings_list: List[Dict[str, Any]]):
        """Initializes the PlantHelper with all necessary game data."""

        self.base_plants: List[Dict[str, Any]] = []
        self.base_plants_by_id: Dict[str, Dict[str, Any]] = {}
        self._load_base_plants(base_plants_list)

        self.seedlings_by_id: Dict[str, Dict[str, Any]] = {s['id']: s for s in seedlings_list}

        self.plants_by_category: Dict[str, List[Dict[str, Any]]] = {}
        self._categorize_plants()

    def _load_base_plants(self, loaded_plants_list: List[Dict[str, Any]]):
        """Processes and stores the list of base plants."""

        if not loaded_plants_list:
            print("CRITICAL: No base plants were provided to PlantHelper. Fallback is likely active.")

        processed_plants_list = []
        for plant_dict in loaded_plants_list:
            if isinstance(plant_dict, dict) and 'id' in plant_dict and 'name' not in plant_dict:
                plant_dict['name'] = plant_dict['id']

            processed_plants_list.append(plant_dict)

        self.base_plants = [p.copy() for p in processed_plants_list]
        self.base_plants_by_id = {p['id']: p.copy() for p in self.base_plants}

    def _categorize_plants(self):
        """Groups all base plants by their 'category' field for efficient lookup."""

        for plant in self.base_plants:
            category = plant.get("category")

            if category:
                if category not in self.plants_by_category:
                    self.plants_by_category[category] = []

                self.plants_by_category[category].append(plant.copy())

        if not self.plants_by_category.get("vanilla"):
            print("CRITICAL WARNING: No plants with category 'vanilla' were found. Regular seedlings will NOT grow!")

        for seedling_id, seedling_data in self.seedlings_by_id.items():
            category = seedling_data.get("category")

            if not self.plants_by_category.get(category):
                print(
                    f"CRITICAL WARNING: No plants found for category '{category}'. The seedling '{seedling_id}' will "
                    f"NOT grow! "
                )

    def get_base_plant_by_id(self, plant_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a base plant's definition dictionary by its unique ID."""
        return self.base_plants_by_id.get(plant_id)

    def get_seedling_by_id(self, seedling_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a seedling's definition by its unique ID."""
        return self.seedlings_by_id.get(seedling_id)

    def get_all_seedlings(self) -> List[Dict[str, Any]]:
        """Returns a list of all loaded seedling definitions."""
        return list(self.seedlings_by_id.values())

    def get_random_plant_by_category(self, category: str) -> Optional[Dict[str, Any]]:
        """Returns a random plant from a specified category."""
        plant_list = self.plants_by_category.get(category)

        if not plant_list:
            print(f"CRITICAL ERROR: Category '{category}' is empty or does not exist. Cannot get a random plant.")
            return None

        return random.choice(plant_list).copy()