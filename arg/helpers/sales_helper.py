from typing import Any, Dict, Tuple


class SalesHelper:
    """A helper class for managing the sale prices and processing of plant sales."""

    def __init__(self, loaded_prices: Dict[str, int], currency_emoji: str):
        """Initializes the SalesHelper with price data and configuration."""

        self.SALES_PRICES = loaded_prices
        self.CURRENCY_EMOJI = currency_emoji

        if not self.SALES_PRICES:
            print("CRITICAL: No sales prices were provided to SalesHelper instance. Fallback may be active.")

    def get_sale_price(self, plant_type: str) -> int:
        """Gets the sale price for a given plant type (tier)."""

        if not self.SALES_PRICES:
            print("CRITICAL ERROR: SALES_PRICES is empty in get_sale_price. Returning 0.")
            return 0

        return self.SALES_PRICES.get(plant_type, 0)

    def process_sales(self, user_data: Dict[str, Any], slots_to_sell_from: Tuple[int, ...]) -> Dict[str, Any]:
        """Processes the sale of plants from specified plots, calculating earnings and mastery."""

        results = {
            "total_earnings": 0,
            "sold_plants_details": [],
            "error_messages": [],
            "mastery_gained": 0,
            "time_mastery_gained": 0,
            "plots_to_clear": []
        }

        for slot_num_1based in set(slots_to_sell_from):
            plot_idx_0based = slot_num_1based - 1
            if not (0 <= plot_idx_0based < 12):
                results["error_messages"].append(f"Plot {slot_num_1based}: Invalid designation (must be 1-12).")
                continue

            plant_to_sell = user_data["garden"][plot_idx_0based]
            if not isinstance(plant_to_sell, dict) or plant_to_sell.get("type") == "seedling":
                results["error_messages"].append(
                    f"Plot {slot_num_1based}: Is empty or contains a non-sellable seedling.")
                continue

            plant_name = plant_to_sell.get("name", "Unknown Asset")
            plant_type = plant_to_sell.get("type", "base_plant")

            if plant_type == "tier∞":
                results["mastery_gained"] += 1
                results["sold_plants_details"].append(
                    f"**{plant_name}** from plot {slot_num_1based} has transcended reality, increasing your Sun "
                    f"Mastery!")
                results["plots_to_clear"].append(plot_idx_0based)
                continue

            if plant_type == "tier-∞":
                results["time_mastery_gained"] += 1
                results["sold_plants_details"].append(
                    f"**{plant_name}** from plot {slot_num_1based} has transcended reality, increasing your Time "
                    f"Mastery!")
                results["plots_to_clear"].append(plot_idx_0based)
                continue

            sale_price = self.get_sale_price(plant_type)
            if sale_price <= 0:
                results["error_messages"].append(f"Plot {slot_num_1based}: Asset '{plant_name}' has no market value.")
                continue

            sun_mastery_bonus = 1 + (0.1 * user_data.get("mastery", 0))
            final_sale_price = int(sale_price * sun_mastery_bonus)
            results["total_earnings"] += final_sale_price

            bonus_text = f" (Boosted by {sun_mastery_bonus:.2f}x)" if sun_mastery_bonus > 1 else ""
            results["sold_plants_details"].append(
                f"**{plant_name}** from plot {slot_num_1based} (Yield: +{final_sale_price:,} "
                f"{self.CURRENCY_EMOJI}){bonus_text}")
            results["plots_to_clear"].append(plot_idx_0based)

        return results
