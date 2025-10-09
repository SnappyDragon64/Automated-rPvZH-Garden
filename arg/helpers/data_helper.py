import json
import pathlib
from typing import Any, Dict, List

from ..models import (
    BasePlant,
    SeedlingDefinition,
    FusionRecipe,
    Background,
    ShopItemDefinition,
)
from .logging_helper import LoggingHelper


class DataHelper:
    """
    Handles the loading and validation of all JSON data files from the data directory.
    This class is responsible for parsing raw JSON into structured dataclass objects.
    It operates in a read-only manner on the data path.
    """

    def __init__(self, data_path_obj: pathlib.Path, logger: LoggingHelper):
        self.data_path = data_path_obj
        self.logger = logger

        self.rux_shop_data: Dict[str, ShopItemDefinition] = {}
        self.penny_shop_data: Dict[str, ShopItemDefinition] = {}
        self.dave_shop_data: Dict[str, ShopItemDefinition] = {}
        self.fusion_plants: List[FusionRecipe] = []
        self.materials_data: Dict[str, str] = {}
        self.base_plants: List[BasePlant] = []
        self.sales_prices: Dict[str, int] = {}
        self.seedlings_data: List[SeedlingDefinition] = []
        self.backgrounds_data: List[Background] = []

    def load_all_data(self):
        """Master method to load all data files and populate helper classes."""

        self.logger.init_log("Data loading process initiated.", "INFO")

        self.base_plants = self._load_base_plants_data()
        self.seedlings_data = self._load_seedlings_data()
        self.fusion_plants = self._load_fusion_data()
        self.backgrounds_data = self._load_backgrounds_data()
        self.rux_shop_data = self._load_rux_shop_data()
        self.penny_shop_data = self._load_penny_shop_data()
        self.dave_shop_data = self._load_dave_shop_data()
        self.materials_data = self._load_materials_data()
        self.sales_prices = self._load_sales_prices_data()

        self.logger.init_log("All data files loaded and processed.", "INFO")

    def _load_json_file(self, filename: str, default_data: Any) -> Any:
        """Generic JSON file loader with validation and logging. Does not write to disk."""

        file_path = self.data_path / filename
        log_prefix = f"Data Load ({filename}): "
        try:
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                if data:
                    self.logger.init_log(f"{log_prefix}Successfully loaded {len(data)} entries.", "INFO")
                    return data
                else:
                    self.logger.init_log(f"{log_prefix}File is empty. Using default fallback data.", "WARNING")
                    return default_data
            else:
                self.logger.init_log(
                    f"{log_prefix}File not found. This is a critical error if not intended. "
                    "Using default fallback data.", "ERROR"
                )
                return default_data
        except (json.JSONDecodeError, Exception) as e:
            self.logger.init_log(f"{log_prefix}Failed to load or parse: {e}. Using default fallback data.", "ERROR")
            return default_data


    def _load_base_plants_data(self) -> List[BasePlant]:
        fallback = [
            {"id": "Peashooter", "type": "base_plant", "name": "Peashooter", "category": "vanilla", "shop": False}]
        data = self._load_json_file("base_plants.json", fallback)

        plants = []
        for plant_dict in data:
            if 'name' not in plant_dict:
                plant_dict['name'] = plant_dict['id']
            plants.append(BasePlant(**plant_dict))
        return plants

    def _load_seedlings_data(self) -> List[SeedlingDefinition]:
        fallback = []
        data = self._load_json_file("seedlings.json", fallback)
        return [SeedlingDefinition(**s_dict) for s_dict in data]

    def _load_fusion_data(self) -> List[FusionRecipe]:
        fallback = []
        data = self._load_json_file("fusions.json", fallback)

        fusions = []
        for f_dict in data:
            if 'name' not in f_dict:
                f_dict['name'] = f_dict['id']
            f_dict['recipe'] = tuple(f_dict.get('recipe', []))
            fusions.append(FusionRecipe(**f_dict))
        return fusions

    def _load_backgrounds_data(self) -> List[Background]:
        fallback = [{"id": "default", "name": "Default", "image_file": "garden", "required_fusions": []}]
        data = self._load_json_file("backgrounds.json", fallback)

        backgrounds = []
        for bg_dict in data:
            bg_dict['required_fusions'] = tuple(bg_dict.get('required_fusions', []))
            backgrounds.append(Background(**bg_dict))
        return backgrounds

    def _load_rux_shop_data(self) -> Dict[str, ShopItemDefinition]:
        data = self._load_json_file("rux_shop.json", {})
        return {item_id: ShopItemDefinition(id=item_id, **details) for item_id, details in data.items()}

    def _load_penny_shop_data(self) -> Dict[str, ShopItemDefinition]:
        data = self._load_json_file("penny_shop.json", {})
        return {item_id: ShopItemDefinition(id=item_id, **details) for item_id, details in data.items()}

    def _load_dave_shop_data(self) -> Dict[str, ShopItemDefinition]:
        data = self._load_json_file("dave_shop.json", {})
        return {item_id: ShopItemDefinition(id=item_id, **details) for item_id, details in data.items()}

    def _load_materials_data(self) -> Dict[str, str]:
        return self._load_json_file("materials.json", {})

    def _load_sales_prices_data(self) -> Dict[str, int]:
        fallback = {"base_plant": 100}
        default = {
            "base_plant": 1000, "tier2": 4000, "tier3": 9000, "tier4": 16000,
            "tier5": 25000, "tier6": 36000, "tier7": 49000, "tier8": 64000, "tier9": 81000,
        }
        prices = self._load_json_file("sales_price.json", default)
        return prices if prices else fallback