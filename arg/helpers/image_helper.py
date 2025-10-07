import io
import pathlib
from typing import Any, Dict, List, Optional, Tuple

import discord

from helpers import LoggingHelper

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    Image, ImageDraw, ImageFont = None, None, None


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