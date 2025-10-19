from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Tuple, Optional, List, Union, Dict


@dataclass
class PlantedSeedling:
    """Represents an instance of a seedling growing in a garden."""
    id: str
    progress: float = 0.0
    notification_channel_id: Optional[int] = None
    type: str = "seedling"

    @property
    def name(self) -> str:
        return self.id

@dataclass(frozen=True)
class PlantedPlant:
    """Represents an instance of a mature plant in a garden or storage."""
    id: str
    name: str
    type: str


SlotItem = Union[PlantedSeedling, PlantedPlant, None]

@dataclass
class UserProfile:
    """The internal representation of a user's data."""
    user_id: int
    balance: int = 0
    sun_mastery: int = 0
    time_mastery: int = 0
    last_daily: Optional[str] = None
    active_background: str = "default"
    garden: List[SlotItem] = field(default_factory=lambda: [None] * 12)
    storage_shed: List[Optional[PlantedPlant]] = field(default_factory=lambda: [None] * 8)
    inventory: Dict[str, int] = field(default_factory=dict)
    discovered_fusions: List[str] = field(default_factory=list)
    unlocked_backgrounds: List[str] = field(default_factory=lambda: ["default"])


# --- External Immutable View ---

@dataclass(frozen=True)
class UserProfileView:
    """The external read-only view of a user's profile."""
    user_id: int
    balance: int
    sun_mastery: int
    time_mastery: int
    last_daily: Optional[str]
    active_background: str
    garden: Tuple[SlotItem, ...]
    storage_shed: Tuple[Optional[PlantedPlant], ...]
    inventory: MappingProxyType[str, int]
    discovered_fusions: Tuple[str, ...]
    unlocked_backgrounds: Tuple[str, ...]