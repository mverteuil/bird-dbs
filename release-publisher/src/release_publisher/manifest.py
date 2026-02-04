"""Pack registry parsing and validation."""

import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    """Geographic bounding box for a region."""

    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float


class RegionInfo(BaseModel):
    """Region definition from pack registry."""

    region_id: str
    release_name: str = Field(..., description="GitHub release tag name")
    h3_cells: list[str]
    pack_count: int
    total_size_mb: float
    resolution: int
    center: dict[str, float]
    bbox: BoundingBox
    download_url: str | None = Field(None, description="GitHub release asset download URL")


class PackRegistry(BaseModel):
    """Complete pack registry structure."""

    version: str
    generated_at: datetime
    total_regions: int
    total_packs: int
    regions: list[RegionInfo]

    @property
    def release_names(self) -> list[str]:
        """Get all unique release names."""
        return [region.release_name for region in self.regions]

    def get_region_by_release(self, release_name: str) -> RegionInfo | None:
        """Find region by release name."""
        for region in self.regions:
            if region.release_name == release_name:
                return region
        return None


def load_registry(registry_path: Path) -> PackRegistry:
    """Load and validate pack registry from JSON file.

    Args:
        registry_path: Path to pack_registry.json

    Returns:
        Validated PackRegistry

    Raises:
        FileNotFoundError: If registry doesn't exist
        json.JSONDecodeError: If registry is invalid JSON
        pydantic.ValidationError: If registry structure is invalid
    """
    with open(registry_path) as f:
        data = json.load(f)
    return PackRegistry(**data)
