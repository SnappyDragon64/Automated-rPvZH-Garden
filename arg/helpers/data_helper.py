import json
import pathlib
from typing import Any, Dict, List

from .logging_helper import LoggingHelper


class DataHelper:
    """Handles the loading and validation of all JSON data files from the data directory."""

    def __init__(self, data_path_obj: pathlib.Path, logger: LoggingHelper):
        self.data_path = data_path_obj
        self.logger = logger

        self.rux_shop_data: Dict[str, Any] = {}
        self.penny_shop_data: Dict[str, Any] = {}
        self.dave_shop_data: Dict[str, Any] = {}
        self.fusion_plants: List[Dict[str, Any]] = []
        self.materials_data: Dict[str, str] = {}
        self.base_plants: List[Dict[str, Any]] = []
        self.sales_prices: Dict[str, int] = {}
        self.seedlings_data: List[Dict[str, Any]] = []
        self.backgrounds_data: List[Dict[str, Any]] = []

    def load_all_data(self):
        """Master method to load all data files and populate helper classes."""

        self.logger.init_log("Data loading process initiated.", "INFO")

        self.rux_shop_data = self._load_rux_shop_data()
        self.penny_shop_data = self._load_penny_shop_data()
        self.dave_shop_data = self._load_dave_shop_data()
        self.fusion_plants = self._load_fusion_data()
        self.materials_data = self._load_materials_data()
        self.base_plants = self._load_base_plants_data()
        self.sales_prices = self._load_sales_prices_data()
        self.seedlings_data = self._load_seedlings_data()
        self.backgrounds_data = self._load_backgrounds_data()

        self.logger.init_log("All data files loaded and processed.", "INFO")

    def _load_json_file(self, filename: str, default_data: Any, data_type: type):
        """Generic JSON file loader with validation and logging."""

        file_path = self.data_path / filename
        log_prefix = f"Data Load ({filename}): "
        try:
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                if isinstance(data, data_type) and data:
                    self.logger.init_log(f"{log_prefix}Successfully loaded {len(data)} entries.", "INFO")
                    return data
                else:
                    self.logger.init_log(f"{log_prefix}File is empty or has incorrect format. Using default.",
                                         "WARNING")
                    return default_data
            else:
                self.logger.init_log(f"{log_prefix}File not found. Using default and creating template.", "WARNING")
                self._create_template_json(file_path, default_data)
                return default_data
        except (json.JSONDecodeError, Exception) as e:
            self.logger.init_log(f"{log_prefix}Failed to load or parse: {e}. Using default.", "ERROR")
            return default_data

    def _create_template_json(self, file_path: pathlib.Path, data: Any):
        """Creates a template JSON file."""

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)

            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)

            self.logger.init_log(f"Created template file at {file_path}.", "INFO")
        except Exception as e:
            self.logger.init_log(f"Could not create template file at {file_path}: {e}", "ERROR")

    def _load_base_plants_data(self) -> List[Dict[str, Any]]:
        fallback = [{"id": "Peashooter", "type": "base_plant", "name": "Peashooter", "category": "vanilla"}]
        return self._load_json_file("base_plants.json", fallback, list)

    def _load_sales_prices_data(self) -> Dict[str, int]:
        fallback = {"base_plant": 100, "default_error_price": 0}
        default = {
            "base_plant": 1000, "tier2": 4000, "tier3": 9000, "tier4": 16000,
            "tier5": 25000, "tier6": 36000, "tier7": 49000, "tier8": 64000, "tier9": 81000,
        }
        prices = self._load_json_file("sales_price.json", default, dict)
        return prices if prices else fallback

    def _load_rux_shop_data(self) -> Dict[str, Any]:
        return self._load_json_file("rux_shop.json", {}, dict)

    def _load_penny_shop_data(self) -> Dict[str, Any]:
        return self._load_json_file("penny_shop.json", {}, dict)

    def _load_dave_shop_data(self) -> Dict[str, Any]:
        return self._load_json_file("dave_shop.json", {}, dict)

    def _load_fusion_data(self) -> List[Dict[str, Any]]:
        fusions = self._load_json_file("fusions.json", [], list)

        for fusion in fusions:
            if 'id' in fusion and 'name' not in fusion:
                fusion['name'] = fusion['id']

        return fusions

    def _load_materials_data(self) -> Dict[str, str]:
        return self._load_json_file("materials.json", {}, dict)

    def _load_seedlings_data(self) -> List[Dict[str, Any]]:
        return self._load_json_file("seedlings.json", [], list)

    def _load_backgrounds_data(self) -> List[Dict[str, Any]]:
        fallback = [{"id": "default", "name": "Default", "image_file": "garden", "required_fusions": []}]
        return self._load_json_file("backgrounds.json", fallback, list)