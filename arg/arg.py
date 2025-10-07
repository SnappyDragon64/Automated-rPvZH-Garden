import asyncio
import io
import json
import pathlib
import random
import re
import time
import traceback
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import pytz

import discord
from redbot.core import Config, commands, data_manager

try:
    from PIL import Image, ImageDraw, ImageFont

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    Image, ImageDraw, ImageFont = None, None, None


class TimeHelper:
    """A static helper class for standardized time and date operations."""
    EST = pytz.timezone('US/Eastern')

    @staticmethod
    def get_est_date() -> str:
        return datetime.now(TimeHelper.EST).strftime('%Y-%m-%d')

    @staticmethod
    def get_current_timestamp() -> int:
        """Returns the current Unix timestamp as an integer."""
        return int(time.time())


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


class LockHelper:
    """Manages all non-persistent, in-memory user locks for the cog."""

    def __init__(self):
        self._locks: List[Dict[str, Any]] = []

    def get_user_lock(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Retrieves the lock object for a user if they are locked."""

        for lock in self._locks:
            if lock.get("user_id") == user_id:
                return lock

        return None

    def add_lock(self, user_id: int, lock_type: str, message: str):
        """Applies a lock to a user. Does nothing if the user is already locked."""

        if not self.get_user_lock(user_id):
            self._locks.append({
                "user_id": user_id,
                "type": lock_type,
                "message": message,
                "timestamp": time.time()
            })

    def remove_lock_for_user(self, user_id: int):
        """Removes a lock from a specific user."""

        self._locks = [lock for lock in self._locks if lock.get("user_id") != user_id]

    def clear_all_locks(self):
        """Removes all active locks. To be used on cog unload."""

        self._locks = []


class LoggingHelper:
    """Handles all logging operations, including Discord channel and console output."""

    def __init__(self, bot: commands.Bot, log_channel_id: int):
        self.bot = bot
        self.log_channel_id = log_channel_id
        self._init_log_queue: List[Tuple[str, str]] = []

    async def log_to_discord(self, message: str, level: str = "INFO", embed: Optional[discord.Embed] = None):
        """Sends a formatted log message to the designated Discord log channel."""

        if not self.bot.is_ready():
            self._init_log_queue.append((message, level))
            print(f"[LOG_QUEUE|{level.upper()}] Bot not ready. Queued: {message}")
            return

        log_channel = self.bot.get_channel(self.log_channel_id)

        if not isinstance(log_channel, discord.TextChannel):
            print(
                f"[LOG_ERROR|{level.upper()}] Log channel {self.log_channel_id} not found or not a TextChannel. "
                f"Message: {message}")
            return

        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        log_prefix = f"`[{timestamp}] [{level.upper()}]` "

        try:
            full_message = log_prefix + message

            if len(full_message) <= 2000:
                await log_channel.send(content=full_message, embed=embed,
                                       allowed_mentions=discord.AllowedMentions.none())
            else:
                await log_channel.send(content=f"{log_prefix}Log message exceeds 2000 characters. See chunks below.",
                                       embed=embed, allowed_mentions=discord.AllowedMentions.none())

                for i in range(0, len(message), 1900):
                    await log_channel.send(f"```{level.upper()} Chunk {i // 1900 + 1}```\n{message[i:i + 1900]}")
        except discord.Forbidden:
            print(f"[LOG_FORBIDDEN] No permission to send to log channel {self.log_channel_id}.")
        except discord.HTTPException as e:
            print(f"[LOG_HTTP_ERROR] Failed to send to log channel {self.log_channel_id}: {e}")

    def init_log(self, message: str, level: str = "INFO"):
        """
        Synchronous logger for use during cog initialization. Queues logs to be sent
        once the bot is ready. Also prints to console immediately.
        """

        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        print(f"[INIT_LOG|{level.upper()}|{timestamp}] {message}")

        if self.bot and hasattr(self.bot, 'loop') and self.bot.loop.is_running():
            self.bot.loop.create_task(self.log_to_discord(message, level=level))
        else:
            self._init_log_queue.append((message, level))

    async def flush_init_log_queue(self):
        """Sends any queued logs that were generated before the bot was ready."""

        if self._init_log_queue:
            self.init_log(f"Flushing {len(self._init_log_queue)} queued startup logs...", "DEBUG")
            for msg, level in self._init_log_queue:
                await self.log_to_discord(msg, level)
            self._init_log_queue.clear()


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


class ImageHelper:
    """Handles all PIL-based image generation for the cog."""

    _PLANT_IMAGE_ASSET_SIZE: int = 128
    _PLANT_SCALED_SIZE_PROFILE: int = 120
    _PLANT_SPACING: int = 20
    _GRID_OFFSET_X: int = 70
    _GRID_OFFSET_Y: int = 50
    _GRID_COLUMNS: int = 4
    _GRID_ROWS: int = 3
    PLANT_SLOT_COORDINATES: List[Tuple[int, int]] = []

    def __init__(self, data_path_obj: pathlib.Path, logger: LoggingHelper):
        if not PIL_AVAILABLE:
            logger.init_log("Pillow (PIL) not found. Image generation will be disabled.", "CRITICAL")
        self.data_path = data_path_obj
        self.logger = logger
        self._is_ready = False

        for r_idx in range(self._GRID_ROWS):
            for c_idx in range(self._GRID_COLUMNS):
                x = self._GRID_OFFSET_X + c_idx * (self._PLANT_IMAGE_ASSET_SIZE + self._PLANT_SPACING)
                y = self._GRID_OFFSET_Y + r_idx * (self._PLANT_IMAGE_ASSET_SIZE + self._PLANT_SPACING)
                self.PLANT_SLOT_COORDINATES.append((x, y))

        self.base_garden_image: Optional[Image.Image] = None
        self.locked_slot_image: Optional[Image.Image] = None
        self.empty_slot_image: Optional[Image.Image] = None
        self.seedling_image_template: Optional[Image.Image] = None

    def _sanitize_id_for_filename(self, plant_id: str) -> str:
        """Replaces spaces with underscores to create a valid filename component."""

        return plant_id.replace(" ", "_")

    def _get_image_path(self, filename: str) -> pathlib.Path:
        """Constructs the full path to an image asset within the data directory."""

        return self.data_path / "images" / filename

    def get_image_file_for_plant(self, plant_id: str) -> Optional[discord.File]:
        """Creates a discord.File object for a given plant ID if the image asset exists."""

        if not plant_id:
            return None

        sanitized_filename = f"{self._sanitize_id_for_filename(plant_id)}.png"
        image_path = self._get_image_path(sanitized_filename)

        if image_path.exists():
            try:
                return discord.File(str(image_path), filename=sanitized_filename)
            except Exception as e:
                self.logger.log_to_discord(f"DEBUG: Failed to create discord.File for {image_path}: {e}", "WARNING")
                return None

        return None

    def load_assets(self):
        """Loads all necessary image assets from disk into memory."""

        if not PIL_AVAILABLE:
            return

        self.base_garden_image = self._load_image_asset("garden.png", resize=False)
        self.locked_slot_image = self._load_image_asset("locked_slot.png")
        self.empty_slot_image = self._load_image_asset("empty_slot.png")
        self.seedling_image_template = self._load_image_asset("Seedling.png")

        if self.base_garden_image:
            self._is_ready = True
            self.logger.init_log("Image assets loaded successfully.", "INFO")
        else:
            self._is_ready = False
            self.logger.init_log("Base 'garden.png' asset failed to load. Image generation disabled.", "CRITICAL")

    def _load_image_asset(self, filename: str, resize: bool = True) -> Optional[Image.Image]:
        """Loads and optionally resizes a single image asset."""

        try:
            path = self._get_image_path(filename)

            if not path.exists():
                self.logger.init_log(f"Image asset '{filename}' not found at {path}.", "ERROR")
                return None

            img = Image.open(path).convert("RGBA")

            if resize and img.size != (self._PLANT_IMAGE_ASSET_SIZE, self._PLANT_IMAGE_ASSET_SIZE):
                img = img.resize((self._PLANT_IMAGE_ASSET_SIZE, self._PLANT_IMAGE_ASSET_SIZE), Image.Resampling.LANCZOS)

            return img
        except Exception as e:
            self.logger.init_log(f"Failed to load or process image asset '{filename}': {e}", "ERROR")
            return None

    def _draw_progress_on_seedling(self, seedling_image: Image.Image, progress: float) -> Image.Image:
        """Draws a progress percentage on a copy of a seedling image."""

        img_copy = seedling_image.copy()
        draw = ImageDraw.Draw(img_copy)
        progress_text = f"{progress:.1f}%"

        try:
            font = ImageFont.truetype("arial.ttf", 30)
        except IOError:
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), progress_text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = (self._PLANT_IMAGE_ASSET_SIZE - text_width) / 2
        y = self._PLANT_IMAGE_ASSET_SIZE - text_height - 15

        draw.text((x, y), progress_text, font=font, fill=(255, 255, 255, 255), stroke_width=2,
                  stroke_fill=(0, 0, 0, 255))

        return img_copy

    async def generate_garden_image(self, user_data: Dict[str, Any], unlocked_slots: set,
                                    background_filename: str = "garden.png") -> Optional[discord.File]:
        """Generates a complete garden profile image for a user."""

        if not self._is_ready:
            return None

        base_image_to_use = self._load_image_asset(background_filename, resize=False)

        if not base_image_to_use:
            base_image_to_use = self.base_garden_image

        if not self._is_ready or not base_image_to_use:
            return None

        garden_image = base_image_to_use.copy()

        garden_slots = user_data.get("garden", [])
        offset_for_centering = (self._PLANT_IMAGE_ASSET_SIZE - self._PLANT_SCALED_SIZE_PROFILE) // 2

        for i, slot_content in enumerate(garden_slots):
            plant_asset_to_render = None
            slot_num_1_indexed = i + 1

            if slot_num_1_indexed not in unlocked_slots:
                plant_asset_to_render = self.locked_slot_image
            elif slot_content is None:
                plant_asset_to_render = self.empty_slot_image
            elif isinstance(slot_content, dict):
                plant_type = slot_content.get("type")
                plant_id = slot_content.get("id")

                if plant_type == "seedling":
                    template_to_use = self.seedling_image_template

                    sanitized_filename = f"{self._sanitize_id_for_filename(plant_id)}.png"
                    loaded_template = self._load_image_asset(sanitized_filename, resize=True)

                    if loaded_template:
                        template_to_use = loaded_template

                    if template_to_use:
                        progress = slot_content.get("progress", 0.0)
                        plant_asset_to_render = self._draw_progress_on_seedling(template_to_use, progress)
                elif plant_id:
                    sanitized_filename = f"{self._sanitize_id_for_filename(plant_id)}.png"
                    plant_asset_to_render = self._load_image_asset(sanitized_filename)

            if plant_asset_to_render:
                scaled_asset = plant_asset_to_render.resize(
                    (self._PLANT_SCALED_SIZE_PROFILE, self._PLANT_SCALED_SIZE_PROFILE),
                    Image.Resampling.LANCZOS
                )

                slot_base_x, slot_base_y = self.PLANT_SLOT_COORDINATES[i]
                paste_x = slot_base_x + offset_for_centering
                paste_y = slot_base_y + offset_for_centering

                garden_image.paste(scaled_asset, (int(paste_x), int(paste_y)), scaled_asset)

        img_byte_arr = io.BytesIO()
        garden_image.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        return discord.File(img_byte_arr, filename="garden_profile.png")


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


class FusionHelper:
    """Encapsulates all logic related to plant and item fusion."""

    def __init__(self, fusions_list: List[Dict[str, Any]], materials_data: Dict[str, str], plant_helper: PlantHelper):
        self.all_fusions = fusions_list
        self.all_materials = materials_data
        self.all_materials_by_name = set(materials_data.values())
        self.all_fusions_by_id = {f['id']: f for f in fusions_list}
        self.all_fusions_by_name = {f['name']: f for f in fusions_list if 'name' in f}
        self.plant_helper = plant_helper

        self.visible_fusions: List[Dict[str, Any]] = []
        self.hidden_fusions_by_id: Dict[str, Dict[str, Any]] = {}

        for f in self.all_fusions:
            visibility = f.get("visibility", "visible")

            if visibility == "visible":
                self.visible_fusions.append(f)
            elif visibility == "hidden":
                self.hidden_fusions_by_id[f['id']] = f

    def find_defined_fusion(self, query: str) -> Optional[Dict[str, Any]]:
        """Searches for a fusion definition by ID or name (case-insensitive)."""

        query_lower = query.lower()

        for f_def in self.all_fusions:
            if f_def.get("id", "").lower() == query_lower:
                return f_def.copy()

        for f_def in self.all_fusions:
            if f_def.get("name", "").lower() == query_lower:
                return f_def.copy()

        return None

    def format_recipe_string(self, recipe_ids: List[str]) -> str:
        """Formats a list of component IDs into a displayable string like '`PlantA` + `PlantB`'."""
        if not recipe_ids:
            return "Unknown Recipe"

        component_names = []
        for comp_id in recipe_ids:
            name = comp_id
            if base_plant := self.plant_helper.get_base_plant_by_id(comp_id):
                name = base_plant.get("name", comp_id)
            elif fusion_def := self.find_defined_fusion(comp_id):
                name = fusion_def.get("name", comp_id)
            component_names.append(f"`{name}`")

        if len(component_names) > 12:
            return " + ".join(component_names[:12]) + " + ..."
        return " + ".join(component_names)

    def deconstruct_plant(
            self,
            plant_data: Dict[str, Any],
            path: Optional[set] = None
    ) -> Tuple[List[str], List[str]]:
        """Recursively deconstructs a plant into its base material and plant component names."""
        if path is None:
            path = set()

        plant_id = plant_data.get("id")
        plant_name = plant_data.get("name", plant_id)

        if plant_id in path:
            return [], [f"Infinite recursion detected involving '{plant_name}'."]
        path.add(plant_id)

        if plant_data.get("type") == "material" or plant_name in self.all_materials_by_name:
            return [plant_name], []

        if plant_data.get("type") == "base_plant":
            return [plant_name], []

        fusion_def = self.all_fusions_by_id.get(plant_id)
        if not fusion_def or "recipe" not in fusion_def:
            return [], [f"Recipe for fusion '{plant_name}' is missing."]

        final_components: List[str] = []
        errors: List[str] = []

        all_base_plants_by_name = {p['name']: p for p in self.plant_helper.base_plants if 'name' in p}

        for component_name in fusion_def.get("recipe", []):
            if component_name in all_base_plants_by_name:
                final_components.append(component_name)
            elif component_name in self.all_materials_by_name:
                final_components.append(component_name)
            elif component_name in self.all_fusions_by_name:
                next_fusion_def = self.all_fusions_by_name[component_name]
                sub_components, sub_errors = self.deconstruct_plant(next_fusion_def, path.copy())
                final_components.extend(sub_components)
                errors.extend(sub_errors)
            else:
                errors.append(f"Recipe for '{plant_name}' contains unknown component: '{component_name}'.")

        return final_components, errors

    def find_fusion_match(self, components: List[str]) -> Optional[Dict[str, Any]]:
        """Given a list of base component names, finds a matching fusion recipe."""

        input_recipe_counter = Counter(components)

        for fusion_def in self.all_fusions:
            recipe_counter = Counter(fusion_def.get("recipe", []))

            if recipe_counter and recipe_counter == input_recipe_counter:
                return fusion_def

        return None

    def parse_almanac_args(self, full_args: str) -> dict:
        """Parses filters and a page number from a single string."""

        filters = []
        page = 1

        if not full_args or not full_args.strip():
            return {'filters': filters, 'page': page}

        words = full_args.strip().split()
        if words[-1].isdigit():
            page = int(words.pop())

        filter_string = " ".join(words)
        if not filter_string:
            return {'filters': filters, 'page': page}

        filter_parts = re.split(r'\s+(?=\w+:)', filter_string)

        for part in filter_parts:
            if ":" in part:
                key, value = part.split(":", 1)
                filters.append({'key': key.strip().lower(), 'value': value.strip().lower()})

        return {'filters': filters, 'page': page}

    def apply_almanac_filters(self, fusions_list: List[dict], filters: List[dict], discovered_ids: set, **kwargs) -> \
            List[dict]:
        """Applies a list of parsed filters to a list of fusion definitions."""

        if not filters:
            return fusions_list

        filtered_results = list(fusions_list)
        mat_ids_to_names = self.all_materials
        mat_names_to_ids = {v.lower(): k for k, v in mat_ids_to_names.items()}
        plans_by_fusion_id = kwargs.get("plans_by_fusion_id", {})

        for f_filter in filters:
            key, value = f_filter['key'], f_filter['value']

            if key == 'name':
                filtered_results = [f for f in filtered_results if value in f.get('name', '').lower()]
            elif key == 'contains':
                temp_results = []
                searched_fusion = self.find_defined_fusion(value)

                if searched_fusion:
                    search_recipe_counter = Counter(searched_fusion.get('recipe', []))

                    for f in filtered_results:
                        recipe_counter = Counter(f.get('recipe', []))
                        is_subset = all(recipe_counter[item] >= count for item, count in search_recipe_counter.items())

                        if is_subset:
                            temp_results.append(f)
                else:
                    for f in filtered_results:
                        for component_name in f.get('recipe', []):
                            if value in component_name.lower():
                                temp_results.append(f)
                                break

                            component_id = mat_names_to_ids.get(component_name.lower())

                            if component_id and value in component_id:
                                temp_results.append(f)
                                break

                filtered_results = temp_results
            elif key == 'discovered':
                is_true = value == 'true'
                filtered_results = [f for f in filtered_results if (f.get('id') in discovered_ids) == is_true]
            elif key == 'storage':
                if not plans_by_fusion_id:
                    continue

                if value == 'false':
                    temp_results = []

                    for f in filtered_results:
                        plan = plans_by_fusion_id.get(f['id'])

                        if plan and not any(asset.get("source") == "storage" for asset in plan):
                            temp_results.append(f)

                    filtered_results = temp_results
            elif key == 'tier':
                normalized_value = "tier" + value.lower().replace("infinity", "∞").replace("inf", "∞").replace("tier",
                                                                                                               "")
                filtered_results = [f for f in filtered_results if f.get('type', '').lower() == normalized_value]
            elif key == 'missing':
                pass

        return filtered_results

    def get_user_whole_assets_with_source(self, user_data: dict) -> List[dict]:
        """Gathers all user assets, tagging them with source and index."""

        assets = []

        for i, plant in enumerate(user_data.get("garden", [])):
            if isinstance(plant, dict) and plant.get("type") != "seedling":
                assets.append({**plant, "source": "garden", "index": i})

        for i, plant in enumerate(user_data.get("storage_shed_slots", [])):
            if isinstance(plant, dict):
                assets.append({**plant, "source": "storage", "index": i})

        for item_id in user_data.get("inventory", []):
            if item_name := self.all_materials.get(item_id):
                assets.append(
                    {"name": item_name, "id": item_id, "type": "material", "source": "inventory", "index": -1})

        return assets

    def get_valid_crafting_components(self, assets_list: List[dict]) -> List[dict]:
        """Filters a list of assets to return only those valid for use as fusion components."""

        validated_assets = []
        for asset in assets_list:
            asset_type = asset.get("type")

            if asset_type == "material" or asset_type == "base_plant":
                validated_assets.append(asset)
                continue

            fusion_def = self.all_fusions_by_id.get(asset.get("id"))

            if not fusion_def or not fusion_def.get("recipe"):
                continue

            validated_assets.append(asset)

        return validated_assets

    def find_crafting_plan(
            self,
            recipe_counter: Counter,
            user_assets: List[dict],
            fusion_id_to_check: str
    ) -> Tuple[Optional[List[dict]], Counter]:
        """
        Determines if a recipe can be crafted and returns the plan and any remaining needed components.
        This function respects the "inseparable unit" rule for fused components.
        If a `fusion_id_to_check` is provided, this function will proactively ignore any
        assets matching that ID before attempting to find a crafting plan.
        It also filters out any fusion plants that lack a valid recipe definition.
        """

        temp_assets = user_assets
        if fusion_id_to_check:
            temp_assets = [asset for asset in user_assets if asset.get("id") != fusion_id_to_check]

        effective_assets = self.get_valid_crafting_components(temp_assets)

        needed = recipe_counter.copy()

        sorted_assets = sorted(
            effective_assets,
            key=lambda x: len(self.deconstruct_plant(x)[0]),
            reverse=True
        )
        plan = []

        for asset in sorted_assets:
            asset_components, errors = self.deconstruct_plant(asset)

            if errors:
                continue

            asset_counter = Counter(asset_components)

            if all(needed.get(item, 0) >= count for item, count in asset_counter.items()):
                needed -= asset_counter
                plan.append(asset)

        remaining_needs = Counter({k: v for k, v in needed.items() if v > 0})

        if not remaining_needs:
            return plan, Counter()

        return None, remaining_needs


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
            sender_data: Dict[str, Any],
            recipient_data: Dict[str, Any],
            sender_unlocked_slots: set
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Validates a plant trade and returns a plan of changes. Does NOT mutate data."""

        if not trade_data:
            return False, "Critical Error: Trade data was missing during execution.", None

        money_to_give = trade_data.get("money_sender_gives", 0)
        plants_info = trade_data.get("plants_sender_receives_info", [])

        if sender_data.get("balance", 0) < money_to_give:
            return False, "Trade failed: Sender no longer has enough sun.", None

        free_sender_plots = sum(
            1 for i, p in enumerate(sender_data.get("garden", [])) if p is None and (i + 1) in sender_unlocked_slots)

        if free_sender_plots < len(plants_info):
            return False, "Trade failed: Sender no longer has enough free garden space.", None

        for plant_snapshot in plants_info:
            r_slot_index = plant_snapshot.get("r_slot_index")
            current_plant_in_slot = recipient_data.get("garden", [])[r_slot_index]
            original_plant_data = plant_snapshot.get("plant_data", {})

            if not isinstance(current_plant_in_slot, dict) or current_plant_in_slot.get(
                    "id") != original_plant_data.get("id"):
                return False, f"Trade failed: The plant in recipient's plot {r_slot_index + 1} has changed.", None

        changes = {
            "balance_updates": [
                {"user_id": trade_data["sender_id"], "amount": -money_to_give},
                {"user_id": trade_data["recipient_id"], "amount": money_to_give},
            ],
            "plant_moves": [],
        }

        temp_sender_garden = list(sender_data.get("garden", []))

        for plant_snapshot in plants_info:
            r_slot_index = plant_snapshot["r_slot_index"]
            plant_to_move = recipient_data["garden"][r_slot_index]

            s_slot_index = next(
                i for i, p in enumerate(temp_sender_garden) if p is None and (i + 1) in sender_unlocked_slots)
            temp_sender_garden[s_slot_index] = plant_to_move

            changes["plant_moves"].append({
                "from_user_id": trade_data["recipient_id"],
                "from_plot_idx": r_slot_index,
                "to_user_id": trade_data["sender_id"],
                "to_plot_idx": s_slot_index,
                "plant_data": plant_to_move
            })

        plant_names = ", ".join([f"**{p['plant_data'].get('name', 'Unknown')}**" for p in plants_info])
        success_message = f"Exchange of **{money_to_give:,}** sun for {plant_names} was successful."

        return True, success_message, changes

    def execute_item_trade(
            self,
            trade_data: Dict[str, Any],
            sender_data: Dict[str, Any],
            recipient_data: Dict[str, Any]
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Validates an item trade and returns a plan of changes. Does NOT mutate data."""

        if not trade_data:
            return False, "Critical Error: Trade data was missing during execution.", None

        sun_to_give = trade_data.get("sun_sender_offers", 0)
        items_info = trade_data.get("items_info_list", [])

        if sender_data.get("balance", 0) < sun_to_give:
            return False, "Trade failed: Sender no longer has enough sun.", None

        recipient_inv_counter = Counter(recipient_data.get("inventory", []))

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


class ShopHelper:
    """Manages the state, stock, and refresh logic for all in-game shops."""

    def __init__(self, all_flags: Dict[str, Any], plant_helper: PlantHelper, penny_shop_catalog: Dict,
                 rux_shop_catalog: Dict, dave_shop_catalog: Dict, materials_catalog: Dict):
        self.flags = all_flags
        self.plant_helper = plant_helper
        self.penny_shop_catalog = penny_shop_catalog
        self.rux_shop_catalog = rux_shop_catalog
        self.dave_shop_catalog = dave_shop_catalog
        self.materials_catalog = materials_catalog

    def get_all_item_definitions(self) -> Dict[str, Any]:
        """Returns a consolidated dictionary of all known items from all shops and materials."""

        all_items = {}
        all_items.update(self.rux_shop_catalog)
        all_items.update(self.penny_shop_catalog)

        for mat_id, mat_name in self.materials_catalog.items():
            if mat_id not in all_items:
                all_items[mat_id] = {"name": mat_name}

        return all_items

    def get_next_penny_refresh_time(self, current_est_time: datetime) -> datetime:
        """Calculates the next scheduled refresh time for Penny's Treasures."""

        interval = self.flags.get("treasure_shop_refresh_interval_hours", 1)
        if not isinstance(interval, int) or interval <= 0 or 24 % interval != 0:
            interval = 1

        refresh_hours = list(range(0, 24, interval))

        for h in refresh_hours:
            refresh_time = current_est_time.replace(hour=h, minute=0, second=0, microsecond=0)
            if current_est_time < refresh_time:
                return refresh_time

        first_refresh_hour_of_day = refresh_hours[0]
        return (current_est_time + timedelta(days=1)).replace(hour=first_refresh_hour_of_day, minute=0, second=0,
                                                              microsecond=0)

    def _generate_new_penny_stock(self) -> List[Dict[str, Any]]:
        """Generates a new random stock for Penny's Treasures."""

        all_penny_items = list(self.penny_shop_catalog.items())
        if not all_penny_items:
            return []

        return [{
            "id": item_id,
            "name": details.get("name", item_id),
            "price": details.get("cost", 999999),
            "stock": 1
        } for item_id, details in all_penny_items]

    async def refresh_penny_shop_if_needed(self, logger: LoggingHelper, force: bool = False):
        """Checks if Penny's shop needs a refresh and performs it."""

        now_est = datetime.now(TimeHelper.EST)
        last_refresh_ts = self.flags.get("last_treasure_shop_refresh")

        needs_refresh = force

        if not needs_refresh and last_refresh_ts is None:
            needs_refresh = True
        elif not needs_refresh:
            last_refresh_dt = datetime.fromtimestamp(last_refresh_ts, tz=TimeHelper.EST)
            next_refresh = self.get_next_penny_refresh_time(last_refresh_dt)
            needs_refresh = now_est >= next_refresh

        if needs_refresh:
            await logger.log_to_discord("Penny's Shop: Refresh triggered.", "INFO")
            self.flags["treasure_shop_stock"] = self._generate_new_penny_stock()
            self.flags["last_treasure_shop_refresh"] = now_est.timestamp()

    def _generate_new_dave_stock(self) -> List[Dict[str, Any]]:
        """Generates the fixed-structure but partially randomized stock for Crazy Dave."""

        final_stock = []
        ids_in_stock = set()

        for item_id, details in self.dave_shop_catalog.items():
            final_stock.append({
                "id": item_id,
                "name": details.get("name", item_id),
                "price": details.get("cost", 0),
                "stock": details.get("stock", 1),
                "type": details.get("type", "material")
            })
            ids_in_stock.add(item_id)

        for seedling_data in self.plant_helper.get_all_seedlings():
            final_stock.append({
                "id": seedling_data["id"],
                "name": seedling_data["id"],
                "price": seedling_data["cost"],
                "stock": seedling_data["stock"],
                "type": "seedling"
            })
            ids_in_stock.add(seedling_data["id"])

        shop_plants = [p for p in self.plant_helper.base_plants if
                       p.get('category') == 'shop' and p['id'] not in ids_in_stock]
        for plant in shop_plants:
            final_stock.append(
                {"id": plant['id'], "name": plant.get('name', plant['id']), "price": 5000, "stock": 1, "type": "plant"})
            ids_in_stock.add(plant['id'])

        all_base_plants = self.plant_helper.base_plants
        eligible_plants = [p for p in all_base_plants if p.get('shop') and p['id'] not in ids_in_stock]

        num_to_add = min(len(eligible_plants), 4)
        if num_to_add > 0:
            for plant in random.sample(eligible_plants, num_to_add):
                final_stock.append(
                    {"id": plant['id'], "name": plant.get('name', plant['id']), "price": 5000, "stock": 1,
                     "type": "plant"})
                ids_in_stock.add(plant['id'])

        return final_stock

    async def refresh_dave_shop_if_needed(self, logger: LoggingHelper, force: bool = False):
        """Checks if Crazy Dave's shop needs its hourly refresh and performs it."""

        now_est = datetime.now(TimeHelper.EST)
        last_refresh_ts = self.flags.get("last_dave_shop_refresh")

        needs_refresh = force
        if not needs_refresh and last_refresh_ts is None:
            needs_refresh = True
        elif not needs_refresh:
            last_refresh_dt = datetime.fromtimestamp(last_refresh_ts, tz=TimeHelper.EST)
            next_refresh = (last_refresh_dt + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            needs_refresh = now_est >= next_refresh

        if needs_refresh:
            await logger.log_to_discord("Dave's Shop: Refresh triggered.", "INFO")
            self.flags["dave_shop_stock"] = self._generate_new_dave_stock()
            self.flags["last_dave_shop_refresh"] = now_est.timestamp()


def is_not_locked():
    """
    A commands.check decorator that fails if the command author is locked.
    Uses the LockHelper to check the user's status.
    """

    async def predicate(ctx: commands.Context):
        if not hasattr(ctx.cog, 'lock_helper'):
            return True

        lock = ctx.cog.lock_helper.get_user_lock(ctx.author.id)
        if lock:
            embed = discord.Embed(
                title=f"❌ Action Locked: Pending {lock.get('type', 'Action').capitalize()}",
                description=f"User {ctx.author.mention}, your actions are locked. Reason:\n\n*_"
                            f"{lock.get('message', 'You are busy with another task.')}_*",
                color=discord.Color.orange()
            )
            embed.set_footer(text="Penny - Global Lock System")
            await ctx.send(embed=embed)
            return False
        return True

    return commands.check(predicate)


def is_cog_ready():
    """
    A commands.check decorator that fails if the cog's main data has not yet been loaded.
    This prevents commands from running during the initial startup sequence.
    """

    async def predicate(ctx: commands.Context):
        if not getattr(ctx.cog, '_initialized', False):
            embed = discord.Embed(
                title="⏳ System Initializing",
                description="Penny's systems are still coming online. Please wait a moment and try your command again.",
                color=discord.Color.orange()
            )
            await ctx.send(embed=embed, delete_after=10)
            return False
        return True

    return commands.check(predicate)


class BackgroundHelper:
    """Manages garden background definitions and user unlocks."""

    def __init__(self, backgrounds_list: List[Dict[str, Any]]):
        self.all_backgrounds = backgrounds_list
        self.backgrounds_by_id = {bg['id']: bg for bg in backgrounds_list}

    def get_background_by_id(self, bg_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a background's definition by its unique ID."""

        return self.backgrounds_by_id.get(bg_id)

    def check_for_unlocks(self, user_fusions: List[str], user_unlocked_bgs: List[str]) -> List[Dict[str, Any]]:
        """Checks all defined backgrounds against a user's discovered fusions."""

        newly_unlocked = []
        user_fusions_set = set(user_fusions)
        user_unlocked_bgs_set = set(user_unlocked_bgs)

        for bg_def in self.all_backgrounds:
            if bg_def['id'] in user_unlocked_bgs_set:
                continue

            required_set = set(bg_def.get("required_fusions", []))
            if required_set and required_set.issubset(user_fusions_set):
                newly_unlocked.append(bg_def)

        return newly_unlocked


class arg(commands.Cog):
    """Penny's Zen Garden Interface - Assist users in managing their Zen Gardens."""

    CURRENCY_EMOJI = "<:Sun:286219730296242186>"
    DISCORD_LOG_CHANNEL_ID = 1379054870312779917
    _DISPLAY_TEXT_GARDEN_IN_PROFILE: bool = False

    def __init__(self, bot: commands.Bot):
        self._initialized = False

        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567892)
        self.config.register_global(users={}, flags={"plant_growth_duration_minutes": 240})

        self.cog_data_path = data_manager.bundled_data_path(self)
        self.lock_helper = LockHelper()
        self.logger = LoggingHelper(bot, self.DISCORD_LOG_CHANNEL_ID)
        self.data_loader = DataHelper(self.cog_data_path, self.logger)

        self.data_loader.load_all_data()

        self.image_helper = ImageHelper(self.cog_data_path, self.logger)
        self.sales_helper = SalesHelper(self.data_loader.sales_prices, self.CURRENCY_EMOJI)
        self.plant_helper = PlantHelper(self.data_loader.base_plants, self.data_loader.seedlings_data)
        self.fusion_helper = FusionHelper(self.data_loader.fusion_plants, self.data_loader.materials_data,
                                          self.plant_helper)
        self.background_helper = BackgroundHelper(self.data_loader.backgrounds_data)
        self.trade_helper = TradeHelper(self.lock_helper)

        self.data: Dict[str, Any] = {"users": {}, "flags": {}}

        self.garden_helper: Optional[GardenHelper] = None
        self.shop_helper: Optional[ShopHelper] = None

        self.image_helper.load_assets()
        self.growth_task = self.bot.loop.create_task(self.startup_and_growth_loop())

    def cog_unload(self):
        """Cog cleanup method."""

        if self.growth_task:
            self.growth_task.cancel()

        self.lock_helper.clear_all_locks()
        self.logger.init_log("Zen Garden cog systems are now offline.", "INFO")

    async def _load_and_initialize_data(self):
        """Handles the initial loading of data from Red's config."""

        await self.logger.log_to_discord("System Startup: Loading data from local Red config.", "INFO")

        self.data = await self.config.all()

        self.data.setdefault("users", {})
        self.data.setdefault("flags", {})

        self.garden_helper = GardenHelper(self.data["users"], self.config)
        self.shop_helper = ShopHelper(
            self.data["flags"],
            self.plant_helper,
            self.data_loader.penny_shop_data,
            self.data_loader.rux_shop_data,
            self.data_loader.dave_shop_data,
            self.data_loader.materials_data
        )

    async def _initialize_global_flags(self):
        """Ensures all necessary global flags are present in the data, setting defaults if not."""

        if self.shop_helper is None:
            return

        flags = self.data["flags"]
        flags_updated = False

        def set_default_flag(key, value):
            nonlocal flags_updated
            if key not in flags:
                flags[key] = value
                flags_updated = True
                self.logger.init_log(f"Global Flags: Initialized '{key}' to '{value}'.", "INFO")

        for item_id, details in self.data_loader.rux_shop_data.items():
            if details.get("category") == "limited":
                set_default_flag(f"{item_id}_stock", details.get("stock", 0))

        set_default_flag("plant_growth_duration_minutes", 240)
        set_default_flag("treasure_shop_refresh_interval_hours", 1)
        set_default_flag("treasure_shop_stock", [])
        set_default_flag("last_treasure_shop_refresh", None)
        set_default_flag("dave_shop_stock", [])
        set_default_flag("last_dave_shop_refresh", None)

        if flags_updated:
            await self.config.flags.set(flags)
            await self.logger.log_to_discord("Global Flags: One or more flags were initialized. Configuration saved.",
                                             "INFO")

    async def startup_and_growth_loop(self):
        """The main background task for the cog."""

        await self.bot.wait_until_ready()
        await self.logger.flush_init_log_queue()
        await self.logger.log_to_discord("Growth Loop: System Online.", "INFO")

        await self._load_and_initialize_data()
        await self._initialize_global_flags()

        await self.shop_helper.refresh_penny_shop_if_needed(self.logger)
        await self.shop_helper.refresh_dave_shop_if_needed(self.logger)

        self._initialized = True

        await self.logger.log_to_discord("Growth Loop: Startup complete. Entering main simulation cycle.", "INFO")
        loop_counter = 0
        while not self.bot.is_closed():
            try:
                loop_start_time = time.monotonic()

                growth_duration = self.data["flags"].get("plant_growth_duration_minutes", 240)
                base_progress = 100.0 / (growth_duration if growth_duration > 0 else 240)

                users_copy = self.data["users"].copy()
                for user_id_str, user_data in users_copy.items():
                    user_id_int = int(user_id_str)
                    time_mastery_bonus = 1 + (user_data.get("time_mastery", 0) * 0.1)

                    for i, slot_data in enumerate(user_data.get("garden", [])):
                        if isinstance(slot_data, dict) and slot_data.get("type") == "seedling":
                            growth_multiplier = 1.0
                            seedling_id = slot_data.get("id")
                            if seedling_def := self.plant_helper.get_seedling_by_id(seedling_id):
                                growth_multiplier = seedling_def.get("growth_multiplier", 1.0)

                            final_progress = base_progress * time_mastery_bonus * growth_multiplier

                            await self.garden_helper.update_seedling_progress(user_id_int, i, final_progress)

                            slot_data_after_update = user_data.get("garden", [])[i]
                            if isinstance(slot_data_after_update, dict) and slot_data_after_update.get("progress",
                                                                                                       0.0) >= 100.0:
                                await self._mature_plant(user_id_int, i, slot_data_after_update)

                await self.shop_helper.refresh_penny_shop_if_needed(self.logger)
                await self.shop_helper.refresh_dave_shop_if_needed(self.logger)

                await self.config.users.set(self.data["users"])
                await self.config.flags.set(self.data["flags"])

                loop_duration = time.monotonic() - loop_start_time
                await self.logger.log_to_discord(
                    f"Growth Loop: Cycle {loop_counter} completed in {loop_duration:.2f}s. Data saved.",
                    "INFO")
            except Exception as e:
                await self.logger.log_to_discord(
                    f"Growth Loop: CRITICAL Anomaly in cycle {loop_counter}: {e}\n{traceback.format_exc()}","CRITICAL")

            loop_counter += 1
            now = datetime.now()
            next_minute_start = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
            target_time = next_minute_start + timedelta(seconds=1)
            wait_seconds = (target_time - now).total_seconds()
            await asyncio.sleep(max(0.1, wait_seconds))

    async def _mature_plant(self, user_id: int, plot_index: int, seedling_data: dict):
        """Handles the logic for when a seedling reaches 100% growth."""

        seedling_id = seedling_data.get("id")

        plant_category = "vanilla"

        if seedling_def := self.plant_helper.get_seedling_by_id(seedling_id):
            plant_category = seedling_def.get("category", "vanilla")

        grown_plant = self.plant_helper.get_random_plant_by_category(plant_category)

        if grown_plant is None:
            await self.logger.log_to_discord(
                f"CRITICAL: Failed to get a plant for category '{plant_category}' for user {user_id}. Maturation "
                f"aborted.",
                "CRITICAL")
            return

        await self.garden_helper.set_garden_plot(user_id, plot_index, grown_plant)

        discord_user = self.bot.get_user(user_id)

        if not discord_user:
            return

        embed = discord.Embed(
            title="🌱 Plant Maturation Complete",
            description=f"Alert, {discord_user.mention}: Your **{seedling_data.get('name', 'Seedling')}** in plot "
                        f"{plot_index + 1} has matured into a **{grown_plant.get('name', grown_plant['id'])}**.",
            color=discord.Color.green()
        )
        embed.set_footer(text="Penny System Monitoring")

        image_file_to_send = self.image_helper.get_image_file_for_plant(grown_plant.get("id"))

        if image_file_to_send:
            embed.set_image(url=f"attachment://{image_file_to_send.filename}")

        notification_channel_id = seedling_data.get("notification_channel_id")
        target_channel = self.bot.get_channel(notification_channel_id) if notification_channel_id else None

        sent_to_channel = False

        if isinstance(target_channel, discord.TextChannel):
            try:
                await target_channel.send(content=discord_user.mention, embed=embed, file=image_file_to_send,
                                          allowed_mentions=discord.AllowedMentions(users=True))
                sent_to_channel = True
            except (discord.Forbidden, discord.HTTPException):
                pass

        if not sent_to_channel:
            try:
                dm_image_file = self.image_helper.get_image_file_for_plant(grown_plant.get("id"))

                if dm_image_file:
                    embed.set_image(url=f"attachment://{dm_image_file.filename}")
                else:
                    embed.set_image(url=None)

                await discord_user.send(embed=embed, file=dm_image_file)
            except (discord.Forbidden, discord.HTTPException):
                pass

    @commands.command(name="profile")
    @is_cog_ready()
    async def profile_command(self, ctx: commands.Context, user: Optional[discord.Member] = None):
        target_user = user or ctx.author

        if user and target_user.id != ctx.author.id:
            if self.lock_helper.get_user_lock(target_user.id):
                profile_lock_embed = discord.Embed(
                    title="⚠️ Target Profile Advisory",
                    description=(f"User {target_user.mention} is currently engaged in a pending action.\n"
                                 f"Their profile data may be subject to imminent change."),
                    color=discord.Color.orange()
                )
                await ctx.send(embed=profile_lock_embed)

        user_data = self.garden_helper.get_user_data(target_user.id)
        rank = self.garden_helper.get_user_rank(target_user.id)
        rank_str = str(rank) if rank is not None else "N/A"

        garden_image_file: Optional[discord.File] = None
        display_text_garden = self._DISPLAY_TEXT_GARDEN_IN_PROFILE

        if not PIL_AVAILABLE:
            display_text_garden = True
        else:
            try:
                active_bg_id = user_data.get("active_background", "default")
                bg_def = self.background_helper.get_background_by_id(active_bg_id)
                bg_filename = f"{bg_def.get('image_file', 'garden')}.png" if bg_def else "garden.png"

                unlocked_slots = {i + 1 for i in range(12) if self.garden_helper.is_slot_unlocked(user_data, i + 1)}
                garden_image_file = await self.image_helper.generate_garden_image(user_data, unlocked_slots,
                                                                                  background_filename=bg_filename)
            except Exception as e:
                await self.logger.log_to_discord(
                    f"Profile image generation failed for {target_user.id}: {e}\n{traceback.format_exc()}", "ERROR")
                await ctx.send("An error occurred while generating the garden image; displaying text fallback.",
                               delete_after=10)
                display_text_garden = True

        embed = discord.Embed(color=discord.Color.blue())
        embed.set_author(name=f"{target_user.display_name}: Zen Garden Dossier",
                         icon_url=target_user.display_avatar.url)

        sun_mastery = user_data.get("mastery", 0)
        time_mastery = user_data.get("time_mastery", 0)

        sun_mastery_display = f"\n**Sun Mastery:** {sun_mastery} ({1 + (0.1 * sun_mastery):.2f}x sell boost)" \
            if sun_mastery > 0 else ""
        time_mastery_display = f"\n**Time Mastery:** {time_mastery} ({1 + (0.1 * time_mastery):.2f}x growth boost)" \
            if time_mastery > 0 else ""

        embed.add_field(
            name="📈 Core Metrics",
            value=f"**Solar Energy Balance:** {user_data.get('balance', 0):,} {self.CURRENCY_EMOJI}\n"
                  f"**Garden User Rank:** #{rank_str}{sun_mastery_display}{time_mastery_display}",
            inline=False
        )

        if display_text_garden:
            col1, col2 = self.garden_helper.get_text_garden_display(user_data)
            embed.add_field(name="🌳 Garden Plots", value=col1, inline=True)
            embed.add_field(name="🌳 Garden Plots", value=col2, inline=True)

        inventory_items = user_data.get("inventory", [])
        inventory_field_value = "No assets acquired."

        if inventory_items:
            all_item_defs = self.shop_helper.get_all_item_definitions()
            inventory_counts = Counter(inventory_items)
            inventory_display = []

            for item_id, count in sorted(inventory_counts.items()):
                item_info = all_item_defs.get(item_id)
                if item_info and item_info.get("category") == "upgrade":
                    continue

                item_name = item_info.get("name", item_id) if item_info else item_id
                inventory_display.append(f"**{item_name}** (`{item_id}`)" + (f" x{count}" if count > 1 else ""))

            if inventory_display:
                inventory_field_value = ", ".join(inventory_display)

        embed.add_field(name="🎒 Acquired Assets", value=inventory_field_value, inline=False)

        if garden_image_file:
            embed.set_image(url=f"attachment://{garden_image_file.filename}")

        embed.set_footer(text="Penny - Data Systems & User Profiling")
        await ctx.send(embed=embed, file=garden_image_file)

    @commands.command(name="daily")
    @is_cog_ready()
    @is_not_locked()
    async def daily_command(self, ctx: commands.Context):
        """Collect your daily solar energy stipend."""

        user_data = self.garden_helper.get_user_data(ctx.author.id)
        current_date_est = TimeHelper.get_est_date()

        if user_data.get("last_daily") == current_date_est:
            now_est = datetime.now(TimeHelper.EST)
            next_reset_est = (now_est + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            unix_ts = int(next_reset_est.timestamp())
            embed = discord.Embed(
                title="❌ Daily Stipend Already Dispensed",
                description=f"User {ctx.author.mention}, system records indicate your daily solar energy stipend of "
                            f"1000 {self.CURRENCY_EMOJI} has already been collected for {current_date_est}.\n "
                            f"Next available collection cycle begins: <t:{unix_ts}:R>.",
                color=discord.Color.red()
            )
            embed.set_footer(text="Penny - Financial Systems Interface")
            await ctx.send(embed=embed)
            return

        await self.garden_helper.add_balance(ctx.author.id, 1000)
        await self.garden_helper.set_last_daily(ctx.author.id, current_date_est)
        user_data = self.garden_helper.get_user_data(ctx.author.id)

        embed = discord.Embed(
            title=f"☀️ Daily Solar Energy Collected",
            description=f"User {ctx.author.mention}, your daily stipend of **1000** {self.CURRENCY_EMOJI} has been "
                        f"successfully credited to your account.\n "
                        f"Your current solar balance is now **{user_data['balance']:,}** {self.CURRENCY_EMOJI}.",
            color=discord.Color.green()
        )
        embed.set_footer(text="Penny - Financial Systems Interface")
        await ctx.send(embed=embed)

    @commands.command(name="plant")
    @is_cog_ready()
    @is_not_locked()
    async def plant_command(self, ctx: commands.Context, *slots_to_plant_in: int):
        """Initiate seedling cultivation in specified garden plots."""

        if not slots_to_plant_in:
            embed = discord.Embed(title="⚠️ Insufficient Parameters for Cultivation",
                                  description=f"User {ctx.author.mention}, please specify target plot numbers for "
                                              f"seedling cultivation.\nSyntax: `{ctx.prefix}plant <plot_num_1> ["
                                              f"plot_num_2] ...`\nExample: `{ctx.prefix}plant 1 2 3`",
                                  color=discord.Color.orange())
            await ctx.send(embed=embed)
            return

        user_data = self.garden_helper.get_user_data(ctx.author.id)
        garden = user_data["garden"]
        cost_per_seedling = 100

        valid_slots_to_plant = []
        error_messages = []

        for slot_num_1based in set(slots_to_plant_in):
            if not (1 <= slot_num_1based <= 12):
                error_messages.append(f"Plot {slot_num_1based}: Invalid designation.")
            elif not self.garden_helper.is_slot_unlocked(user_data, slot_num_1based):
                error_messages.append(f"Plot {slot_num_1based}: Access restricted (Locked).")
            elif garden[slot_num_1based - 1] is not None:
                error_messages.append(f"Plot {slot_num_1based}: Currently occupied.")
            else:
                valid_slots_to_plant.append(slot_num_1based)

        if not valid_slots_to_plant:
            desc = "Cultivation protocol aborted:\n\n" + "\n".join([f"• {msg}" for msg in error_messages])
            embed = discord.Embed(title="❌ Cultivation Protocol Error", description=desc, color=discord.Color.red())
            await ctx.send(embed=embed)
            return

        actual_cost = len(valid_slots_to_plant) * cost_per_seedling

        if user_data["balance"] < actual_cost:
            embed = discord.Embed(title="❌ Insufficient Solar Energy Reserves",
                                  description=f"Cultivation cost for {len(valid_slots_to_plant)} plot(s): "
                                              f"**{actual_cost:,}** {self.CURRENCY_EMOJI}.\n"
                                              f"Your available balance: "
                                              f"**{user_data['balance']:,}** {self.CURRENCY_EMOJI}.",
                                  color=discord.Color.red())
            await ctx.send(embed=embed)
            return

        await self.garden_helper.remove_balance(ctx.author.id, actual_cost)

        for slot_num_1based in valid_slots_to_plant:
            await self.garden_helper.plant_seedling(
                ctx.author.id, slot_num_1based - 1, "Seedling", ctx.channel.id
            )

        user_data = self.garden_helper.get_user_data(ctx.author.id)

        planted_slots_str = ", ".join(map(str, sorted(valid_slots_to_plant)))
        desc = f"Seedling cultivation initiated in plot(s): **{planted_slots_str}**.\n"
        desc += f"Solar energy expended: **{actual_cost:,}** {self.CURRENCY_EMOJI}.\n"
        desc += f"Remaining solar balance: **{user_data['balance']:,}** {self.CURRENCY_EMOJI}."

        if error_messages:
            desc += "\n\n**Advisory:** Some plots were not processed:\n" + "\n".join(
                [f"• {msg}" for msg in error_messages])

        embed = discord.Embed(title="🌱 Seedling Cultivation Initiated", description=desc, color=discord.Color.green())
        await ctx.send(embed=embed)

    @commands.command(name="sell")
    @is_cog_ready()
    @is_not_locked()
    async def sell_command(self, ctx: commands.Context, *slots_to_sell_from: int):
        """Liquidate mature botanical assets from specified plots."""

        if not slots_to_sell_from:
            embed = discord.Embed(title="⚠️ Insufficient Parameters for Liquidation",
                                  description=f"User {ctx.author.mention}, please designate which botanical assets are "
                                              f"to be "f"liquidated from your garden plots.\n"
                                              f"Syntax: `{ctx.prefix}sell <plot_num_1> [plot_num_2] ...`\n"
                                              f"Example: `{ctx.prefix}sell 1 2 3`",
                                  color=discord.Color.orange())
            embed.set_footer(text="Penny - Command Syntax Adherence Module")
            await ctx.send(embed=embed)
            return

        user_data = self.garden_helper.get_user_data(ctx.author.id)

        sale_results = self.sales_helper.process_sales(user_data, slots_to_sell_from)

        total_earnings = sale_results["total_earnings"]
        sold_plants_details = sale_results["sold_plants_details"]
        error_messages = sale_results["error_messages"]
        mastery_gained = sale_results["mastery_gained"]
        time_mastery_gained = sale_results["time_mastery_gained"]
        plots_to_clear = sale_results["plots_to_clear"]

        if not sold_plants_details and not mastery_gained and not time_mastery_gained:
            desc = "The asset liquidation process yielded no successful transactions.\n\n"
            if error_messages:
                desc += "Analysis of encountered issues:\n" + "\n".join([f"• {msg}" for msg in error_messages])
            embed = discord.Embed(title="❌ Liquidation Process Inconclusive", description=desc,
                                  color=discord.Color.red())
            embed.set_footer(text="Penny - Financial Operations Interface")
            await ctx.send(embed=embed)
            return

        if total_earnings > 0:
            await self.garden_helper.add_balance(ctx.author.id, total_earnings)

        if mastery_gained > 0:
            await self.garden_helper.increment_mastery(ctx.author.id, mastery_gained)

        if time_mastery_gained > 0:
            await self.garden_helper.increment_time_mastery(ctx.author.id, time_mastery_gained)

        for plot_idx_0based in plots_to_clear:
            await self.garden_helper.set_garden_plot(ctx.author.id, plot_idx_0based, None)

        user_data = self.garden_helper.get_user_data(ctx.author.id)

        desc = f"User {ctx.author.mention}, asset liquidation protocol executed successfully.\n\n"

        if sold_plants_details:
            desc += "**Liquidated Assets & Yields:**\n" + "\n".join([f"• {detail}" for detail in sold_plants_details])

        if mastery_gained > 0:
            desc += f"\n\n**Your Sun Mastery has increased by {mastery_gained} to a new level of" \
                    f"{user_data.get('mastery', 0)}!**"

        if time_mastery_gained > 0:
            desc += f"\n\n**Your Time Mastery has increased by {time_mastery_gained} to a new level of" \
                    f"{user_data.get('time_mastery', 0)}!**"

        if total_earnings > 0:
            desc += f"\n\n**Total Solar Energy Acquired from Transaction:** {total_earnings:,} {self.CURRENCY_EMOJI}"

        desc += f"\n**Updated Solar Balance:** {user_data['balance']:,} {self.CURRENCY_EMOJI}"

        if error_messages:
            desc += "\n\n**System Advisory:** Note that some assets could not be liquidated due to the following" \
                    "issues:\n" + "\n".join([f"• {msg}" for msg in error_messages])

        embed = discord.Embed(title="💰 Asset Liquidation Complete", description=desc, color=discord.Color.green())
        embed.set_footer(text="Penny - Financial Operations Interface")
        await ctx.send(embed=embed)

    @commands.command(name="shovel")
    @is_cog_ready()
    @is_not_locked()
    async def shovel_command(self, ctx: commands.Context, *slots_to_clear: int):
        """Clear plots of immature seedlings. No sun is awarded. This command cannot remove mature plants."""

        if not slots_to_clear:
            embed = discord.Embed(
                title="⚠️ Insufficient Parameters for Plot Clearing",
                description=f"User {ctx.author.mention}, please specify target plot numbers for clearing.\nSyntax: "
                            f"`{ctx.prefix}shovel <plot_num_1> [plot_num_2] ...`\nExample: `{ctx.prefix}shovel 1 2 3`",
                color=discord.Color.orange()
            )
            embed.set_footer(text="Penny - Command Syntax Adherence Module")
            await ctx.send(embed=embed)
            return

        user_data = self.garden_helper.get_user_data(ctx.author.id)
        cleared_slots_details = []
        error_messages = []

        for slot_num_1based in set(slots_to_clear):
            plot_idx_0based = slot_num_1based - 1

            if not (0 <= plot_idx_0based < 12):
                error_messages.append(f"Plot {slot_num_1based}: Invalid designation.")
            elif not self.garden_helper.is_slot_unlocked(user_data, slot_num_1based):
                error_messages.append(f"Plot {slot_num_1based}: Access restricted (Locked).")
            else:
                occupant = user_data["garden"][plot_idx_0based]

                if occupant is None:
                    error_messages.append(f"Plot {slot_num_1based}: Already unoccupied.")
                elif not isinstance(occupant, dict) or occupant.get("type") != "seedling":
                    plant_name = occupant.get("name", "This asset") if isinstance(occupant, dict) else "This asset"
                    error_messages.append(
                        f"Plot {slot_num_1based}: Contains a mature plant (**{plant_name}**). Use `{ctx.prefix}sell` "
                        f"instead.")
                else:
                    occupant_name = occupant.get("name", "Unidentified Occupant")
                    cleared_slots_details.append(f"Plot {slot_num_1based} (previously contained **{occupant_name}**)")

                await self.garden_helper.set_garden_plot(ctx.author.id, plot_idx_0based, None)

        if not cleared_slots_details:
            desc = "The plot clearing operation yielded no changes.\n\n"
            if error_messages:
                desc += "Analysis of encountered issues:\n" + "\n".join([f"• {msg}" for msg in error_messages])
            embed = discord.Embed(title="❌ Plot Clearing Operation Inconclusive", description=desc,
                                  color=discord.Color.red())
            embed.set_footer(text="Penny - Garden Maintenance Subroutine")
            await ctx.send(embed=embed)
            return

        desc = f"User {ctx.author.mention}, plot clearing operation has been successfully executed.\n\n"
        desc += "**Plots Cleared of Occupants:**\n" + "\n".join([f"• {detail}" for detail in cleared_slots_details])

        if error_messages:
            desc += "\n\n**System Advisory:** Some plots could not be cleared:\n" + "\n".join(
                [f"• {msg}" for msg in error_messages])

        embed = discord.Embed(title="🛠️ Plot Clearing Operation Complete", description=desc, color=discord.Color.blue())
        embed.set_footer(text="Penny - Garden Maintenance Subroutine")
        await ctx.send(embed=embed)

    @commands.command(name="reorder")
    @is_cog_ready()
    @is_not_locked()
    async def reorder_command(self, ctx: commands.Context, *new_order_str: str):
        """Reconfigure the physical arrangement of plants within unlocked garden plots."""

        user_data = self.garden_helper.get_user_data(ctx.author.id)
        garden = user_data["garden"]
        num_garden_slots = len(garden)

        if not new_order_str:
            embed = discord.Embed(title="⚠️ Insufficient Parameters for Garden Reconfiguration",
                                  description=(
                                      f"User {ctx.author.mention}, to reconfigure your garden, please provide the "
                                      f"desired new sequence of your current plot occupants. Specify the *current* plot"
                                      f"numbers (1-12) in the new order you want them for your **unlocked** plots.\n\n "
                                      f"**Syntax:** `{ctx.prefix}reorder <current_plot_num_for_new_pos1> "
                                      f"<current_plot_num_for_new_pos2> ...`\n "
                                      f"**Example (if plots 1-6 are unlocked):** To swap plants in plot 1 and 2, and "
                                      f"keep 3-6 the same: `{ctx.prefix}reorder 2 1 3 4 5 6`"),
                                  color=discord.Color.orange())
            embed.set_footer(text="Penny - Command Syntax Adherence Module")
            await ctx.send(embed=embed)
            return

        try:
            new_order_original_slots_1_indexed = [int(slot) for slot in new_order_str]
        except ValueError:
            embed = discord.Embed(title="❌ Invalid Plot Designators for Reconfiguration",
                                  description=f"User {ctx.author.mention}, plot designators must be numerical values "
                                              f"corresponding to your current garden plots (e.g., 1, 2, 3...).",
                                  color=discord.Color.red())
            embed.set_footer(text="Penny - Input Validation Error")
            await ctx.send(embed=embed)
            return

        unlocked_slot_indices_0based = sorted(
            [i for i in range(num_garden_slots) if self.garden_helper.is_slot_unlocked(user_data, i + 1)])
        num_unlocked_slots = len(unlocked_slot_indices_0based)

        if len(new_order_original_slots_1_indexed) != num_unlocked_slots:
            embed = discord.Embed(title="❌ Plot Sequence Count Mismatch for Reconfiguration",
                                  description=(
                                      f"User {ctx.author.mention}, the number of plot designators provided"
                                      f"({len(new_order_original_slots_1_indexed)}) "
                                      f"does not match your current number of unlocked plots ({num_unlocked_slots}).\n"
                                      f"Please list the current plot numbers of items from your **{num_unlocked_slots}"
                                      f"unlocked plots only**, in the new sequence."),
                                  color=discord.Color.red())
            embed.set_footer(text="Penny - Input Validation Error")
            await ctx.send(embed=embed)
            return

        errors: List[str] = []
        source_slots_for_new_order_0_indexed: List[int] = []
        seen_original_slots_0_indexed_in_input: set[int] = set()

        for original_slot_1_indexed in new_order_original_slots_1_indexed:
            original_slot_0_indexed = original_slot_1_indexed - 1

            if not (0 <= original_slot_0_indexed < num_garden_slots):
                errors.append(
                    f"Specified original plot `{original_slot_1_indexed}` is out of range (1-{num_garden_slots}).")
            elif original_slot_0_indexed not in unlocked_slot_indices_0based:
                errors.append(
                    f"Specified original plot `{original_slot_1_indexed}` is locked. Only contents of unlocked plots "
                    f"can be reordered.")
            elif original_slot_0_indexed in seen_original_slots_0_indexed_in_input:
                errors.append(
                    f"Original plot `{original_slot_1_indexed}` specified multiple times. Each unlocked plot's "
                    f"content must be sourced once.")
            else:
                seen_original_slots_0_indexed_in_input.add(original_slot_0_indexed)
                source_slots_for_new_order_0_indexed.append(original_slot_0_indexed)

        for unlocked_idx_0based in unlocked_slot_indices_0based:
            if unlocked_idx_0based not in seen_original_slots_0_indexed_in_input:
                errors.append(
                    f"The content of your unlocked plot `{unlocked_idx_0based + 1}` was not included in your reorder "
                    f"sequence.")

        if errors:
            error_list_str = "\n".join([f"• {e}" for e in errors])
            embed = discord.Embed(title="❌ Reconfiguration Logic Error Detected",
                                  description=(f"User {ctx.author.mention}, garden reconfiguration failed:\n\n"
                                               f"{error_list_str}"),
                                  color=discord.Color.red())
            embed.set_footer(text="Penny - Spatial Arrangement Subroutine Error")
            await ctx.send(embed=embed)
            return

        temp_new_garden_unlocked_contents = [garden[src_idx] for src_idx in source_slots_for_new_order_0_indexed]
        new_full_garden_state = list(garden)

        for i, dest_idx_0based in enumerate(unlocked_slot_indices_0based):
            new_full_garden_state[dest_idx_0based] = temp_new_garden_unlocked_contents[i]

        await self.garden_helper.set_full_garden(ctx.author.id, new_full_garden_state)

        embed = discord.Embed(title="✅ Garden Matrix Reconfigured Successfully",
                              description=f"User {ctx.author.mention}, your Zen Garden plot arrangement has been "
                                          f"updated. Verify with `{ctx.prefix}profile`.",
                              color=discord.Color.green())
        embed.set_footer(text="Penny - Spatial Arrangement Subroutine")
        await ctx.send(embed=embed)

    @commands.command(name="leaderboard")
    @is_cog_ready()
    async def leaderboard_command(self, ctx: commands.Context, page: int = 1):
        """Display rankings of Zen Garden users by solar energy reserves."""

        sorted_users = self.garden_helper.get_sorted_leaderboard()

        if not sorted_users:
            await ctx.send("There is no user data to display on the leaderboard yet.")
            return

        items_per_page = 10
        total_pages = max(1, (len(sorted_users) + items_per_page - 1) // items_per_page)
        page = max(1, min(page, total_pages))
        start_index = (page - 1) * items_per_page

        page_entries = sorted_users[start_index: start_index + items_per_page]

        if not page_entries:
            await ctx.send(f"There are no entries on page {page}.")
            return

        lb_lines = []
        medals = ["🥇", "🥈", "🥉"]

        for i, user_entry in enumerate(page_entries):
            rank = start_index + i + 1
            user_id = int(user_entry["user_id"])
            user_obj = self.bot.get_user(user_id)
            display_name = user_obj.display_name if user_obj else f"User {user_id}"
            escaped_name = discord.utils.escape_markdown(display_name)

            medal = medals[rank - 1] if rank <= 3 and page == 1 else "▫️"
            lb_lines.append(f"{medal} **#{rank}** {escaped_name}: {user_entry['balance']:,} {self.CURRENCY_EMOJI}")

        embed = discord.Embed(
            title=f"📊 Zen Garden User Rankings (Page {page}/{total_pages})",
            description="\n".join(lb_lines),
            color=discord.Color.green()
        )
        embed.set_footer(text=f"Use {ctx.prefix}leaderboard [page_num] to navigate.")
        await ctx.send(embed=embed)

    @commands.command(name="gardenhelp")
    @is_cog_ready()
    async def gardenhelp_command(self, ctx: commands.Context):
        """Display Penny's Zen Garden command manifest."""

        prefix = ctx.prefix
        embed = discord.Embed(title="⚙️ Penny's Zen Garden - Command Manifest",
                              description=f"Greetings, User {ctx.author.mention}! Welcome to the Zen Garden "
                                          f"interface. Below is a list of available commands.",
                              color=discord.Color.teal())

        if bot_avatar_url := getattr(self.bot.user, 'display_avatar', None):
            embed.set_thumbnail(url=bot_avatar_url.url)

        embed.add_field(name="🌱 Core Garden Operations", inline=False, value=(
            f"▫️ `{prefix}daily` - Collect your daily stipend of 1000 {self.CURRENCY_EMOJI}.\n"
            f"▫️ `{prefix}plant <plot...>` - Plant seedlings in specified plots.\n"
            f"▫️ `{prefix}sell <plot...>` - Liquidate mature plants from specified plots.\n"
            f"▫️ `{prefix}shovel <plot...>` - Clear plots of any occupants (no {self.CURRENCY_EMOJI} awarded).\n"
            f"▫️ `{prefix}profile [@user]` - View your Zen Garden profile or another's.\n"
            f"▫️ `{prefix}reorder <order...>` - Rearrange plants within your unlocked plots."
        ))
        embed.add_field(name="🔬 Fusion & Discovery", inline=False, value=(
            f"▫️ `{prefix}fuse <plot/item...>` - Fuse plants and/or materials to create advanced specimens.\n"
            f"▫️ `{prefix}almanac` - View your list of discovered fusions.\n"
            f"▫️ `{prefix}almanac info <name>` - Get detailed info for a discovered fusion.\n"
            f"▫️ `{prefix}almanac available [filters]` - Check for fusions you can make right now.\n"
            f"▫️ `{prefix}almanac discover [filters]` - See potential undiscovered recipes.\n"
        ))
        embed.add_field(name="🛒 Shops", inline=False, value=(
            f"▫️ `{prefix}ruxshop` - Browse Rux's Bazaar for upgrades and rare goods.\n"
            f"▫️ `{prefix}ruxbuy <item_id>` - Purchase an item from Rux's Bazaar.\n"
            f"▫️ `{prefix}pennyshop` - View Penny's exclusive, rotating collection of materials.\n"
            f"▫️ `{prefix}pennybuy <item_id>` - Purchase a material from Penny's Treasures.\n"
            f"▫️ `{prefix}daveshop` - Browse Crazy Dave's selection of plants and goods.\n"
            f"▫️ `{prefix}davebuy <item_id>` - Purchase an item from Crazy Dave."
        ))
        embed.add_field(name="🤝 Asset Exchange", inline=False, value=(
            f"▫️ `{prefix}trade @user <sun> <plot...>` - Propose a trade for another user's plants.\n"
            f"▫️ `{prefix}tradeitem @user <sun> <item...>` - Propose to buy one or more of a user's materials.\n"
            f"▫️ `{prefix}accept <id>` - Accept a pending asset exchange proposal.\n"
            f"▫️ `{prefix}decline <id>` - Decline a proposal or cancel one you initiated."
        ))
        embed.add_field(name="📦 Storage Shed Operations", inline=False, value=(
            f"▫️ `{prefix}storage [@user]` - View your storage shed.\n"
            f"▫️ `{prefix}store <plot...>` - Move mature plants from garden plots to storage.\n"
            f"▫️ `{prefix}unstore <slot...>` - Move plants from storage back to your garden."
        ))
        embed.add_field(name="📊 System & Information", inline=False, value=(
            f"▫️ `{prefix}leaderboard [page]` - View user rankings by solar energy.\n"
            f"▫️ `{prefix}background [set] <name>` - View and set your unlocked garden backgrounds.\n"
            f"▫️ `{prefix}gardenhelp` - Display this command manifest."
        ))

        current_growth_duration = self.data["flags"].get("plant_growth_duration_minutes", 240)
        hours, minutes = divmod(current_growth_duration, 60)
        duration_str = f"{hours} hour{'s' if hours != 1 else ''}" if hours > 0 else ""
        if minutes > 0:
            duration_str += f"{' and ' if hours > 0 else ''}{minutes} minute{'s' if minutes != 1 else ''}"

        embed.set_footer(text=f"Seedling maturation cycle is {duration_str if duration_str else '4 hours'}.")
        await ctx.send(embed=embed)

    @commands.command(name="ruxshop")
    @is_cog_ready()
    async def ruxshop_command(self, ctx: commands.Context, page: int = 1):
        """Access Rux's Bazaar for upgrades and rare goods."""

        user_data = self.garden_helper.get_user_data(ctx.author.id)
        user_inventory = user_data.get("inventory", [])

        if not self.data_loader.rux_shop_data:
            embed = discord.Embed(title="🛒 Rux's Bazaar",
                                  description="The Bazaar is... empty. Rux must be on a supply run. Try again later, "
                                              "buddy.",
                                  color=discord.Color.orange())
            embed.set_footer(text="Penny - Inventory Systems Offline")
            await ctx.send(embed=embed)
            return

        eligible_items_for_display = []
        sorted_shop_items = sorted(self.data_loader.rux_shop_data.items(),
                                   key=lambda item: (item[1].get("category", "zzz"), item[1].get("cost", 0)))

        for item_id, item_details in sorted_shop_items:
            if not isinstance(item_details, dict):
                continue

            is_limited = item_details.get("category") == "limited"
            is_owned = item_id in user_inventory

            if is_owned and not is_limited:
                continue

            if any(req not in user_inventory for req in item_details.get("requirements", [])):
                continue

            stock = self.data["flags"].get(f"{item_id}_stock", 0)

            if is_limited and stock <= 0 and not is_owned:
                continue

            eligible_items_for_display.append((item_id, item_details))

        if not eligible_items_for_display:
            shop_content = "Looks like you've bought everything I've got for sale, pal. Or maybe you're not ready " \
                           "for my best stuff yet. Come back later! "
        else:
            items_per_page = 5
            total_pages = max(1, (len(eligible_items_for_display) + items_per_page - 1) // items_per_page)
            page = max(1, min(page, total_pages))
            start_index = (page - 1) * items_per_page
            page_items = eligible_items_for_display[start_index: start_index + items_per_page]

            shop_content_parts = []
            for item_id, details in page_items:
                name = details.get("name", item_id)
                cost = details.get("cost", 0)
                description = details.get("description", "No description available.")

                item_entry = f"**{name}** (`{item_id}`)\nCost: **{cost:,}** {self.CURRENCY_EMOJI}"
                if details.get("category") == "limited":
                    stock = self.data["flags"].get(f"{item_id}_stock", "N/A")
                    if item_id in user_inventory:
                        item_entry += " (**Acquired** - Max 1)"
                    else:
                        item_entry += f" (Stock: **{stock}**)"
                item_entry += f"\n-# {description}"
                shop_content_parts.append(item_entry)

            shop_content = "\n\n".join(shop_content_parts)

        embed = discord.Embed(
            title="🛒 Rux's Bazaar",
            description=f"Hey, {ctx.author.mention}.\n\n"
                        f"**Your Current Solar Energy Balance:** {user_data.get('balance', 0):,} "
                        f"{self.CURRENCY_EMOJI}\n\n"
                        f"**Available Items for Procurement:**\n{shop_content}",
            color=discord.Color.teal()
        )
        footer_text = f"To procure an item: {ctx.prefix}ruxbuy <item_id>"
        if len(eligible_items_for_display) > 5:
            footer_text += f"  •  Use {ctx.prefix}ruxshop [page_num] to navigate."
        embed.set_footer(text=footer_text)
        await ctx.send(embed=embed)

    @commands.command(name="ruxbuy")
    @is_cog_ready()
    @is_not_locked()
    async def ruxbuy_command(self, ctx: commands.Context, item_id_to_buy: str):
        """Procure an item from Rux's Bazaar."""

        user_data = self.garden_helper.get_user_data(ctx.author.id)

        item_id_lower = item_id_to_buy.lower()
        actual_item_key = next((k for k in self.data_loader.rux_shop_data if k.lower() == item_id_lower), None)
        item_details = self.data_loader.rux_shop_data.get(actual_item_key)

        if not actual_item_key or not item_details:
            embed = discord.Embed(title="❌ Item Not in Bazaar",
                                  description=f"Rux says: '{item_id_to_buy}'? Never heard of it. Check your spelling "
                                              f"or use `{ctx.prefix}ruxshop` to see what I've got.",
                                  color=discord.Color.red())
            await ctx.send(embed=embed)
            return

        item_name = item_details.get('name', actual_item_key)
        if item_details.get("category") != "limited" and actual_item_key in user_data["inventory"]:
            embed = discord.Embed(title="❌ Already Acquired",
                                  description=f"Rux says: You've already got the **{item_name}**. I don't do returns "
                                              f"or duplicates!",
                                  color=discord.Color.red())
            await ctx.send(embed=embed)
            return

        cost = item_details.get("cost", 0)
        if user_data["balance"] < cost:
            embed = discord.Embed(title="❌ Insufficient Solar Energy",
                                  description=f"Rux says: To get the **{item_name}**, you need **{cost:,}** "
                                              f"{self.CURRENCY_EMOJI}. You only have **{user_data['balance']:,}** "
                                              f"{self.CURRENCY_EMOJI}.",
                                  color=discord.Color.red())
            await ctx.send(embed=embed)
            return

        missing_reqs = [req for req in item_details.get("requirements", []) if req not in user_data["inventory"]]
        if missing_reqs:
            missing_reqs_names = [f"`{self.data_loader.rux_shop_data.get(req, {}).get('name', req)}`" for req in
                                  missing_reqs]
            embed = discord.Embed(title="❌ Prerequisites Not Met",
                                  description=f"Rux says: You can't buy the **{item_name}** yet. You need to get these "
                                              f"first: {', '.join(missing_reqs_names)}.",
                                  color=discord.Color.red())
            await ctx.send(embed=embed)
            return

        if item_details.get("category") == "limited":
            stock_key = f"{actual_item_key}_stock"
            if self.data["flags"].get(stock_key, 0) <= 0:
                embed = discord.Embed(title="❌ Item Out of Stock",
                                      description=f"Rux says: The **{item_name}** is all sold out! Should've been "
                                                  f"quicker, pal.",
                                      color=discord.Color.red())
                await ctx.send(embed=embed)
                return

        await self.garden_helper.remove_balance(ctx.author.id, cost)
        await self.garden_helper.add_item_to_inventory(ctx.author.id, actual_item_key)

        success_desc = f"Rux says: A deal's a deal! The **{item_name}** is all yours, pal.\n\n"
        user_data = self.garden_helper.get_user_data(ctx.author.id)
        success_desc += f"Sun debited: **{cost:,}** {self.CURRENCY_EMOJI}.\n"
        success_desc += f"New balance: **{user_data['balance']:,}** {self.CURRENCY_EMOJI}."

        if item_details.get("category") == "limited":
            stock_key = f"{actual_item_key}_stock"
            self.data["flags"][stock_key] -= 1
            await self.config.flags.set(self.data["flags"])
            success_desc += f"\nThis was a limited item. Stock remaining: **{self.data['flags'].get(stock_key, 0)}**."

        embed = discord.Embed(title="🛒 Deal's a Deal!", description=success_desc, color=discord.Color.green())
        embed.set_footer(text="Penny - Procurement Division")
        await ctx.send(embed=embed)

    @commands.command(name="pennyshop")
    @is_cog_ready()
    async def pennyshop_command(self, ctx: commands.Context):
        """Displays the current stock of Penny's exclusive treasures."""
        current_stock = self.data["flags"].get("treasure_shop_stock", [])
        next_refresh = self.shop_helper.get_next_penny_refresh_time(datetime.now(TimeHelper.EST))

        embed = discord.Embed(
            title="💎 Penny's Treasures 💎",
            description=f"A curated collection of rare and invaluable artifacts. Stock is limited and rotates "
                        f"periodically.\nNext refresh: <t:{int(next_refresh.timestamp())}:R>",
            color=discord.Color.purple()
        )

        if not current_stock:
            embed.description += "\n\nPenny is currently restocking her treasures. Please check back later!"
        else:
            display_items = []
            for item in current_stock:
                if item.get("stock", 0) > 0:
                    display_items.append(
                        f"**{item.get('name', 'N/A')}** (`{item.get('id', 'N/A')}`)\n"
                        f"Price: **{item.get('price', 0):,}** {self.CURRENCY_EMOJI} • Stock: **1**"
                    )

            if not display_items:
                embed.add_field(name="Current Wares", value="All treasures for this rotation have been procured!",
                                inline=False)
            else:
                midpoint = (len(display_items) + 1) // 2
                embed.add_field(name="Current Wares", value="\n\n".join(display_items[:midpoint]), inline=True)
                embed.add_field(name="\u200b", value="\n\n".join(display_items[midpoint:]), inline=True)

        embed.set_footer(text=f"Use {ctx.prefix}pennybuy <item_id> to purchase")
        await ctx.send(embed=embed)

    @commands.command(name="pennybuy")
    @is_cog_ready()
    @is_not_locked()
    async def pennybuy_command(self, ctx: commands.Context, *, item_id: str):
        """Purchase an item from Penny's Treasures."""

        user_data = self.garden_helper.get_user_data(ctx.author.id)
        shop_stock = self.data["flags"].get("treasure_shop_stock", [])

        item_to_buy, item_index = None, -1

        for i, item in enumerate(shop_stock):
            if item.get("id", "").lower() == item_id.lower() and item.get("stock", 0) > 0:
                item_to_buy, item_index = item, i
                break

        if not item_to_buy:
            embed = discord.Embed(title="❌ Item Not Available",
                                  description=f"The item `{item_id}` is not currently available in Penny's Treasures.",
                                  color=discord.Color.red())
            await ctx.send(embed=embed)
            return

        price = item_to_buy.get("price", 9999999)
        if user_data["balance"] < price:
            embed = discord.Embed(title="❌ Insufficient Solar Energy",
                                  description=f"You require **{price:,}** {self.CURRENCY_EMOJI} to procure this "
                                              f"treasure, but your available balance is only "
                                              f"**{user_data['balance']:,}**.",
                                  color=discord.Color.red())
            await ctx.send(embed=embed)
            return

        await self.garden_helper.remove_balance(ctx.author.id, price)
        await self.garden_helper.add_item_to_inventory(ctx.author.id, item_to_buy["id"])
        self.data["flags"]["treasure_shop_stock"][item_index]["stock"] = 0

        await self.config.flags.set(self.data["flags"])
        user_data = self.garden_helper.get_user_data(ctx.author.id)

        embed = discord.Embed(
            title="✅ Treasure Procured!",
            description=f"You have successfully acquired the **{item_to_buy.get('name')}** for **{price:,}** "
                        f"{self.CURRENCY_EMOJI}.\nYour new balance is **{user_data['balance']:,}** "
                        f"{self.CURRENCY_EMOJI}.",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)

    @commands.command(name="daveshop")
    @is_cog_ready()
    async def daveshop_command(self, ctx: commands.Context):
        """Displays Crazy Dave's Twiddydinkies."""

        stock = self.data["flags"].get("dave_shop_stock", [])
        last_refresh_ts = self.data["flags"].get("last_dave_shop_refresh", time.time())
        next_refresh = (datetime.fromtimestamp(last_refresh_ts, tz=TimeHelper.EST) + timedelta(hours=1)).replace(
            minute=0, second=0, microsecond=0)

        embed = discord.Embed(
            title="🌱 Crazy Dave's Twiddydinkies",
            description=f"WAABBI WABBO WOO! I'M CRAAAAZY DAVE! But you can call me Crazy Dave. Here's some stuff I "
                        f"found in my car!\nNext restock: <t:{int(next_refresh.timestamp())}:R>",
            color=discord.Color.from_rgb(139, 69, 19)
        )

        if not stock:
            embed.description += "\n\nI'm all out of twiddydinkies! Come back later, neighbor!"
        else:
            display_items = []
            for item in stock:
                if item.get("stock", 0) > 0:
                    display_items.append(
                        f"**{item.get('name')}** (`{item.get('id')}`)\n"
                        f"Price: **{item.get('price', 0):,}** {self.CURRENCY_EMOJI} • Stock: **{item.get('stock')}**"
                    )

            if display_items:
                midpoint = (len(display_items) + 1) // 2
                embed.add_field(name="Wares", value="\n\n".join(display_items[:midpoint]), inline=True)
                embed.add_field(name="\u200b", value="\n\n".join(display_items[midpoint:]), inline=True)
            else:
                embed.add_field(name="Wares", value="Looks like you bought everything! Because I'm CRAAAAZY!",
                                inline=False)

        embed.set_footer(text=f"Use {ctx.prefix}davebuy <item_id> to purchase")
        await ctx.send(embed=embed)

    @commands.command(name="davebuy")
    @is_cog_ready()
    @is_not_locked()
    async def davebuy_command(self, ctx: commands.Context, *, item_id: str):
        """Purchase an item from Crazy Dave's Twiddydinkies."""

        user_data = self.garden_helper.get_user_data(ctx.author.id)
        shop_stock = self.data["flags"].get("dave_shop_stock", [])

        item_to_buy = None
        item_index = -1
        for i, item in enumerate(shop_stock):
            if item.get("id", "").lower() == item_id.lower():
                item_to_buy = item
                item_index = i
                break

        if not item_to_buy:
            await ctx.send(embed=discord.Embed(title="❌ Item Not Found",
                                               description=f"Dave says: I don't have any `{item_id}`! Are you sure "
                                                           f"that's not a taco?",
                                               color=discord.Color.red()))
            return

        if item_to_buy.get("stock", 0) <= 0:
            await ctx.send(embed=discord.Embed(title="❌ Out of Stock",
                                               description=f"Dave says: All the **{item_to_buy.get('name')}** are "
                                                           f"gone! You gotta be quicker than that, neighbor!",
                                               color=discord.Color.red()))
            return

        price = item_to_buy.get("price", 9999999)
        if user_data["balance"] < price:
            await ctx.send(embed=discord.Embed(title="❌ Insufficient Funds",
                                               description=f"You need **{price:,}** {self.CURRENCY_EMOJI} for this "
                                                           f"twiddydinky! You only have {user_data['balance']:,}.",
                                               color=discord.Color.red()))
            return

        item_type = item_to_buy.get("type")

        if item_type in ["plant", "seedling"]:
            first_empty_slot = next((i for i, s in enumerate(user_data["garden"]) if
                                     self.garden_helper.is_slot_unlocked(user_data, i + 1) and s is None), -1)

            if item_type == "seedling":
                await self.garden_helper.plant_seedling(ctx.author.id, first_empty_slot, item_to_buy["id"],
                                                        ctx.channel.id)
            else:
                plant_def = self.plant_helper.get_base_plant_by_id(item_to_buy["id"])
                await self.garden_helper.set_garden_plot(ctx.author.id, first_empty_slot, plant_def.copy())

        elif item_type == "material":
            await self.garden_helper.add_item_to_inventory(ctx.author.id, item_to_buy["id"])

        await self.garden_helper.remove_balance(ctx.author.id, price)
        self.data["flags"]["dave_shop_stock"][item_index]["stock"] -= 1
        await self.config.flags.set(self.data["flags"])

        await ctx.send(embed=discord.Embed(
            title="✅ Purchase Successful!",
            description=f"You have successfully purchased **{item_to_buy.get('name')}** for **{price:,}** "
                        f"{self.CURRENCY_EMOJI}.",
            color=discord.Color.green()
        ))

    @commands.command(name="storage")
    @is_cog_ready()
    async def storage_command(self, ctx: commands.Context, user: Optional[discord.Member] = None):
        """Displays the contents of your storage shed or that of another user."""

        target_user = user or ctx.author
        user_data = self.garden_helper.get_user_data(target_user.id)

        if not self.garden_helper.user_has_storage_shed(user_data):
            user_display = "You do" if target_user == ctx.author else f"User {target_user.mention} does"
            embed = discord.Embed(
                title="🔒 Storage Shed Inaccessible",
                description=f"{user_display} not currently possess a Storage Shed. It can be acquired from the "
                            f"`{ctx.prefix}ruxshop`.",
                color=discord.Color.orange()
            )
            embed.set_footer(text="Penny - Asset Management Systems")
            await ctx.send(embed=embed)
            return

        display_lines, occupied_slots, capacity = self.garden_helper.get_formatted_storage_contents(user_data)

        embed = discord.Embed(
            title=f"📦 {target_user.display_name}'s Storage Shed Inventory",
            description=f"Displaying current botanical asset storage for {target_user.mention}.\nCapacity: "
                        f"**{occupied_slots}/{capacity}** slots utilized.",
            color=discord.Color.dark_teal()
        )

        if occupied_slots == 0:
            embed.description += "\n\nThis storage shed is currently empty."
        else:
            col1_limit = 4
            col1 = "\n".join(display_lines[:col1_limit])
            col2 = "\n".join(display_lines[col1_limit:])

            embed.add_field(name="Shed Slots 1-4", value=col1, inline=True)
            if capacity > 4:
                embed.add_field(name="Shed Slots 5-8", value=col2 if col2 else "All empty.", inline=True)

        footer_text = "Penny - Asset Management Systems"
        if target_user == ctx.author:
            footer_text += f" • Use {ctx.prefix}store & {ctx.prefix}unstore"
        embed.set_footer(text=footer_text)
        await ctx.send(embed=embed)

    @commands.command(name="store")
    @is_cog_ready()
    @is_not_locked()
    async def store_command(self, ctx: commands.Context, *plot_numbers: int):
        """Moves plants from specified garden plots into your storage shed."""

        user_data = self.garden_helper.get_user_data(ctx.author.id)

        if not self.garden_helper.user_has_storage_shed(user_data):
            embed = discord.Embed(
                title="🔒 Storage Shed Inaccessible",
                description=f"User {ctx.author.mention}, you do not currently possess a Storage Shed. "
                            f"It can be acquired from `{ctx.prefix}ruxshop`.",
                color=discord.Color.orange()
            )
            await ctx.send(embed=embed)
            return

        if not plot_numbers:
            embed = discord.Embed(
                title="⚠️ Insufficient Parameters for Storage Transfer",
                description=f"User {ctx.author.mention}, please specify the garden plot numbers containing the plants "
                            f"you wish to move to storage.\nSyntax: `{ctx.prefix}store <plot_num_1> [plot_num_2] ...`",
                color=discord.Color.orange()
            )
            await ctx.send(embed=embed)
            return

        moved_plants_summary = []
        error_messages = []

        for plot_num in set(plot_numbers):
            plot_idx_0based = plot_num - 1

            if not (0 <= plot_idx_0based < 12):
                error_messages.append(f"Plot {plot_num}: Invalid designation (must be 1-12).")
                continue

            plant = user_data["garden"][plot_idx_0based]
            if not isinstance(plant, dict) or plant.get("type") == "seedling":
                error_messages.append(f"Plot {plot_num}: Is empty or contains a non-storable seedling.")
                continue

            success, message = await self.garden_helper.store_plant(ctx.author.id, plot_idx_0based)

            if success:
                moved_plants_summary.append(message)
            else:
                error_messages.append(f"Plot {plot_num}: Failed to store. Reason: {message}")

        if not moved_plants_summary:
            desc = "No plants were successfully moved to storage."
            if error_messages:
                desc += "\n\n**Issues Encountered:**\n" + "\n".join([f"• {msg}" for msg in error_messages])
            await ctx.send(
                embed=discord.Embed(title="❌ Storage Transfer Failed", description=desc, color=discord.Color.red()))
            return

        desc = f"User {ctx.author.mention}, asset transfer to storage successful.\n\n**Transfer Details:**\n"
        desc += "\n".join([f"• {summary}" for summary in moved_plants_summary])

        if error_messages:
            desc += "\n\n**System Advisory:** Some plants could not be stored due to the following issues:\n" + \
                    "\n".join([f"• {msg}" for msg in error_messages])

        embed = discord.Embed(title="✅ Plants Moved to Storage", description=desc, color=discord.Color.green())
        embed.set_footer(text="Penny - Asset Management Systems")
        await ctx.send(embed=embed)

    @commands.command(name="unstore")
    @is_cog_ready()
    @is_not_locked()
    async def unstore_command(self, ctx: commands.Context, *storage_space_numbers: int):
        """Moves plants from specified storage shed slots back into your garden."""

        user_data = self.garden_helper.get_user_data(ctx.author.id)

        if not self.garden_helper.user_has_storage_shed(user_data):
            embed = discord.Embed(
                title="🔒 Storage Shed Inaccessible",
                description=f"User {ctx.author.mention}, you do not currently possess a Storage Shed.",
                color=discord.Color.orange()
            )
            await ctx.send(embed=embed)
            return

        if not storage_space_numbers:
            embed = discord.Embed(
                title="⚠️ Insufficient Parameters for Storage Retrieval",
                description=f"User {ctx.author.mention}, please specify the storage space numbers of the plants you "
                            f"wish to retrieve.\nSyntax: `{ctx.prefix}unstore <space_num_1> ...`",
                color=discord.Color.orange()
            )
            await ctx.send(embed=embed)
            return

        retrieved_plants_summary = []
        error_messages = []
        storage_capacity = self.garden_helper.get_storage_capacity(user_data)

        for slot_num in set(storage_space_numbers):
            slot_idx_0based = slot_num - 1

            if not (0 <= slot_idx_0based < storage_capacity):
                error_messages.append(f"Storage Slot {slot_num}: Invalid or inaccessible.")
                continue

            if user_data["storage_shed_slots"][slot_idx_0based] is None:
                error_messages.append(f"Storage Slot {slot_num}: Is empty.")
                continue

            success, message = await self.garden_helper.unstore_plant(ctx.author.id, slot_idx_0based)

            if success:
                retrieved_plants_summary.append(message)
            else:
                error_messages.append(f"Storage Slot {slot_num}: Failed to retrieve. Reason: {message}")

        if not retrieved_plants_summary:
            desc = "No plants were successfully retrieved from storage."
            if error_messages:
                desc += "\n\n**Issues Encountered:**\n" + "\n".join([f"• {msg}" for msg in error_messages])
            await ctx.send(
                embed=discord.Embed(title="❌ Storage Retrieval Failed", description=desc, color=discord.Color.red()))
            return

        desc = f"User {ctx.author.mention}, asset retrieval from storage successful.\n\n**Retrieval Details:**\n"
        desc += "\n".join([f"• {summary}" for summary in retrieved_plants_summary])

        if error_messages:
            desc += "\n\n**System Advisory:** Some plants could not be retrieved due to the following issues:\n" + \
                    "\n".join([f"• {msg}" for msg in error_messages])

        embed = discord.Embed(title="✅ Plants Retrieved from Storage", description=desc, color=discord.Color.green())
        embed.set_footer(text="Penny - Asset Management Systems")
        await ctx.send(embed=embed)

    @commands.command(name="trade")
    @is_cog_ready()
    @is_not_locked()
    async def trade_command(self, ctx: commands.Context, recipient: discord.User, money_to_give: int,
                            *want_slots_input: str):
        """Initiate an asset exchange proposal with another user (Sun for Plants)."""

        sender = ctx.author

        if recipient.bot:
            embed = discord.Embed(title="❌ Invalid Trade Target Entity",
                                  description="Automated system entities (bots) are not authorized for asset exchange.",
                                  color=discord.Color.red())
            embed.set_footer(text="Penny - Secure Exchange System: Entity Check")
            await ctx.send(embed=embed)
            return

        if sender.id == recipient.id:
            embed = discord.Embed(title="❌ Invalid Trade Operation: Self-Target",
                                  description="Self-trading protocols are not permitted.", color=discord.Color.red())
            embed.set_footer(text="Penny - Secure Exchange System: Operation Check")
            await ctx.send(embed=embed)
            return

        if self.lock_helper.get_user_lock(recipient.id):
            embed = discord.Embed(title="❌ Target User Currently Engaged",
                                  description=f"User {recipient.mention} is currently involved in another system "
                                              f"operation and cannot trade at this time.",
                                  color=discord.Color.orange())
            await ctx.send(embed=embed)
            return

        if money_to_give < 0 or not want_slots_input:
            embed = discord.Embed(title="❌ Missing or Invalid Parameters",
                                  description=f"User {ctx.author.mention}, please specify a non-negative sun amount "
                                              f"and the plot number(s) you wish to acquire.\nSyntax: "
                                              f"`{ctx.prefix}trade @User <sun> <plot1> ...`",
                                  color=discord.Color.red())
            embed.set_footer(text="Penny - Secure Exchange System: Command Syntax")
            await ctx.send(embed=embed)
            return

        try:
            want_slots_0_indexed = sorted(list(set([int(s) - 1 for s in want_slots_input])))
        except ValueError:
            await ctx.send(embed=discord.Embed(title="❌ Invalid Parameter: Plot Designators",
                                               description="Plot designators must be numerical values.",
                                               color=discord.Color.red()))
            return

        sender_data = self.garden_helper.get_user_data(sender.id)
        if sender_data["balance"] < money_to_give:
            await ctx.send(embed=discord.Embed(title="❌ Insufficient Solar Reserves",
                                               description=f"Your proposal to offer {money_to_give:,} "
                                                           f"{self.CURRENCY_EMOJI} exceeds your current balance.",
                                               color=discord.Color.red()))
            return

        recipient_data = self.garden_helper.get_user_data(recipient.id)
        plants_to_receive_info = []
        for r_slot_idx in want_slots_0_indexed:
            if not (0 <= r_slot_idx < 12) or not self.garden_helper.is_slot_unlocked(recipient_data, r_slot_idx + 1):
                await ctx.send(embed=discord.Embed(title="❌ Invalid Target Asset",
                                                   description=f"Plot {r_slot_idx + 1} is invalid or locked for "
                                                               f"{recipient.mention}.",
                                                   color=discord.Color.red()))
                return
            plant = recipient_data["garden"][r_slot_idx]
            if not isinstance(plant, dict) or plant.get("type") == "seedling":
                await ctx.send(embed=discord.Embed(title="❌ Invalid Target Asset",
                                                   description=f"The item in {recipient.mention}'s plot "
                                                               f"{r_slot_idx + 1} is not a mature, tradable plant.",
                                                   color=discord.Color.red()))
                return
            plants_to_receive_info.append({"r_slot_index": r_slot_idx, "plant_data": plant.copy()})

        free_sender_plots = sum(1 for i, p in enumerate(sender_data["garden"]) if
                                p is None and self.garden_helper.is_slot_unlocked(sender_data, i + 1))

        if free_sender_plots < len(plants_to_receive_info):
            await ctx.send(embed=discord.Embed(title="❌ Insufficient Garden Capacity",
                                               description=f"You need {len(plants_to_receive_info)} empty garden "
                                                           f"plots to receive these plants, but yo"
                                                           f"u only have {free_sender_plots}.",
                                               color=discord.Color.red()))
            return

        trade_id = f"TR{int(time.time()) % 10000:04d}"
        trade_details = {
            "id": trade_id, "sender_id": sender.id, "recipient_id": recipient.id, "trade_type": "plant",
            "money_sender_gives": money_to_give, "plants_sender_receives_info": plants_to_receive_info,
            "status": "pending", "timestamp": TimeHelper.get_current_timestamp()
        }

        self.trade_helper.propose_trade(sender, recipient, trade_details)

        plant_names_str = "\n".join(
            [f"    • **{p['plant_data']['name']}** from plot {p['r_slot_index'] + 1}" for p in plants_to_receive_info])
        offer_desc = (f"User {sender.mention} has proposed an asset exchange with you.\n\n"
                      f"**Proposal:**\n"
                      f"  ➢ **{sender.display_name}** offers: **{money_to_give:,}** {self.CURRENCY_EMOJI}\n"
                      f"  ➢ In exchange for your asset(s):\n{plant_names_str}\n\n"
                      f"To **accept**, transmit: `{ctx.prefix}accept {trade_id}`\n"
                      f"To **decline**, transmit: `{ctx.prefix}decline {trade_id}`\n\n"
                      f"This proposal will automatically expire in **60 seconds**.")

        dm_embed = discord.Embed(title="🛰️ Incoming Asset Exchange Proposal", description=offer_desc,
                                 color=discord.Color.teal())
        dm_embed.set_footer(text=f"Trade Proposal ID: {trade_id}")
        try:
            await recipient.send(embed=dm_embed)
            await ctx.send(embed=discord.Embed(title="✅ Proposal Transmitted",
                                               description=f"Your proposal (`{trade_id}`) has been sent to "
                                                           f"{recipient.mention}. They have 60 seconds to respond.",
                                               color=discord.Color.green()))
        except discord.Forbidden:
            self.trade_helper.resolve_trade(trade_id)
            await ctx.send(embed=discord.Embed(title="❌ Transmission Failure",
                                               description=f"Could not DM {recipient.mention}. Their DMs may be "
                                                           f"disabled. Trade cancelled.",
                                               color=discord.Color.red()))
            return

        await asyncio.sleep(60)

        if self.trade_helper.resolve_trade(trade_id):
            timeout_embed = discord.Embed(title="⏰ Asset Exchange Proposal Expired",
                                          description=f"The proposal (`{trade_id}`) between {sender.mention} and "
                                                      f"{recipient.mention} has expired due to no response.",
                                          color=discord.Color.light_grey())
            for user in [sender, recipient]:
                try:
                    await user.send(embed=timeout_embed)
                except (discord.Forbidden, AttributeError):
                    pass

    @commands.command(name="tradeitem")
    @is_cog_ready()
    @is_not_locked()
    async def tradeitem_command(self, ctx: commands.Context, recipient: discord.User, sun_offered: int,
                                *item_ids: str):
        """Propose to buy multiple Material items from another user's inventory for sun."""

        sender = ctx.author

        if recipient.bot:
            embed = discord.Embed(title="❌ Invalid Trade Target Entity",
                                  description="Automated system entities (bots) are not authorized for asset exchange.",
                                  color=discord.Color.red())
            embed.set_footer(text="Penny - Secure Exchange System: Entity Check")
            await ctx.send(embed=embed)
            return

        if sender.id == recipient.id:
            embed = discord.Embed(title="❌ Invalid Trade Operation: Self-Target",
                                  description="Self-trading protocols are not permitted.", color=discord.Color.red())
            embed.set_footer(text="Penny - Secure Exchange System: Operation Check")
            await ctx.send(embed=embed)
            return

        if not item_ids:
            await ctx.send(embed=discord.Embed(title="❌ Missing Parameters",
                                               description=f"Please specify the ID(s) of the Material(s) you wish to "
                                                           f"acquire.\nSyntax: `{ctx.prefix}tradeitem @user <sun> "
                                                           f"<item_id_1> ...`",
                                               color=discord.Color.red()))
            return

        if self.lock_helper.get_user_lock(recipient.id):
            embed = discord.Embed(title="❌ Target User Currently Engaged",
                                  description=f"User {recipient.mention} is currently involved in another system "
                                              f"operation and cannot trade at this time.",
                                  color=discord.Color.orange())
            await ctx.send(embed=embed)
            return

        if sun_offered < 0:
            await ctx.send(embed=discord.Embed(title=f"❌ Invalid Parameter",
                                               description=f"The sun offered must be a non-negative amount.",
                                               color=discord.Color.red()))
            return

        sender_data = self.garden_helper.get_user_data(sender.id)
        if sender_data["balance"] < sun_offered:
            await ctx.send(embed=discord.Embed(title="❌ Insufficient Solar Reserves",
                                               description=f"Your proposal to offer {sun_offered:,} "
                                                           f"{self.CURRENCY_EMOJI} exceeds your current balance.",
                                               color=discord.Color.red()))
            return

        recipient_data = self.garden_helper.get_user_data(recipient.id)
        recipient_inv_counter = Counter(recipient_data.get("inventory", []))

        requested_items_counter = Counter()
        errors = []
        mat_id_map = {k.lower(): k for k in self.data_loader.materials_data.keys()}

        for item_input in item_ids:
            item_lower = item_input.lower()

            if item_lower in mat_id_map:
                requested_items_counter[mat_id_map[item_lower]] += 1
            else:
                errors.append(f"Item ID '{item_input}' is not a recognized tradable Material.")

        if errors:
            await ctx.send(embed=discord.Embed(title="❌ Invalid Item Request",
                                               description="The following issues were found:\n" + "\n".join(
                                                   f"• {e}" for e in errors), color=discord.Color.red()))
            return

        validated_items_info = []
        for item_id, count in requested_items_counter.items():
            item_name = self.data_loader.materials_data.get(item_id, item_id)

            if recipient_inv_counter.get(item_id, 0) < count:
                errors.append(
                    f"Recipient has {recipient_inv_counter.get(item_id, 0)} of **{item_name}**, but you requested "
                    f"{count}.")
                continue
            validated_items_info.append({"id": item_id, "name": item_name, "count": count})

        if errors:
            await ctx.send(embed=discord.Embed(title="❌ Proposal Validation Failed",
                                               description="Your trade could not be sent:\n" + "\n".join(
                                                   f"• {e}" for e in errors), color=discord.Color.red()))
            return

        trade_id = f"TI{int(time.time()) % 10000:04d}"
        trade_details = {
            "id": trade_id, "sender_id": sender.id, "recipient_id": recipient.id, "trade_type": "item",
            "sun_sender_offers": sun_offered, "items_info_list": validated_items_info, "status": "pending",
            "timestamp": TimeHelper.get_current_timestamp()
        }

        self.trade_helper.propose_trade(sender, recipient, trade_details)

        items_for_msg = "\n".join([f"    • **{item['name']}** x{item['count']}" for item in validated_items_info])
        offer_desc = (f"User {sender.mention} has proposed a Material exchange with you.\n\n"
                      f"**Proposal:**\n"
                      f"  ➢ **{sender.display_name}** offers: **{sun_offered:,}** {self.CURRENCY_EMOJI}\n"
                      f"  ➢ In exchange for your Material(s):\n{items_for_msg}\n\n"
                      f"To **accept**, transmit: `{ctx.prefix}accept {trade_id}`\n"
                      f"To **decline**, transmit: `{ctx.prefix}decline {trade_id}`\n\n"
                      f"This proposal will automatically expire in **60 seconds**.")

        dm_embed = discord.Embed(title="💎 Incoming Material Exchange Proposal", description=offer_desc,
                                 color=discord.Color.purple())
        dm_embed.set_footer(text=f"Trade Proposal ID: {trade_id}")

        try:
            await recipient.send(embed=dm_embed)
            await ctx.send(embed=discord.Embed(title="✅ Proposal Transmitted",
                                               description=f"Your Material exchange proposal (`{trade_id}`) has been "
                                                           f"sent to {recipient.mention}.",
                                               color=discord.Color.green()))
        except discord.Forbidden:
            self.trade_helper.resolve_trade(trade_id)
            await ctx.send(embed=discord.Embed(title="❌ Transmission Failure",
                                               description=f"Unable to DM {recipient.mention}. Trade cancelled.",
                                               color=discord.Color.red()))
            return

        await asyncio.sleep(60)
        if expired_trade := self.trade_helper.resolve_trade(trade_id):
            sender = self.bot.get_user(expired_trade["sender_id"])
            recipient = self.bot.get_user(expired_trade["recipient_id"])
            timeout_embed = discord.Embed(title="⏰ Material Exchange Proposal Expired",
                                          description=f"The proposal (`{trade_id}`) between {sender.mention} and "
                                                      f"{recipient.mention} has expired.",
                                          color=discord.Color.light_grey())

            for user in [sender, recipient]:
                if user:
                    try:
                        await user.send(embed=timeout_embed)
                    except (discord.Forbidden, AttributeError):
                        pass

    @commands.command(name="accept")
    @is_cog_ready()
    async def accept_command(self, ctx: commands.Context, trade_id: str):
        """Confirm and execute a pending asset exchange proposal you received."""

        trade_peek = self.trade_helper.pending_trades.get(trade_id)

        if not trade_peek:
            embed = discord.Embed(title="❌ Invalid Proposal Identifier",
                                  description=f"The ID (`{trade_id}`) does not correspond to an active proposal.",
                                  color=discord.Color.red())
            await ctx.send(embed=embed)
            return

        if trade_peek.get("recipient_id") != ctx.author.id:
            embed = discord.Embed(title="❌ Unauthorized Action", description="This proposal is not addressed to you.",
                                  color=discord.Color.red())
            await ctx.send(embed=embed)
            return

        trade = self.trade_helper.resolve_trade(trade_id)
        if not trade:
            embed = discord.Embed(title="❌ Proposal No Longer Active",
                                  description="This proposal has just expired or was cancelled.",
                                  color=discord.Color.orange())
            await ctx.send(embed=embed)
            return

        sender_id = trade["sender_id"]
        recipient_id = trade["recipient_id"]
        sender_data = self.garden_helper.get_user_data(sender_id)
        recipient_data = self.garden_helper.get_user_data(recipient_id)

        trade_type = trade.get("trade_type", "plant")
        success = False
        message = "Critical Error: Unknown trade type."
        changes = None

        if trade_type == "plant":
            sender_unlocked_slots = {i + 1 for i in range(12) if
                                     self.garden_helper.is_slot_unlocked(sender_data, i + 1)}
            success, message, changes = self.trade_helper.execute_plant_trade(
                trade_data=trade,
                sender_data=sender_data,
                recipient_data=recipient_data,
                sender_unlocked_slots=sender_unlocked_slots
            )
        elif trade_type == "item":
            success, message, changes = self.trade_helper.execute_item_trade(
                trade_data=trade,
                sender_data=sender_data,
                recipient_data=recipient_data
            )

        sender = self.bot.get_user(sender_id)

        if success and changes:
            for update in changes.get("balance_updates", []):
                if update["amount"] > 0:
                    await self.garden_helper.add_balance(update["user_id"], update["amount"])
                else:
                    await self.garden_helper.remove_balance(update["user_id"], -update["amount"])

            for move in changes.get("plant_moves", []):
                await self.garden_helper.set_garden_plot(move["from_user_id"], move["from_plot_idx"], None)
                await self.garden_helper.set_garden_plot(move["to_user_id"], move["to_plot_idx"], move["plant_data"])

            for transfer in changes.get("item_transfers", []):
                await self.garden_helper.remove_item_from_inventory(transfer["from_user_id"], transfer["item_id"],
                                                                    transfer["quantity"])
                await self.garden_helper.add_item_to_inventory(transfer["to_user_id"], transfer["item_id"],
                                                               transfer["quantity"])

            embed_acceptor = discord.Embed(title="✅ Asset Exchange Confirmed & Executed",
                                           description=f"You accepted proposal `{trade_id}` from "
                                                       f"{sender.mention if sender else 'the other user'}."
                                                       f"\n**Details:** {message}",
                                           color=discord.Color.green())
            await ctx.send(embed=embed_acceptor)
            if sender:
                try:
                    embed_sender = discord.Embed(title="✅ Proposal Accepted",
                                                 description=f"Your proposal (`{trade_id}`) with {ctx.author.mention} "
                                                             f"was accepted and executed.",
                                                 color=discord.Color.green())
                    await sender.send(embed=embed_sender)
                except discord.Forbidden:
                    pass
        else:
            embed_acceptor = discord.Embed(title="❌ Asset Exchange Failed During Final Execution",
                                           description=f"While finalizing proposal `{trade_id}`, an error occurred: "
                                                       f"**{message}**\n\nNo assets were exchanged.",
                                           color=discord.Color.red())
            await ctx.send(embed=embed_acceptor)
            if sender:
                try:
                    embed_sender = discord.Embed(title="❌ Proposal Execution Failed",
                                                 description=f"Your proposal (`{trade_id}`) with {ctx.author.mention} "
                                                             f"failed final validation: **{message}**",
                                                 color=discord.Color.red())
                    await sender.send(embed=embed_sender)
                except discord.Forbidden:
                    pass

    @commands.command(name="decline")
    @is_cog_ready()
    async def decline_command(self, ctx: commands.Context, trade_id: str):
        """Reject a pending asset exchange proposal or cancel one you initiated."""

        trade_peek = self.trade_helper.pending_trades.get(trade_id)

        if not trade_peek:
            await ctx.send(embed=discord.Embed(title="❌ Invalid Proposal Identifier",
                                               description=f"The ID (`{trade_id}`) is invalid or does not involve you.",
                                               color=discord.Color.red()))
            return

        is_sender = trade_peek.get("sender_id") == ctx.author.id
        is_recipient = trade_peek.get("recipient_id") == ctx.author.id

        if not (is_sender or is_recipient):
            await ctx.send(
                embed=discord.Embed(title="❌ Unauthorized Action", description="This proposal does not involve you.",
                                    color=discord.Color.red()))
            return

        trade = self.trade_helper.resolve_trade(trade_id)
        if not trade:
            await ctx.send(
                embed=discord.Embed(title="❌ Proposal Not Active", description="This proposal is no longer pending.",
                                    color=discord.Color.orange()))
            return

        action = "cancelled" if is_sender else "declined"
        other_party_id = trade["recipient_id"] if is_sender else trade["sender_id"]
        other_party = self.bot.get_user(other_party_id)

        action_title = f"❌ Asset Exchange Proposal {action.capitalize()}"
        action_desc = f"User {ctx.author.mention} has successfully **{action}** asset exchange proposal (`{trade_id}`)."
        await ctx.send(embed=discord.Embed(title=action_title, description=action_desc, color=discord.Color.red()))

        if other_party:
            try:
                other_party_desc = f"Asset exchange proposal (`{trade_id}`) with {ctx.author.mention} was **{action}**."
                await other_party.send(
                    embed=discord.Embed(title=action_title, description=other_party_desc, color=discord.Color.red()))
            except discord.Forbidden:
                pass

    @commands.command(name="fuse")
    @is_cog_ready()
    @is_not_locked()
    async def fuse_command(self, ctx: commands.Context, *args: str):
        """Fuse plants from plots and/or Material items from your inventory."""

        if len(args) < 2:
            embed = discord.Embed(title="⚠️ Insufficient Components for Fusion",
                                  description=f"User {ctx.author.mention}, fusion protocol requires a minimum of two "
                                              f"components.\nSyntax: `{ctx.prefix}fuse <plot_num_1> <item_id_1> ...`",
                                  color=discord.Color.orange())
            embed.set_footer(text="Penny - Fusion Systems Interface")
            await ctx.send(embed=embed)
            return

        user_data = self.garden_helper.get_user_data(ctx.author.id)

        first_plot_mentioned = None
        validated_plots_info = []
        requested_items_counter = Counter()
        errors = []

        plot_args = [arg for arg in args if arg.isdigit()]
        if len(plot_args) != len(set(plot_args)):
            errors.append("Duplicate plots were mentioned. Each plot can only be used once per fusion attempt.")

        processed_plots = set()

        mat_id_map = {name.lower(): mat_id for mat_id, name in self.data_loader.materials_data.items()}
        mat_id_map.update({mat_id.lower(): mat_id for mat_id in self.data_loader.materials_data.keys()})

        for arg in args:
            if arg.isdigit():
                plot_num = int(arg)

                if first_plot_mentioned is None:
                    first_plot_mentioned = plot_num

                if plot_num in processed_plots:
                    continue

                processed_plots.add(plot_num)

                if not (1 <= plot_num <= 12):
                    errors.append(f"Plot {plot_num}: Invalid number.")
                elif not self.garden_helper.is_slot_unlocked(user_data, plot_num):
                    errors.append(f"Plot {plot_num}: Locked.")
                else:
                    plant = user_data["garden"][plot_num - 1]
                    if isinstance(plant, dict) and plant.get("type") != "seedling":
                        validated_plots_info.append({"data": plant, "slot_1based": plot_num})
                    else:
                        errors.append(f"Plot {plot_num}: Is empty or has a non-fusable seedling.")
            else:
                arg_lower = arg.lower()
                canonical_id = mat_id_map.get(arg_lower)
                if canonical_id:
                    requested_items_counter[canonical_id] += 1
                else:
                    errors.append(f"'{arg}' is not a valid plot number or fusable material.")

        for item_id, count in requested_items_counter.items():
            if Counter(user_data["inventory"]).get(item_id, 0) < count:
                item_name = self.data_loader.materials_data.get(item_id, item_id)
                errors.append(
                    f"You need {count}x **{item_name}** but only have "
                    f"{Counter(user_data['inventory']).get(item_id, 0)}.")

        if first_plot_mentioned is None:
            errors.append("Fusion requires at least one plant from a plot to determine the result's location.")

        if errors:
            await ctx.send(embed=discord.Embed(title="❌ Fusion Input Error",
                                               description="Fusion protocol aborted due to input failures:\n\n"
                                                           + "\n".join(f"• {e}" for e in errors),
                                               color=discord.Color.red()))
            return

        base_components = []
        deconstruction_errors = []
        for plot_info in validated_plots_info:
            components, errors = self.fusion_helper.deconstruct_plant(plot_info["data"])
            base_components.extend(components)
            deconstruction_errors.extend(errors)

        for item_id, count in requested_items_counter.items():
            item_name = self.data_loader.materials_data.get(item_id, item_id)
            base_components.extend([item_name] * count)

        if deconstruction_errors:
            await ctx.send(embed=discord.Embed(title="❌ Fusion Deconstruction Error",
                                               description="Errors occurred during component analysis:\n\n" + "\n".join(
                                                   f"• {e}" for e in deconstruction_errors), color=discord.Color.red()))
            return

        fusion_result_data = self.fusion_helper.find_fusion_match(base_components)

        consumed_list_str = [f"**{p['data']['name']}** (Plot {p['slot_1based']})" for p in validated_plots_info]
        consumed_list_str.extend(
            [f"**{self.data_loader.materials_data.get(item_id, item_id)}** x{count}" for item_id, count in
             requested_items_counter.items()])

        if not fusion_result_data:
            desc = f"The combination of components from {', '.join(consumed_list_str)} does not match any known " \
                   f"fusion recipe."
            await ctx.send(embed=discord.Embed(title="🚫 No Matching Fusion Recipe Found", description=desc,
                                               color=discord.Color.orange()))
            return

        result_plant_name = fusion_result_data.get('name', fusion_result_data['id'])
        fusion_visibility = fusion_result_data.get("visibility", "visible")
        is_new = fusion_result_data['id'] not in user_data.get("fusions", []) and fusion_visibility != "invisible"
        output_slot = first_plot_mentioned

        lock_message = f"Awaiting confirmation to fuse components into a **{result_plant_name}**."
        self.lock_helper.add_lock(ctx.author.id, "fusion", lock_message)

        confirm_desc = (f"User {ctx.author.mention}, the following components will be consumed:\n"
                        f"  • {', '.join(consumed_list_str)}\n\n"
                        f"This combination will create: **{result_plant_name}{' [NEW]' if is_new else ''}**\n\n"
                        f"The result will be placed in plot **{output_slot}**. Proceed? (yes/no)")

        embed = discord.Embed(title="🧬 Fusion Confirmation Required", description=confirm_desc,
                              color=discord.Color.teal())
        await ctx.send(embed=embed)

        try:
            msg = await self.bot.wait_for("message", timeout=30.0,
                                          check=lambda m: m.author == ctx.author and m.channel == ctx.channel
                                          and m.content.lower() in ["yes", "y", "no", "n"])

            if msg.content.lower() in ["no", "n"]:
                await ctx.send(embed=discord.Embed(title="🚫 Fusion Cancelled",
                                                   description="Fusion protocol has been cancelled by user directive.",
                                                   color=discord.Color.light_grey()))
                return
        except asyncio.TimeoutError:
            await ctx.send(embed=discord.Embed(title="⏰ Fusion Timed Out",
                                               description="Confirmation not received. The operation has been "
                                                           "automatically cancelled.",
                                               color=discord.Color.light_grey()))
            return
        finally:
            self.lock_helper.remove_lock_for_user(ctx.author.id)

        for item_id, count in requested_items_counter.items():
            await self.garden_helper.remove_item_from_inventory(ctx.author.id, item_id, count)

        for plot_info in validated_plots_info:
            await self.garden_helper.set_garden_plot(ctx.author.id, plot_info["slot_1based"] - 1, None)

        new_plant = {"id": fusion_result_data["id"], "name": result_plant_name,
                     "type": fusion_result_data.get("type", "unknown")}
        await self.garden_helper.set_garden_plot(ctx.author.id, output_slot - 1, new_plant)

        bonus_text = ""
        if is_new:
            await self.garden_helper.add_fusion_discovery(ctx.author.id, fusion_result_data['id'])
            bonus = int(0.5 * self.sales_helper.get_sale_price(new_plant.get("type", "")))
            if bonus > 0:
                await self.garden_helper.add_balance(ctx.author.id, bonus)
                bonus_text = f"\n\n**New Fusion Discovery!** You've been awarded a bonus of **{bonus:,}** " \
                             f"{self.CURRENCY_EMOJI}!"

        unlock_text = ""
        user_data = self.garden_helper.get_user_data(ctx.author.id)
        if fusion_visibility != "invisible":
            newly_unlocked_bgs = self.background_helper.check_for_unlocks(
                user_data.get("fusions", []), user_data.get("unlocked_backgrounds", [])
            )
            if newly_unlocked_bgs:
                unlocked_names = []
                for bg in newly_unlocked_bgs:
                    await self.garden_helper.add_unlocked_background(ctx.author.id, bg['id'])
                    unlocked_names.append(f"**{bg['name']}**")
                unlock_text = f"\n\n🎉 **Background Unlocked!** You have unlocked the {', '.join(unlocked_names)} " \
                              f"garden background! Use `{ctx.prefix}background` to manage it."

        success_desc = f"Fusion successful! A **{result_plant_name}** has been cultivated in plot {output_slot}." \
                       + bonus_text + unlock_text
        success_embed = discord.Embed(title="✅ Fusion Protocol Complete", description=success_desc,
                                      color=discord.Color.green())
        success_embed.set_footer(text="Penny - Fusion Systems Interface")

        image_file_to_send = self.image_helper.get_image_file_for_plant(fusion_result_data.get("id"))
        if image_file_to_send:
            success_embed.set_image(url=f"attachment://{image_file_to_send.filename}")

        await ctx.send(embed=success_embed, file=image_file_to_send)

    @commands.group(name="almanac", invoke_without_command=True)
    @is_cog_ready()
    async def almanac_command(self, ctx: commands.Context, *, full_args: str = ""):
        """Displays your discovered fusions. Use subcommands for more actions."""

        if ctx.invoked_subcommand is not None:
            return

        is_list_intent = (
                not full_args or
                any(":" in arg for arg in full_args.split()) or
                (full_args and full_args.strip().split()[-1].isdigit())
        )

        if is_list_intent:
            user_data = self.garden_helper.get_user_data(ctx.author.id)
            discovered_ids = set(user_data.get("fusions", []))

            discovered_fusions_to_display = [f for f in self.fusion_helper.visible_fusions if f['id'] in discovered_ids]
            for fid in discovered_ids:
                if hidden_fusion := self.fusion_helper.hidden_fusions_by_id.get(fid):
                    discovered_fusions_to_display.append(hidden_fusion)

            if not discovered_fusions_to_display:
                await ctx.send(embed=discord.Embed(title=f"🔬 {ctx.author.display_name}'s Almanac",
                                                   description="You have not discovered any fusions yet.",
                                                   color=discord.Color.purple()))
                return

            parsed_args = self.fusion_helper.parse_almanac_args(full_args)
            filters, page = parsed_args['filters'], parsed_args['page']
            filtered_fusions = self.fusion_helper.apply_almanac_filters(discovered_fusions_to_display, filters,
                                                                        discovered_ids)

            if not filtered_fusions:
                await ctx.send(embed=discord.Embed(title="ℹ️ Almanac Search",
                                                   description="No discovered fusions match your specified filters.",
                                                   color=discord.Color.purple()))
                return

            total_visible_fusions = len(self.fusion_helper.visible_fusions)
            discovered_hidden_count = sum(1 for fid in discovered_ids if fid in self.fusion_helper.hidden_fusions_by_id)
            total_almanac_fusions = total_visible_fusions + discovered_hidden_count

            items_per_page = 10
            total_pages = max(1, (len(filtered_fusions) + items_per_page - 1) // items_per_page)
            page = max(1, min(page, total_pages))
            page_entries = sorted(filtered_fusions, key=lambda x: x['name'])[
                           (page - 1) * items_per_page: page * items_per_page]

            title = f"🔬 {ctx.author.display_name}'s Almanac ({len(discovered_ids)}/{total_almanac_fusions}) " \
                    f"(Page {page}/{total_pages})"
            embed = discord.Embed(title=title, color=discord.Color.purple())

            display_lines = []
            for i, f in enumerate(page_entries, start=(page - 1) * items_per_page + 1):
                recipe_str = self.fusion_helper.format_recipe_string(f.get('recipe', []))
                display_lines.append(f"**{i}.** **{f['name']}**\nRecipe: {recipe_str}")

            embed.description = "\n\n".join(display_lines)
            embed.set_footer(
                text=f"Use {ctx.prefix}almanac [filters] [page]. Filters: name:<str> contains:<str> tier:<#>")
            await ctx.send(embed=embed)

        else:
            await self.almanac_info_command.callback(self, ctx, fusion_query=full_args.strip())

    @almanac_command.command(name="info")
    async def almanac_info_command(self, ctx: commands.Context, *, fusion_query: str):
        """Shows detailed info for a specific discovered fusion."""

        user_data = self.garden_helper.get_user_data(ctx.author.id)
        discovered_ids = set(user_data.get("fusions", []))

        fusion_def = self.fusion_helper.find_defined_fusion(fusion_query)

        if not fusion_def or fusion_def.get("visibility") == "invisible":
            embed = discord.Embed(title="ℹ️ Recipe Unknown",
                                  description=f"The fusion recipe for **'{fusion_query}'** could not be found.",
                                  color=discord.Color.purple())
            await ctx.send(embed=embed)
            return

        if fusion_def.get("visibility") == "hidden" and fusion_def['id'] not in discovered_ids:
            embed = discord.Embed(title="ℹ️ Recipe Unknown",
                                  description=f"The fusion recipe for **'{fusion_query}'** could not be found.",
                                  color=discord.Color.purple())
            await ctx.send(embed=embed)
            return

        if fusion_def['id'] not in discovered_ids:
            embed = discord.Embed(title="ℹ️ Fusion Not Discovered",
                                  description=f"You have not discovered **{fusion_def['name']}** yet. ",
                                  color=discord.Color.purple())
            await ctx.send(embed=embed)
            return

        embed = discord.Embed(title=f"🌿 Almanac Entry: {fusion_def['name']}",
                              description=f"Detailed schematics for **{fusion_def['name']}** from your almanac.",
                              color=discord.Color.purple())
        embed.add_field(name="Asset ID", value=f"`{fusion_def['id']}`", inline=True)
        embed.add_field(name="Classification Tier", value=f"`{fusion_def.get('type', 'N/A')}`", inline=True)
        embed.add_field(name="Fusion Recipe",
                        value=self.fusion_helper.format_recipe_string(fusion_def.get('recipe', [])), inline=False)

        image_file_to_send = self.image_helper.get_image_file_for_plant(fusion_def.get("id"))

        if image_file_to_send:
            embed.set_image(url=f"attachment://{image_file_to_send.filename}")

        embed.set_footer(text="Penny - Fusion Experimentation Log")
        await ctx.send(embed=embed, file=image_file_to_send)

    @almanac_command.command(name="available")
    async def almanac_available_command(self, ctx: commands.Context, *, full_args: str = ""):
        """Lists all fusions you can make right now."""

        user_data = self.garden_helper.get_user_data(ctx.author.id)
        discovered_ids = set(user_data.get("fusions", []))
        parsed_args = self.fusion_helper.parse_almanac_args(full_args)
        filters, page = parsed_args['filters'], parsed_args['page']

        user_assets = self.fusion_helper.get_user_whole_assets_with_source(user_data)

        sorted_user_assets = sorted(
            user_assets,
            key=lambda x: len(self.fusion_helper.deconstruct_plant(x)[0]),
            reverse=True
        )

        all_craftable_fusions = []
        for fusion_def in self.fusion_helper.visible_fusions:
            plan, _ = self.fusion_helper.find_crafting_plan(
                recipe_counter=Counter(fusion_def.get("recipe", [])),
                user_assets=user_assets,
                fusion_id_to_check=fusion_def.get("id")
            )

            if plan is not None:
                recipe_counter = Counter(fusion_def.get("recipe", []))
                temp_needed = recipe_counter.copy()
                have_assets_list = []

                for asset in sorted_user_assets:
                    if any(asset['source'] == p['source'] and asset['index'] == p['index'] and asset['id'] == p['id']
                           for p in plan):
                        asset_components, _ = self.fusion_helper.deconstruct_plant(asset)
                        asset_counter = Counter(asset_components)
                        if all(temp_needed.get(item, 0) >= count for item, count in asset_counter.items()):
                            temp_needed -= asset_counter
                            have_assets_list.append(asset['name'])

                fusion_def['have_list'] = have_assets_list
                fusion_def['plan'] = plan
                fusion_def['is_new'] = fusion_def['id'] not in discovered_ids
                all_craftable_fusions.append(fusion_def)

        plans_by_fusion_id = {f['id']: f['plan'] for f in all_craftable_fusions}
        filtered_results = self.fusion_helper.apply_almanac_filters(all_craftable_fusions, filters, discovered_ids,
                                                                    plans_by_fusion_id=plans_by_fusion_id)

        if not filtered_results:
            desc = "You cannot make any fusions that match your filters with your current assets."
            await ctx.send(
                embed=discord.Embed(title="✅ Available Fusions", description=desc, color=discord.Color.purple()))
            return

        items_per_page = 5
        sorted_entries = sorted(filtered_results,
                                key=lambda f: (not f.get('is_new', False), len(f.get('recipe', [])), f['name']))

        total_pages = max(1, (len(sorted_entries) + items_per_page - 1) // items_per_page)
        page = max(1, min(page, total_pages))
        page_entries = sorted_entries[(page - 1) * items_per_page: page * items_per_page]

        embed = discord.Embed(title=f"✅ Available Fusions (Page {page}/{total_pages})", color=discord.Color.purple())

        for f in page_entries:
            new_tag = " **[NEW]**" if f['is_new'] else ""
            storage_items_in_plan = [asset for asset in f.get("plan", []) if asset.get("source") == "storage"]
            storage_tag = " 📦" if storage_items_in_plan else ""
            recipe_str = self.fusion_helper.format_recipe_string(f.get('recipe', []))

            have_list = f.get('have_list', [])
            have_str = ", ".join(
                [f"**{name}** x{count}" for name, count in Counter(have_list).items()]) if have_list else "None"

            if not storage_tag:
                fuse_args = [str(a['index'] + 1) if a['source'] == 'garden' else a['id'] for a in f.get('plan', [])]
                command_str = f"`{ctx.prefix}fuse {' '.join(fuse_args)}`"
            else:
                unstore_indices = sorted([str(asset['index'] + 1) for asset in storage_items_in_plan])
                command_str = f"`{ctx.prefix}unstore {' '.join(unstore_indices)}`"

            value_str = f"Recipe: {recipe_str}\nHave: {have_str}\n{command_str}"
            embed.add_field(name=f"▫️ {f['name']}{new_tag}{storage_tag}", value=value_str, inline=False)

        embed.set_footer(
            text=f"Use {ctx.prefix}almanac available [filters] [page]. Filters: name:<str> contains:<str> tier:<#> "
                 f"discovered:<bool> storage:<bool>")
        await ctx.send(embed=embed)

    @almanac_command.command(name="discover")
    async def almanac_discover_command(self, ctx: commands.Context, *, full_args: str = ""):
        """Lists potential discoveries using at least one of your plants or materials."""

        user_data = self.garden_helper.get_user_data(ctx.author.id)
        discovered_ids = set(user_data.get("fusions", []))
        parsed_args = self.fusion_helper.parse_almanac_args(full_args)
        filters, page = parsed_args['filters'], parsed_args['page']

        user_assets = self.fusion_helper.get_user_whole_assets_with_source(user_data)
        if any(f['key'] == 'storage' and f['value'] == 'false' for f in filters):
            user_assets = [asset for asset in user_assets if asset.get("source") != "storage"]

        potential_fusions = []
        material_names = self.fusion_helper.all_materials_by_name

        valid_user_assets = self._get_valid_crafting_components(user_assets)

        sorted_user_assets = sorted(
            valid_user_assets,
            key=lambda x: len(self.fusion_helper.deconstruct_plant(x)[0]),
            reverse=True
        )

        for fusion_def in self.fusion_helper.visible_fusions:
            if fusion_def['id'] in discovered_ids:
                continue

            recipe_counter = Counter(fusion_def.get("recipe", []))

            plan, needed = self.fusion_helper.find_crafting_plan(
                recipe_counter=recipe_counter,
                user_assets=user_assets,
                fusion_id_to_check=fusion_def.get('id')
            )

            fusion_def['plan'] = plan
            fusion_def['need_counter'] = needed

            have_assets_list = []
            if plan is not None:
                have_assets_list = [p.get('name', 'Unknown') for p in plan]
                sort_group = 0
            else:
                temp_needed = recipe_counter.copy()

                for asset in sorted_user_assets:
                    asset_components, _ = self.fusion_helper.deconstruct_plant(asset)
                    asset_counter = Counter(asset_components)

                    if all(temp_needed.get(item, 0) >= count for item, count in asset_counter.items()):
                        temp_needed -= asset_counter
                        have_assets_list.append(asset['name'])

                sort_group = 3
                if have_assets_list:
                    if any(comp not in material_names for comp in have_assets_list):
                        sort_group = 1
                    else:
                        sort_group = 2

            fusion_def['have_list'] = have_assets_list
            fusion_def['sort_group'] = sort_group

            potential_fusions.append(fusion_def)

        missing_filter_value = None
        temp_filters = list(filters)
        for f in temp_filters:
            if f['key'] == 'missing':
                try:
                    missing_filter_value = int(f['value'])
                except ValueError:
                    pass
                filters.remove(f)

        filtered_results = self.fusion_helper.apply_almanac_filters(potential_fusions, filters, discovered_ids)

        if missing_filter_value is not None:
            filtered_results = [f for f in filtered_results if
                                sum(f.get('need_counter', Counter()).values()) == missing_filter_value]

        if not filtered_results:
            await ctx.send(embed=discord.Embed(title="🌱 Potential Discoveries",
                                               description="No undiscovered recipes match your criteria.",
                                               color=discord.Color.purple()))
            return

        def sort_key(f):
            group = f.get('sort_group', 3)
            if group < 2:
                key1 = sum(f.get('need_counter', Counter()).values())
                key2 = len(f.get('recipe', []))
                key3 = f['name']
                return group, key1, key2, key3
            elif group == 2:
                key1 = -len(f.get('have_list', []))
                key2 = len(f.get('recipe', []))
                key3 = f['name']
                return group, key1, key2, key3
            else:
                key1 = len(f.get('recipe', []))
                key2 = f['name']
                key3 = 0
                return group, key1, key2, key3

        sorted_entries = sorted(filtered_results, key=sort_key)

        items_per_page = 5
        total_pages = max(1, (len(sorted_entries) + items_per_page - 1) // items_per_page)
        page = max(1, min(page, total_pages))
        page_entries = sorted_entries[(page - 1) * items_per_page: page * items_per_page]

        embed = discord.Embed(title=f"🌱 Potential Discoveries (Page {page}/{total_pages})",
                              color=discord.Color.purple())

        for f in page_entries:
            value_lines = []
            if f['plan'] is not None:
                recipe_str = self.fusion_helper.format_recipe_string(f.get('recipe', []))
                have_str = ", ".join(
                    [f"**{name}** x{count}" for name, count in Counter(f.get('have_list', [])).items()])
                storage_items_in_plan = [asset for asset in f.get("plan", []) if asset.get("source") == "storage"]
                storage_tag = " 📦" if storage_items_in_plan else ""
                header = f"✅ **Ready to Fuse!**{storage_tag}\nRecipe: {recipe_str}\nHave: {have_str}"

                if not storage_tag:
                    fuse_args = [str(a['index'] + 1) if a['source'] == 'garden' else a['id'] for a in f['plan']]
                    command_str = f"`{ctx.prefix}fuse {' '.join(fuse_args)}`"
                    value_lines.append(f"{header}\n{command_str}")
                else:
                    unstore_indices = sorted([str(asset['index'] + 1) for asset in storage_items_in_plan])
                    command_str = f"`{ctx.prefix}unstore {' '.join(unstore_indices)}`"
                    value_lines.append(f"{header}\n{command_str}")
            else:
                recipe_str = self.fusion_helper.format_recipe_string(f.get('recipe', []))
                value_lines.append(f"Recipe: {recipe_str}")

                have_list = f.get('have_list', [])
                if have_list:
                    have_str = ", ".join([f"**{name}** x{count}" for name, count in Counter(have_list).items()])
                    value_lines.append(f"Have: {have_str}")

                need_counter = f.get('need_counter', Counter())
                if any(count > 0 for count in need_counter.values()):
                    need_str = ", ".join([f"**{name}** x{count}" for name, count in need_counter.items() if count > 0])
                    value_lines.append(f"Need: {need_str}")

            embed.add_field(name=f"▫️ {f['name']}", value="\n".join(value_lines) or " ", inline=False)

        embed.set_footer(
            text=f"Use {ctx.prefix}almanac discover [filters] [page]. Filters: name:<str> contains:<str> tier:<#> "
                 f"storage:<bool> missing:<#>")
        await ctx.send(embed=embed)

    @commands.group(name="background", invoke_without_command=True)
    @is_cog_ready()
    async def background_command(self, ctx: commands.Context, *, background_name: Optional[str] = None):
        """View and set your unlocked garden backgrounds."""

        if background_name:
            await self.background_set_command.callback(self, ctx, background_name=background_name)
        else:
            await self.background_list_command.callback(self, ctx)

    @background_command.command(name="list")
    async def background_list_command(self, ctx: commands.Context):
        """Displays all the garden backgrounds you have unlocked."""

        user_data = self.garden_helper.get_user_data(ctx.author.id)
        unlocked_ids = set(user_data.get("unlocked_backgrounds", ["default"]))
        active_id = user_data.get("active_background", "default")

        embed = discord.Embed(
            title=f"🖼️ {ctx.author.display_name}'s Unlocked Backgrounds",
            description=f"You have unlocked **{len(unlocked_ids)}** background(s). Use `{ctx.prefix}bg set <name>` to "
                        f"change your active background.",
            color=discord.Color.dark_magenta()
        )

        display_lines = []
        for bg_def in self.background_helper.all_backgrounds:
            if bg_def['id'] in unlocked_ids:
                is_active = "✅" if bg_def['id'] == active_id else "▫️"
                display_lines.append(f"{is_active} **{bg_def['name']}**")

        embed.add_field(name="Available Backgrounds", value="\n".join(display_lines) or "None unlocked.")
        await ctx.send(embed=embed)

    @background_command.command(name="set")
    async def background_set_command(self, ctx: commands.Context, *, background_name: str):
        """Sets your active garden background."""

        user_data = self.garden_helper.get_user_data(ctx.author.id)
        unlocked_ids = set(user_data.get("unlocked_backgrounds", ["default"]))

        target_bg = None
        for bg_def in self.background_helper.all_backgrounds:
            if bg_def['name'].lower() == background_name.lower():
                target_bg = bg_def
                break

        if not target_bg:
            await ctx.send(embed=discord.Embed(title="❌ Background Not Found",
                                               description=f"No background named '{background_name}' exists.",
                                               color=discord.Color.red()))
            return

        if target_bg['id'] not in unlocked_ids:
            await ctx.send(embed=discord.Embed(title="❌ Background Locked",
                                               description=f"You have not unlocked the **{target_bg['name']}** "
                                                           f"background yet.",
                                               color=discord.Color.red()))
            return

        await self.garden_helper.set_active_background(ctx.author.id, target_bg['id'])

        embed = discord.Embed(
            title="✅ Background Set!",
            description=f"Your active garden background has been set to **{target_bg['name']}**. Your profile will now "
                        f"reflect this change.",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)

    @commands.group(name="debug")
    @is_cog_ready()
    @commands.is_owner()
    async def cmd_debug_group(self, ctx: commands.Context):
        """Base command for owner-only Zen Garden debug utilities."""
        pass

    @cmd_debug_group.command(name="setsun")
    async def debug_setsun_command(self, ctx: commands.Context, amount: int, target_user: discord.Member):
        """Sets a user's balance to a specific amount."""

        if amount < 0:
            await ctx.send(embed=discord.Embed(title="❌ Invalid Input",
                                               description="Amount cannot be negative. Use a positive integer or zero.",
                                               color=discord.Color.red()))
            return

        user_data = self.garden_helper.get_user_data(target_user.id)
        original_balance = user_data.get("balance", 0)

        await self.garden_helper.set_balance(target_user.id, amount)
        user_data = self.garden_helper.get_user_data(target_user.id)

        embed = discord.Embed(
            title="⚙️ Debug: Solar Energy Set Protocol",
            description=f"Successfully set the solar energy balance for User {target_user.mention}.",
            color=discord.Color.orange()
        )
        embed.add_field(name="Target User", value=target_user.mention, inline=True)
        embed.add_field(name="Set Amount", value=f"{amount:,}", inline=True)
        embed.add_field(name="Original Balance", value=f"{original_balance:,} {self.CURRENCY_EMOJI}", inline=False)
        embed.add_field(name="New Balance", value=f"{user_data['balance']:,} {self.CURRENCY_EMOJI}", inline=False)
        embed.set_footer(text="Penny - Administrative Financial Override Systems")
        await ctx.send(embed=embed)

    @cmd_debug_group.command(name="setsunmastery")
    async def debug_setsunmastery_command(self, ctx: commands.Context, level: int, target_user: discord.Member):
        """Sets a user's Sun Mastery level."""

        if level < 0:
            await ctx.send(embed=discord.Embed(title="❌ Invalid Input",
                                               description="Mastery level cannot be negative. Use a positive integer "
                                                           "or zero.",
                                               color=discord.Color.red()))
            return

        user_data = self.garden_helper.get_user_data(target_user.id)
        original_mastery = user_data.get("mastery", 0)

        await self.garden_helper.set_sun_mastery(target_user.id, level)
        user_data = self.garden_helper.get_user_data(target_user.id)

        sun_mastery_bonus = 1 + (0.1 * level)

        embed = discord.Embed(
            title="⚙️ Debug: Sun Mastery Level Set Protocol",
            description=f"Successfully set the Sun Mastery level for User {target_user.mention}.",
            color=discord.Color.orange()
        )
        embed.add_field(name="Target User", value=target_user.mention, inline=True)
        embed.add_field(name="Set Level", value=f"{level}", inline=True)
        embed.add_field(name="Original Sun Mastery", value=f"{original_mastery}", inline=False)
        embed.add_field(name="New Sun Mastery", value=f"{user_data['mastery']} ({sun_mastery_bonus:.2f}x sell boost)",
                        inline=False)
        embed.set_footer(text="Penny - Administrative Stat Override Systems")
        await ctx.send(embed=embed)

    @cmd_debug_group.command(name="settimemastery")
    async def debug_settimemastery_command(self, ctx: commands.Context, level: int, target_user: discord.Member):
        """Sets a user's Time Mastery level."""

        if level < 0:
            await ctx.send(embed=discord.Embed(title="❌ Invalid Input",
                                               description="Mastery level cannot be negative. Use a positive integer "
                                                           "or zero.",
                                               color=discord.Color.red()))
            return

        user_data = self.garden_helper.get_user_data(target_user.id)
        original_mastery = user_data.get("time_mastery", 0)

        await self.garden_helper.set_time_mastery(target_user.id, level)
        user_data = self.garden_helper.get_user_data(target_user.id)

        time_mastery_bonus = 1 + (0.1 * level)

        embed = discord.Embed(
            title="⚙️ Debug: Time Mastery Level Set Protocol",
            description=f"Successfully set the Time Mastery level for User {target_user.mention}.",
            color=discord.Color.orange()
        )
        embed.add_field(name="Target User", value=target_user.mention, inline=True)
        embed.add_field(name="Set Level", value=f"{level}", inline=True)
        embed.add_field(name="Original Time Mastery", value=f"{original_mastery}", inline=False)
        embed.add_field(name="New Time Mastery",
                        value=f"{user_data['time_mastery']} ({time_mastery_bonus:.2f}x growth boost)", inline=False)
        embed.set_footer(text="Penny - Administrative Stat Override Systems")
        await ctx.send(embed=embed)

    @cmd_debug_group.command(name="additem")
    async def debug_additem_command(self, ctx: commands.Context, target_user: discord.Member, item_id: str,
                                    quantity: int = 1):
        """Adds an item to a user's inventory by ID."""

        if quantity <= 0:
            await ctx.send(
                embed=discord.Embed(title="❌ Invalid Input", description="Quantity must be a positive number.",
                                    color=discord.Color.red()))
            return

        all_items = self.shop_helper.get_all_item_definitions()
        actual_item_key = next((k for k in all_items if k.lower() == item_id.lower()), None)
        item_details = all_items.get(actual_item_key)

        if not actual_item_key or not item_details:
            await ctx.send(embed=discord.Embed(title="❌ Item Not Found",
                                               description=f"The ID `{item_id}` does not correspond to any known item.",
                                               color=discord.Color.red()))
            return

        await self.garden_helper.add_item_to_inventory(target_user.id, actual_item_key, quantity)

        item_name = item_details.get("name", actual_item_key)
        embed = discord.Embed(
            title="⚙️ Debug: Item Addition Protocol",
            description=f"Successfully added **{item_name}** (`{actual_item_key}`) x{quantity} to "
                        f"{target_user.mention}'s inventory.",
            color=discord.Color.green()
        )
        embed.set_footer(text="Penny - Administrative Inventory Override Systems")
        await ctx.send(embed=embed)

    @cmd_debug_group.command(name="removeitem")
    async def debug_removeitem_command(self, ctx: commands.Context, target_user: discord.Member, item_id: str):
        """Removes one instance of an item from a user's inventory."""

        user_data = self.garden_helper.get_user_data(target_user.id)
        inventory = user_data.get("inventory", [])

        item_id_lower = item_id.lower()
        actual_item_key = next((k for k in inventory if k.lower() == item_id_lower), None)

        if actual_item_key:
            await self.garden_helper.remove_item_from_inventory(target_user.id, actual_item_key)

            all_items = self.shop_helper.get_all_item_definitions()
            item_name = all_items.get(actual_item_key, {}).get("name", actual_item_key)

            embed = discord.Embed(
                title="⚙️ Debug: Item Removal Protocol",
                description=f"Successfully removed one **{item_name}** (`{actual_item_key}`) from "
                            f"{target_user.mention}'s inventory.",
                color=discord.Color.orange()
            )
        else:
            embed = discord.Embed(
                title="⚙️ Debug: Item Not Found in Inventory",
                description=f"Item with ID `{item_id}` not found in {target_user.mention}'s inventory. No changes "
                            f"were made.",
                color=discord.Color.yellow()
            )

        embed.set_footer(text="Penny - Administrative Inventory Override Systems")
        await ctx.send(embed=embed)

    @cmd_debug_group.group(name="addplant")
    async def debug_addplant_group(self, ctx: commands.Context):
        """Base command for adding plants to a user's garden."""

        pass

    @debug_addplant_group.command(name="baseplant")
    async def debug_addplant_baseplant(self, ctx: commands.Context, target_user: discord.Member, plot_number: int, *,
                                       plant_id: str):
        """Adds a specific base plant to a user's garden plot."""

        plant_definition = self.plant_helper.get_base_plant_by_id(plant_id)
        if not plant_definition:
            await ctx.send(embed=discord.Embed(title="❌ Plant Not Found",
                                               description=f"The ID `{plant_id}` does not correspond to any known base "
                                                           f"plant.",
                                               color=discord.Color.red()))
            return

        user_data = self.garden_helper.get_user_data(target_user.id)
        garden = user_data["garden"]
        plot_index = plot_number - 1

        if not (0 <= plot_index < 12):
            await ctx.send(
                embed=discord.Embed(title="❌ Invalid Plot", description="Plot number must be between 1 and 12.",
                                    color=discord.Color.red()))
            return
        if not self.garden_helper.is_slot_unlocked(user_data, plot_number):
            await ctx.send(embed=discord.Embed(title="❌ Plot Locked",
                                               description=f"Plot {plot_number} is locked for user "
                                                           f"{target_user.mention}.",
                                               color=discord.Color.red()))
            return
        if garden[plot_index] is not None:
            await ctx.send(embed=discord.Embed(title="❌ Plot Occupied",
                                               description=f"Plot {plot_number} for user {target_user.mention} is "
                                                           f"already occupied.",
                                               color=discord.Color.red()))
            return

        await self.garden_helper.set_garden_plot(target_user.id, plot_index, plant_definition.copy())

        embed = discord.Embed(
            title="⚙️ Debug: Base Plant Added",
            description=f"Successfully added **{plant_definition.get('name', plant_id)}** to plot {plot_number} for "
                        f"{target_user.mention}.",
            color=discord.Color.green()
        )
        embed.set_footer(text="Penny - Administrative Override Systems")
        await ctx.send(embed=embed)

    @debug_addplant_group.command(name="fusion")
    async def debug_addplant_fusion(self, ctx: commands.Context, target_user: discord.Member, plot_number: int, *,
                                    fusion_id: str):
        """Adds a specific fusion plant to a user's garden plot."""
        fusion_definition = self.fusion_helper.find_defined_fusion(fusion_id)
        if not fusion_definition:
            await ctx.send(embed=discord.Embed(title="❌ Fusion Not Found",
                                               description=f"The ID `{fusion_id}` does not correspond to any known "
                                                           f"fusion.",
                                               color=discord.Color.red()))
            return

        user_data = self.garden_helper.get_user_data(target_user.id)
        garden = user_data["garden"]
        plot_index = plot_number - 1

        if not (0 <= plot_index < 12):
            await ctx.send(
                embed=discord.Embed(title="❌ Invalid Plot", description="Plot number must be between 1 and 12.",
                                    color=discord.Color.red()))
            return
        if not self.garden_helper.is_slot_unlocked(user_data, plot_number):
            await ctx.send(embed=discord.Embed(title="❌ Plot Locked",
                                               description=f"Plot {plot_number} is locked for user "
                                                           f"{target_user.mention}.",
                                               color=discord.Color.red()))
            return
        if garden[plot_index] is not None:
            await ctx.send(embed=discord.Embed(title="❌ Plot Occupied",
                                               description=f"Plot {plot_number} for user {target_user.mention} is "
                                                           f"already occupied.",
                                               color=discord.Color.red()))
            return

        plant_to_add = {
            "id": fusion_definition.get("id"),
            "name": fusion_definition.get("name", fusion_id),
            "type": fusion_definition.get("type", "unknown_fusion")
        }
        await self.garden_helper.set_garden_plot(target_user.id, plot_index, plant_to_add)

        embed = discord.Embed(
            title="⚙️ Debug: Fusion Plant Added",
            description=f"Successfully added **{plant_to_add.get('name')}** to plot {plot_number} for "
                        f"{target_user.mention}.",
            color=discord.Color.green()
        )
        embed.set_footer(text="Penny - Administrative Override Systems")
        await ctx.send(embed=embed)

    @debug_addplant_group.command(name="custom")
    async def debug_addplant_custom(self, ctx: commands.Context, target_user: discord.Member, plot_number: int, *,
                                    custom_plant_dict_str: str):
        """Adds a custom plant object (from dict) to a user's garden."""
        try:
            custom_plant_obj = json.loads(custom_plant_dict_str)
            if not isinstance(custom_plant_obj, dict):
                raise ValueError("Input must be a valid JSON dictionary.")
            if not all(k in custom_plant_obj for k in ["id", "name", "type"]):
                await ctx.send(embed=discord.Embed(title="❌ Invalid Dictionary",
                                                   description="The provided dictionary string is missing one or more "
                                                               "required keys (`id`, `name`, `type`).",
                                                   color=discord.Color.red()))
                return
        except json.JSONDecodeError:
            await ctx.send(embed=discord.Embed(title="❌ JSON Error",
                                               description="Failed to parse the provided string as a valid JSON "
                                                           "dictionary.",
                                               color=discord.Color.red()))
            return
        except ValueError as e:
            await ctx.send(embed=discord.Embed(title="❌ Value Error", description=str(e), color=discord.Color.red()))
            return

        user_data = self.garden_helper.get_user_data(target_user.id)
        garden = user_data["garden"]
        plot_index = plot_number - 1

        if not (0 <= plot_index < 12):
            await ctx.send(
                embed=discord.Embed(title="❌ Invalid Plot", description="Plot number must be between 1 and 12.",
                                    color=discord.Color.red()))
            return
        if not self.garden_helper.is_slot_unlocked(user_data, plot_number):
            await ctx.send(embed=discord.Embed(title="❌ Plot Locked",
                                               description=f"Plot {plot_number} is locked for user "
                                                           f"{target_user.mention}.",
                                               color=discord.Color.red()))
            return
        if garden[plot_index] is not None:
            await ctx.send(embed=discord.Embed(title="❌ Plot Occupied",
                                               description=f"Plot {plot_number} for user {target_user.mention} is "
                                                           f"already occupied.",
                                               color=discord.Color.red()))
            return

        await self.garden_helper.set_garden_plot(target_user.id, plot_index, custom_plant_obj)

        embed = discord.Embed(
            title="⚙️ Debug: Custom Plant Added",
            description=f"Successfully added custom plant **{custom_plant_obj.get('name')}** to plot {plot_number} "
                        f"for {target_user.mention}.",
            color=discord.Color.green()
        )
        embed.add_field(name="Data Added", value=f"```json\n{json.dumps(custom_plant_obj, indent=2)}\n```")
        embed.set_footer(text="Penny - Administrative Override Systems")
        await ctx.send(embed=embed)

    @cmd_debug_group.command(name="speed")
    async def debug_speed_command(self, ctx: commands.Context, minutes: Optional[int] = None):
        """Sets or displays the global plant growth duration in minutes."""
        current_duration = self.data["flags"].get("plant_growth_duration_minutes", 240)

        if minutes is None:
            embed = discord.Embed(
                title="⚙️ Debug: Plant Growth Speed Setting",
                description=f"The current global plant growth duration is set to **{current_duration} minutes**.",
                color=discord.Color.blue()
            )
            embed.set_footer(text=f"Use {ctx.prefix}debug speed <minutes> to change it")
            await ctx.send(embed=embed)
            return

        if minutes <= 0:
            await ctx.send(
                embed=discord.Embed(title="❌ Invalid Input", description="Growth duration must be a positive integer.",
                                    color=discord.Color.red()))
            return

        self.data["flags"]["plant_growth_duration_minutes"] = minutes
        await self.config.flags.set(self.data["flags"])

        embed = discord.Embed(
            title="✅ Debug: Plant Growth Speed Updated",
            description=f"Global plant growth duration has been updated from {current_duration} minutes to "
                        f"**{minutes} minutes**.",
            color=discord.Color.green()
        )
        embed.set_footer(text="Penny - Administrative Growth Cycle Configuration")
        await ctx.send(embed=embed)

    @cmd_debug_group.command(name="replenishstock")
    async def debug_replenishstock_command(self, ctx: commands.Context, item_id: str, amount: int = 1):
        """Adds stock to a limited item in Rux's shop."""
        item_details = self.data_loader.rux_shop_data.get(item_id)
        if not item_details or item_details.get("category") != "limited":
            embed = discord.Embed(title="❌ Invalid Item",
                                  description=f"'{item_id}' is not a valid, limited-stock item in rux_shop.json.",
                                  color=discord.Color.red())
            await ctx.send(embed=embed)
            return

        if amount <= 0:
            await ctx.send(
                embed=discord.Embed(title="❌ Invalid Input", description="Amount must be a positive integer.",
                                    color=discord.Color.red()))
            return

        stock_key = f"{item_id}_stock"
        current_stock = self.data["flags"].get(stock_key, 0)
        new_stock = current_stock + amount
        self.data["flags"][stock_key] = new_stock
        await self.config.flags.set(self.data["flags"])

        embed = discord.Embed(
            title="⚙️ Debug: Stock Replenishment Protocol",
            description=f"Successfully replenished stock for **{item_details.get('name', item_id)}** (`{item_id}`).",
            color=discord.Color.green()
        )
        embed.add_field(name="Amount Added", value=f"+{amount}", inline=True)
        embed.add_field(name="Previous Stock", value=f"{current_stock}", inline=True)
        embed.add_field(name="New Stock", value=f"{new_stock}", inline=True)
        embed.set_footer(text="Penny - Administrative Stock Management Systems")
        await ctx.send(embed=embed)

    @cmd_debug_group.command(name="refreshpennyshop")
    async def debug_refreshpennyshop_command(self, ctx: commands.Context):
        """Forces an immediate refresh of Penny's Treasures shop stock."""
        await ctx.send(embed=discord.Embed(title="⚙️ Debug: Penny's Shop Refresh",
                                           description="Forcing an immediate refresh of Penny's Treasures stock...",
                                           color=discord.Color.orange()))

        await self.shop_helper.refresh_penny_shop_if_needed(self.logger, force=True)
        await self.config.flags.set(self.data["flags"])

        await self.logger.log_to_discord(f"Debug: Penny's Shop manually refreshed by {ctx.author.name}.", "INFO")
        await ctx.send(embed=discord.Embed(title="✅ Debug: Penny's Shop Refreshed",
                                           description="Penny's Treasures stock has been successfully refreshed with "
                                                       "new items.",
                                           color=discord.Color.green()))

    @cmd_debug_group.command(name="pennyshoprefresh")
    async def debug_pennyshoprefresh_command(self, ctx: commands.Context, interval_hours: Optional[int] = None):
        """Sets or displays the Penny's Shop refresh interval in hours."""
        current_interval = self.data["flags"].get("treasure_shop_refresh_interval_hours", 1)

        if interval_hours is None:
            embed = discord.Embed(
                title="⚙️ Debug: Penny's Shop Refresh Interval",
                description=f"The current refresh interval for Penny's Treasures is **{current_interval} hours**.\n"
                            f"Valid intervals are positive numbers that divide 24 evenly (1, 2, 3, 4, 6, 8, 12, 24).",
                color=discord.Color.blue()
            )
            embed.set_footer(text=f"Use {ctx.prefix}debug pennyshoprefresh <hours> to change it")
            await ctx.send(embed=embed)
            return

        if interval_hours <= 0 or 24 % interval_hours != 0:
            embed = discord.Embed(
                title="❌ Invalid Interval",
                description="The interval must be a positive number of hours that divides 24 evenly (e.g., 1, 2, 3, 4, "
                            "6, 8, 12, 24).",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return

        self.data["flags"]["treasure_shop_refresh_interval_hours"] = interval_hours
        await self.config.flags.set(self.data["flags"])

        embed = discord.Embed(
            title="✅ Debug: Penny's Shop Interval Updated",
            description=f"The refresh interval for Penny's Treasures has been changed from {current_interval} hours "
                        f"to **{interval_hours} hours**.",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)

    @cmd_debug_group.command(name="refreshdaveshop")
    async def debug_refreshdaveshop_command(self, ctx: commands.Context):
        """Forces an immediate refresh of Crazy Dave's shop stock."""
        await ctx.send(embed=discord.Embed(title="⚙️ Debug: Dave's Shop Refresh",
                                           description="Forcing an immediate refresh of Crazy Dave's Twiddydinkies "
                                                       "stock...",
                                           color=discord.Color.orange()))

        await self.shop_helper.refresh_dave_shop_if_needed(self.logger, force=True)
        await self.config.flags.set(self.data["flags"])

        await self.logger.log_to_discord(f"Debug: Dave's Shop manually refreshed by {ctx.author.name}.", "INFO")
        await ctx.send(embed=discord.Embed(title="✅ Debug: Dave's Shop Refreshed",
                                           description="Crazy Dave's stock has been successfully refreshed.",
                                           color=discord.Color.green()))

    @cmd_debug_group.command(name="unlockbg")
    async def debug_unlockbg_command(self, ctx: commands.Context, target_user: discord.Member, *, background_name: str):
        """Unlocks a specific garden background for a user."""

        target_bg_def = None
        for bg_def in self.background_helper.all_backgrounds:
            if bg_def['name'].lower() == background_name.lower():
                target_bg_def = bg_def
                break

        if not target_bg_def:
            await ctx.send(embed=discord.Embed(
                title="❌ Background Not Found",
                description=f"No background with the name '{background_name}' could be found in the loaded data.",
                color=discord.Color.red()
            ))
            return

        user_data = self.garden_helper.get_user_data(target_user.id)
        unlocked_bgs = user_data.get("unlocked_backgrounds", ["default"])
        bg_id_to_unlock = target_bg_def['id']

        if bg_id_to_unlock in unlocked_bgs:
            await ctx.send(embed=discord.Embed(
                title="⚙️ Debug: Background Already Unlocked",
                description=f"User {target_user.mention} already has the **{target_bg_def['name']}** background "
                            f"unlocked.",
                color=discord.Color.blue()
            ))
            return

        await self.garden_helper.add_unlocked_background(target_user.id, bg_id_to_unlock)

        embed = discord.Embed(
            title="✅ Debug: Background Unlocked",
            description=f"Successfully unlocked the **{target_bg_def['name']}** background for {target_user.mention}.",
            color=discord.Color.green()
        )
        embed.set_footer(text="Penny - Administrative Override Systems")
        await ctx.send(embed=embed)
