import random
from datetime import datetime, timedelta
from typing import Any, Dict, List

from .game_state_helper import GameStateHelper
from .logging_helper import LoggingHelper
from .plant_helper import PlantHelper
from .time_helper import TimeHelper
from ..models import ShopItemDefinition


class ShopHelper:
    """Manages the state, stock, and refresh logic for all in-game shops."""

    def __init__(
        self,
        game_state_helper: GameStateHelper,
        plant_helper: PlantHelper,
        penny_shop_catalog: Dict[str, ShopItemDefinition],
        rux_shop_catalog: Dict[str, ShopItemDefinition],
        dave_shop_catalog: Dict[str, ShopItemDefinition],
        materials_catalog: Dict[str, str],
    ):
        self.game_state_helper = game_state_helper
        self.plant_helper = plant_helper
        self.penny_shop_catalog = penny_shop_catalog
        self.rux_shop_catalog = rux_shop_catalog
        self.dave_shop_catalog = dave_shop_catalog
        self.materials_catalog = materials_catalog

    def get_all_item_definitions(self) -> Dict[str, Any]:
        """
        Returns a consolidated dictionary of all known items from all shops and materials.
        """

        all_items = {}
        all_items.update(self.rux_shop_catalog)
        all_items.update(self.penny_shop_catalog)
        all_items.update(self.dave_shop_catalog)

        for mat_id, mat_name in self.materials_catalog.items():
            if mat_id not in all_items:
                all_items[mat_id] = {"name": mat_name, "id": mat_id}

        return all_items

    def get_next_penny_refresh_time(self, current_est_time: datetime) -> datetime:
        """Calculates the next scheduled refresh time for Penny's Treasures."""

        interval = self.game_state_helper.get_global_state("treasure_shop_refresh_interval_hours", 1)

        if not isinstance(interval, int) or interval <= 0 or 24 % interval != 0:
            interval = 1

        refresh_hours = list(range(0, 24, interval))

        for h in refresh_hours:
            refresh_time = current_est_time.replace(hour=h, minute=0, second=0, microsecond=0)
            if current_est_time < refresh_time:
                return refresh_time

        first_refresh_hour_of_day = refresh_hours[0]
        return (current_est_time + timedelta(days=1)).replace(
            hour=first_refresh_hour_of_day, minute=0, second=0, microsecond=0
        )

    def _generate_new_penny_stock(self) -> List[Dict[str, Any]]:
        """Generates a new random stock for Penny's Treasures."""

        all_penny_items = list(self.penny_shop_catalog.values())
        if not all_penny_items:
            return []

        return [
            {
                "id": item.id,
                "name": item.name,
                "price": item.cost,
                "stock": 1,
            }
            for item in all_penny_items
        ]

    async def refresh_penny_shop_if_needed(self, logger: LoggingHelper, force: bool = False):
        """Checks if Penny's shop needs a refresh and performs it IN MEMORY."""

        now_est = datetime.now(TimeHelper.EST)
        last_refresh_ts = self.game_state_helper.get_global_state("last_treasure_shop_refresh")

        needs_refresh = force
        if not needs_refresh and last_refresh_ts is None:
            needs_refresh = True
        elif not needs_refresh:
            last_refresh_dt = datetime.fromtimestamp(last_refresh_ts, tz=TimeHelper.EST)
            next_refresh = self.get_next_penny_refresh_time(last_refresh_dt)
            needs_refresh = now_est >= next_refresh

        if needs_refresh:
            await logger.log_to_discord("Penny's Shop: Refresh triggered.", "INFO")
            self.game_state_helper.set_global_state("treasure_shop_stock", self._generate_new_penny_stock())
            self.game_state_helper.set_global_state("last_treasure_shop_refresh", now_est.timestamp())

    def _generate_new_dave_stock(self) -> List[Dict[str, Any]]:
        """Generates the fixed-structure but partially randomized stock for Crazy Dave."""

        final_stock: List[Dict[str, Any]] = []
        ids_in_stock: set[str] = set()

        for item_def in self.dave_shop_catalog.values():
            final_stock.append({
                "id": item_def.id,
                "name": item_def.name,
                "price": item_def.cost,
                "stock": item_def.stock,
                "type": item_def.type,
            })
            ids_in_stock.add(item_def.id)

        for seedling_def in self.plant_helper.get_all_seedlings():
            final_stock.append({
                "id": seedling_def.id,
                "name": seedling_def.id,
                "price": seedling_def.cost,
                "stock": seedling_def.stock,
                "type": "seedling",
            })
            ids_in_stock.add(seedling_def.id)

        shop_plants = [p for p in self.plant_helper.base_plants if p.category == 'shop' and p.id not in ids_in_stock]
        for plant_def in shop_plants:
            final_stock.append({
                "id": plant_def.id,
                "name": plant_def.name,
                "price": 5000,
                "stock": 1,
                "type": "plant",
            })
            ids_in_stock.add(plant_def.id)

        all_base_plants = self.plant_helper.base_plants
        eligible_plants = [p for p in all_base_plants if p.shop and p.id not in ids_in_stock]

        num_to_add = min(len(eligible_plants), 4)
        if num_to_add > 0:
            for plant_def in random.sample(eligible_plants, num_to_add):
                final_stock.append({
                    "id": plant_def.id,
                    "name": plant_def.name,
                    "price": 5000,
                    "stock": 1,
                    "type": "plant",
                })
                ids_in_stock.add(plant_def.id)

        return final_stock

    async def refresh_dave_shop_if_needed(self, logger: LoggingHelper, force: bool = False):
        """Checks if Crazy Dave's shop needs its hourly refresh and performs it IN MEMORY."""

        now_est = datetime.now(TimeHelper.EST)
        last_refresh_ts = self.game_state_helper.get_global_state("last_dave_shop_refresh")

        needs_refresh = force
        if not needs_refresh and last_refresh_ts is None:
            needs_refresh = True
        elif not needs_refresh:
            last_refresh_dt = datetime.fromtimestamp(last_refresh_ts, tz=TimeHelper.EST)
            next_refresh = (last_refresh_dt + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            needs_refresh = now_est >= next_refresh

        if needs_refresh:
            await logger.log_to_discord("Dave's Shop: Refresh triggered.", "INFO")
            self.game_state_helper.set_global_state("dave_shop_stock", self._generate_new_dave_stock())
            self.game_state_helper.set_global_state("last_dave_shop_refresh", now_est.timestamp())