from dataclasses import dataclass, field
from typing import Tuple, Optional

@dataclass(frozen=True)
class BasePlant:
    """Represents a single plant definition from base_plants.json."""
    id: str
    name: str
    type: str
    category: str
    shop: bool = False

@dataclass(frozen=True)
class SeedlingDefinition:
    """Represents a seedling definition from seedlings.json."""
    id: str
    category: str
    cost: int
    stock: int
    growth_multiplier: float = 1.0

@dataclass(frozen=True)
class FusionRecipe:
    """Represents a fusion recipe from fusions.json."""
    id: str
    name: str
    type: str
    recipe: Tuple[str, ...]
    visibility: str = "visible"

@dataclass(frozen=True)
class Background:
    """Represents a garden background from backgrounds.json."""
    id: str
    name: str
    image_file: str
    required_fusions: Tuple[str, ...] = field(default_factory=tuple)

@dataclass(frozen=True)
class ShopItemDefinition:
    """A generic definition for an item sold in any shop."""
    id: str
    name: str
    cost: int
    description: str = ""
    category: Optional[str] = None
    requirements: Tuple[str, ...] = field(default_factory=tuple)
    stock: Optional[int] = None
    type: Optional[str] = None