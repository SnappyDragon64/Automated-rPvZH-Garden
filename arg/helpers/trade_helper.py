from collections import Counter
from typing import Any, Dict, Optional, Tuple

import discord

from ..models import UserProfileView, PlantedPlant
from .lock_helper import LockHelper


class TradeHelper:
    """Manages the state and execution of all user-to-user trades, including locking."""

    def __init__(self, lock_helper: LockHelper):
        self.lock_helper = lock_helper
        self.pending_trades: Dict[str, Dict[str, Any]] = {}

    def propose_trade(self, sender: discord.User, recipient: discord.User, trade_details: Dict[str, Any]) -> str:
        """Adds a new trade to the pending trades dictionary and locks both users."""

        trade_id = trade_details["id"]
        self.pending_trades[trade_id] = trade_details

        sender_lock_msg = f"Awaiting a response from {recipient.mention} for your proposal (`{trade_id}`)."
        recipient_lock_msg = f"Awaiting your response for a proposal from {sender.mention} (`{trade_id}`). " \
                             f"Please check your DMs."
        self.lock_helper.add_lock(sender.id, "trade", sender_lock_msg)
        self.lock_helper.add_lock(recipient.id, "trade", recipient_lock_msg)

        return trade_id

    def resolve_trade(self, trade_id: str) -> Optional[Dict[str, Any]]:
        """Removes a trade from the pending dictionary and unlocks the involved users."""

        trade = self.pending_trades.pop(trade_id, None)
        if trade:
            self.lock_helper.remove_lock_for_user(trade["sender_id"])
            self.lock_helper.remove_lock_for_user(trade["recipient_id"])
        return trade

    def execute_plant_trade(
            self,
            trade_data: Dict[str, Any],
            sender_profile: UserProfileView,
            recipient_profile: UserProfileView,
            sender_unlocked_slots: set
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Validates a plant trade using UserProfileViews and returns a plan of changes."""

        if not trade_data:
            return False, "Critical Error: Trade data was missing during execution.", None

        money_to_give = trade_data.get("money_sender_gives", 0)
        plants_info = trade_data.get("plants_sender_receives_info", [])

        if sender_profile.balance < money_to_give:
            return False, "Trade failed: Sender no longer has enough sun.", None

        free_sender_plots = sum(1 for i, p in enumerate(sender_profile.garden) if p is None and (i + 1) in sender_unlocked_slots)
        if free_sender_plots < len(plants_info):
            return False, "Trade failed: Sender no longer has enough free garden space.", None

        for plant_snapshot in plants_info:
            r_slot_index = plant_snapshot.get("r_slot_index")
            current_plant_in_slot = recipient_profile.garden[r_slot_index]
            original_plant_id = plant_snapshot.get("plant_data", {}).get("id")

            if not isinstance(current_plant_in_slot, PlantedPlant) or current_plant_in_slot.id != original_plant_id:
                return False, f"Trade failed: The plant in recipient's plot {r_slot_index + 1} has changed.", None

        changes = {
            "balance_updates": [
                {"user_id": trade_data["sender_id"], "amount": -money_to_give},
                {"user_id": trade_data["recipient_id"], "amount": money_to_give},
            ],
            "plant_moves": [],
        }

        temp_sender_garden = list(sender_profile.garden)
        for plant_snapshot in plants_info:
            r_slot_index = plant_snapshot["r_slot_index"]
            plant_to_move = recipient_profile.garden[r_slot_index]

            s_slot_index = next(i for i, p in enumerate(temp_sender_garden) if p is None and (i + 1) in sender_unlocked_slots)
            temp_sender_garden[s_slot_index] = plant_to_move

            changes["plant_moves"].append({
                "from_user_id": trade_data["recipient_id"],
                "from_plot_idx": r_slot_index,
                "to_user_id": trade_data["sender_id"],
                "to_plot_idx": s_slot_index,
                "plant_data": plant_to_move,
            })

        plant_names = ", ".join([f"**{p['plant_data'].get('name', 'Unknown')}**" for p in plants_info])
        success_message = f"Exchange of **{money_to_give:,}** sun for {plant_names} was successful."

        return True, success_message, changes

    def execute_item_trade(
            self,
            trade_data: Dict[str, Any],
            sender_profile: UserProfileView,
            recipient_profile: UserProfileView
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Validates an item trade using UserProfileViews and returns a plan of changes."""

        if not trade_data:
            return False, "Critical Error: Trade data was missing during execution.", None

        sun_to_give = trade_data.get("sun_sender_offers", 0)
        items_info = trade_data.get("items_info_list", [])

        if sender_profile.balance < sun_to_give:
            return False, "Trade failed: Sender no longer has enough sun.", None

        recipient_inv_counter = recipient_profile.inventory
        for item in items_info:
            if recipient_inv_counter.get(item.get("id"), 0) < item.get("count", 0):
                return False, f"Trade failed: Recipient no longer has enough **{item.get('name')}**.", None

        changes = {
            "balance_updates": [
                {"user_id": trade_data["sender_id"], "amount": -sun_to_give},
                {"user_id": trade_data["recipient_id"], "amount": sun_to_give},
            ],
            "item_transfers": [],
        }

        for item in items_info:
            changes["item_transfers"].append({
                "from_user_id": trade_data["recipient_id"],
                "to_user_id": trade_data["sender_id"],
                "item_id": item["id"],
                "quantity": item["count"],
            })

        traded_items_str = ", ".join([f"**{item['name']}** x{item['count']}" for item in items_info])
        success_message = f"Exchange of **{sun_to_give:,}** sun for {traded_items_str} was successful."

        return True, success_message, changes