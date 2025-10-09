from typing import Any, Dict

from redbot.core import Config

from .logging_helper import LoggingHelper


class GameStateHelper:
    """
    The single source of truth for all persistent game data.
    Manages the in-memory state and is the sole gatekeeper for disk I/O with Red's Config.
    """

    def __init__(self, config_object: Config, logger: LoggingHelper):
        self.config = config_object
        self.logger = logger
        self.game_state: Dict[str, Any] = {}

    async def load_game_state(self):
        """Loads the entire game state from disk into memory and initializes defaults."""

        self.game_state = await self.config.game_state()

        self.game_state.setdefault("users", {})
        self.game_state.setdefault("global_state", {})

        defaults = {
            "plant_growth_duration_minutes": 240,
            "treasure_shop_refresh_interval_hours": 1,
            "treasure_shop_stock": [],
            "last_treasure_shop_refresh": None,
            "dave_shop_stock": [],
            "last_dave_shop_refresh": None,
        }

        settings = self.game_state["global_state"]
        for key, value in defaults.items():
            settings.setdefault(key, value)

        await self.logger.log_to_discord("System Startup: Game state loaded into memory.", "INFO")

    def get_all_user_data(self) -> Dict[str, Dict]:
        return self.game_state.get("users", {})

    def get_user_data(self, user_id: int) -> Dict[str, Any]:
        return self.game_state.get("users", {}).get(str(user_id), {})

    def set_user_data(self, user_id: int, user_dict: Dict[str, Any]):
        self.game_state["users"][str(user_id)] = user_dict

    def get_global_state(self, key: str, default: Any = None) -> Any:
        return self.game_state.get("global_state", {}).get(key, default)

    def set_global_state(self, key: str, value: Any):
        self.game_state["global_state"][key] = value

    def get_rux_stock(self, item_id: str) -> int:
        return self.get_global_state(f"{item_id}_stock", 0)

    def set_rux_stock(self, item_id: str, stock: int):
        self.set_global_state(f"{item_id}_stock", stock)

    async def commit_to_disk(self):
        await self.config.game_state.set(self.game_state)