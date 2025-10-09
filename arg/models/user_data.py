from dataclasses import dataclass, field
from typing import Tuple, Optional, List, Union

# --- Instance Representations ---

@dataclass
class PlantedSeedling:
    """Represents an instance of a seedling growing in a garden. Mutable."""
    id: str
    progress: float = 0.0
    notification_channel_id: Optional[int] = None
    type: str = "seedling"

    @property
    def name(self) -> str:
        # The name of a planted seedling is always its ID.
        return self.id

@dataclass(frozen=True)
class PlantedPlant:
    """Represents an instance of a mature plant in a garden or storage. Immutable."""
    id: str
    name: str
    type: str

# A type hint for clarity, representing anything that can be in a garden/storage slot.
SlotItem = Union[PlantedSeedling, PlantedPlant, None]


# --- Internal Mutable Model ---

@dataclass
class UserProfile:
    """
    The internal, MUTABLE representation of a user's data.
    This is the "working copy" used exclusively by GardenHelper.
    """
    user_id: int
    balance: int = 0
    sun_mastery: int = 0
    time_mastery: int = 0
    last_daily: Optional[str] = None
    active_background: str = "default"
    garden: List[SlotItem] = field(default_factory=lambda: [None] * 12)
    storage_shed: List[Optional[PlantedPlant]] = field(default_factory=lambda: [None] * 8)
    inventory: List[str] = field(default_factory=list)
    discovered_fusions: List[str] = field(default_factory=list)
    unlocked_backgrounds: List[str] = field(default_factory=lambda: ["default"])


# --- External Immutable View ---

@dataclass(frozen=True)
class UserProfileView:
    """
    The external, IMMUTABLE, read-only view of a user's profile.
    This is the safe "snapshot" given to the rest of the application.
    """
    user_id: int
    balance: int
    sun_mastery: int
    time_mastery: int
    last_daily: Optional[str]
    active_background: str
    garden: Tuple[SlotItem, ...]
    storage_shed: Tuple[Optional[PlantedPlant], ...]
    inventory: Tuple[str, ...]
    discovered_fusions: Tuple[str, ...]
    unlocked_backgrounds: Tuple[str, ...]