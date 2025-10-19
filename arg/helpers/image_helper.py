import io
import pathlib
from typing import Dict, Optional, Tuple, Set

import discord

from .logging_helper import LoggingHelper
from ..models import UserProfileView, PlantedSeedling

try:
    from PIL import Image, ImageDraw, ImageFont

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    Image, ImageDraw, ImageFont = None, None, None


class ImageHelper:
    """Handles PIL-based image generation for the cog."""

    _PLANT_IMAGE_ASSET_SIZE: int = 128
    _PLANT_SPACING: int = 20
    _GRID_OFFSET_X: int = 70
    _GRID_OFFSET_Y: int = 50
    _GRID_COLUMNS: int = 4
    _GRID_ROWS: int = 3
    PLANT_SLOT_COORDINATES: list[Tuple[int, int]] = []

    def __init__(self, data_path_obj: pathlib.Path, logger: LoggingHelper):
        if not PIL_AVAILABLE:
            logger.init_log("Pillow (PIL) not found. Image generation will be disabled.", "CRITICAL")

        self.data_path = data_path_obj
        self.logger = logger
        self._is_ready = False

        self.image_cache: Dict[str, Image.Image] = {}
        self.progress_font: Optional[ImageFont.FreeTypeFont] = None

        for r_idx in range(self._GRID_ROWS):
            for c_idx in range(self._GRID_COLUMNS):
                x = self._GRID_OFFSET_X + c_idx * (self._PLANT_IMAGE_ASSET_SIZE + self._PLANT_SPACING)
                y = self._GRID_OFFSET_Y + r_idx * (self._PLANT_IMAGE_ASSET_SIZE + self._PLANT_SPACING)
                self.PLANT_SLOT_COORDINATES.append((x, y))

    def _sanitize_id_for_filename(self, plant_id: str) -> str:
        return plant_id.replace(" ", "_")

    def get_image_file_for_plant(self, plant_id: str) -> Optional[discord.File]:
        if not plant_id:
            return None

        sanitized_filename = f"{self._sanitize_id_for_filename(plant_id)}.png"

        if cached_image := self.image_cache.get(sanitized_filename):
            try:
                buffer = io.BytesIO()
                cached_image.save(buffer, format='PNG')
                buffer.seek(0)
                return discord.File(buffer, filename=sanitized_filename)
            except Exception as e:
                self.logger.log_to_discord(
                    f"DEBUG: Failed to create discord.File from cached image {sanitized_filename}: {e}", "WARNING")

        return None

    def load_assets(self):
        if not PIL_AVAILABLE:
            return

        self.image_cache.clear()
        image_dir = self.data_path / "images"

        if not image_dir.is_dir():
            self.logger.init_log(f"Image asset directory not found at {image_dir}. Image generation disabled.",
                                 "CRITICAL")
            self._is_ready = False
            return

        loaded_count = 0
        for image_path in image_dir.glob("*.png"):
            try:
                img = Image.open(image_path).convert("RGBA")
                self.image_cache[image_path.name] = img
                loaded_count += 1
            except Exception as e:
                self.logger.init_log(f"Failed to load image asset '{image_path.name}': {e}", "ERROR")

        self.logger.init_log(f"Loaded {loaded_count} image assets into memory cache.", "INFO")

        try:
            font_path = self.data_path / "font" / "Roboto-Medium.ttf"
            self.progress_font = ImageFont.truetype(str(font_path), 30)
        except IOError:
            self.logger.init_log("Roboto-Medium.ttf not found. Falling back to default font.", "WARNING")
            self.progress_font = ImageFont.load_default()

        if "garden.png" in self.image_cache:
            self._is_ready = True
            self.logger.init_log("Essential image assets are cached. Image helper is ready.", "INFO")
        else:
            self._is_ready = False
            self.logger.init_log("Base 'garden.png' asset failed to load. Image generation disabled.", "CRITICAL")

    def _draw_progress_on_seedling(self, seedling_image: Image.Image, progress: float) -> Image.Image:
        img_copy = seedling_image.copy()
        draw = ImageDraw.Draw(img_copy)
        progress_text = f"{progress:.1f}%"
        font = self.progress_font

        bbox = draw.textbbox((0, 0), progress_text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = (self._PLANT_IMAGE_ASSET_SIZE - text_width) / 2
        y = self._PLANT_IMAGE_ASSET_SIZE - text_height - 15

        draw.text((x, y), progress_text, font=font, fill=(255, 255, 255, 255), stroke_width=2,
                  stroke_fill=(0, 0, 0, 255))
        return img_copy

    async def generate_garden_image(
            self, profile: UserProfileView, unlocked_slots: Set[int], background_filename: str = "garden.png"
    ) -> Optional[discord.File]:
        """Generates a complete garden profile image for a user using their UserProfileView."""

        if not self._is_ready:
            return None

        base_image_to_use = self.image_cache.get(background_filename) or self.image_cache.get("garden.png")
        if not base_image_to_use:
            return None

        locked_slot_image = self.image_cache.get("locked_slot.png")
        empty_slot_image = self.image_cache.get("empty_slot.png")
        default_seedling_image = self.image_cache.get("Seedling.png")

        garden_image = base_image_to_use.copy()
        garden_slots = profile.garden

        for i, slot_content in enumerate(garden_slots):
            plant_asset_to_render = None
            slot_num_1_indexed = i + 1

            if slot_num_1_indexed not in unlocked_slots:
                plant_asset_to_render = locked_slot_image
            elif slot_content is None:
                plant_asset_to_render = empty_slot_image
            else:
                plant_id = slot_content.id
                sanitized_filename = f"{self._sanitize_id_for_filename(plant_id)}.png"

                if isinstance(slot_content, PlantedSeedling):
                    template_to_use = self.image_cache.get(sanitized_filename) or default_seedling_image
                    if template_to_use:
                        plant_asset_to_render = self._draw_progress_on_seedling(template_to_use, slot_content.progress)
                else:
                    plant_asset_to_render = self.image_cache.get(sanitized_filename)

            if plant_asset_to_render:
                slot_base_x, slot_base_y = self.PLANT_SLOT_COORDINATES[i]
                garden_image.paste(plant_asset_to_render, (slot_base_x, slot_base_y), plant_asset_to_render)

        img_byte_arr = io.BytesIO()
        garden_image.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        return discord.File(img_byte_arr, filename="garden_profile.png")