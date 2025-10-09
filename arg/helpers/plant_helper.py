import random
from typing import Dict, List, Optional

from ..models import BasePlant, SeedlingDefinition


class PlantHelper:
    """
    Manages the primary list of all plant and seedling definitions.
    This class loads and provides access to base plant data, categorized for different game mechanics.
    """

    def __init__(self, base_plants_list: List[BasePlant], seedlings_list: List[SeedlingDefinition]):
        """Initializes the PlantHelper with dataclass objects provided by DataHelper."""

        self.base_plants: List[BasePlant] = base_plants_list
        self.base_plants_by_id: Dict[str, BasePlant] = {p.id: p for p in base_plants_list}

        self.seedlings_by_id: Dict[str, SeedlingDefinition] = {s.id: s for s in seedlings_list}

        self.plants_by_category: Dict[str, List[BasePlant]] = {}
        self._categorize_plants()

    def _categorize_plants(self):
        """Groups all base plants by their 'category' field for efficient lookup."""

        for plant in self.base_plants:
            category = plant.category

            if category:
                if category not in self.plants_by_category:
                    self.plants_by_category[category] = []

                self.plants_by_category[category].append(plant)

        if "vanilla" not in self.plants_by_category:
            print("CRITICAL WARNING: No plants with category 'vanilla' were found. Regular seedlings will NOT grow!")

        for seedling_id, seedling_def in self.seedlings_by_id.items():
            category = seedling_def.category

            if category not in self.plants_by_category:
                print(
                    f"CRITICAL WARNING: No plants found for category '{category}'. The seedling '{seedling_id}' will "
                    f"NOT grow!"
                )

    def get_base_plant_by_id(self, plant_id: str) -> Optional[BasePlant]:
        return self.base_plants_by_id.get(plant_id)

    def get_seedling_by_id(self, seedling_id: str) -> Optional[SeedlingDefinition]:
        return self.seedlings_by_id.get(seedling_id)

    def get_all_seedlings(self) -> List[SeedlingDefinition]:
        return list(self.seedlings_by_id.values())

    def get_random_plant_by_category(self, category: str) -> Optional[BasePlant]:
        plant_list = self.plants_by_category.get(category)

        if not plant_list:
            print(f"CRITICAL ERROR: Category '{category}' is empty or does not exist. Cannot get a random plant.")
            return None

        return random.choice(plant_list)