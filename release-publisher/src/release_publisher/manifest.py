"""Pack manifest parsing and validation."""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class PackInfo(BaseModel):
    """Individual pack within a region."""

    pack_id: str
    boundary_cell: str
    boundary_resolution: int
    data_resolution: int
    center_lat: float
    center_lon: float
    estimated_size_mb: float
    total_checklists: int


class RegionInfo(BaseModel):
    """Region definition from pack manifest."""

    h3_cells: list[str]
    packs: list[PackInfo]
    size_mb: float
    pack_count: int
    center: dict[str, float]
    region_id: str
    release_name: str = Field(..., description="GitHub release tag name")
    download_url: str | None = Field(None, description="GitHub release asset download URL")


class PackManifest(BaseModel):
    """Complete pack manifest structure."""

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


def load_manifest(manifest_path: Path) -> PackManifest:
    """Load and validate pack manifest from JSON file.

    Args:
        manifest_path: Path to pack_manifest.json

    Returns:
        Validated PackManifest

    Raises:
        FileNotFoundError: If manifest doesn't exist
        json.JSONDecodeError: If manifest is invalid JSON
        pydantic.ValidationError: If manifest structure is invalid
    """
    with open(manifest_path) as f:
        data = json.load(f)
    return PackManifest(**data)
