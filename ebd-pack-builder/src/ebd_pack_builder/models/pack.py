"""Pack and region manifest models."""

from pydantic import BaseModel, Field


class BoundaryCell(BaseModel):
    """A single H3 boundary cell with statistics."""

    h3_cell: str = Field(description="H3 cell ID in hex format")
    center_lat: float = Field(description="Cell center latitude")
    center_lon: float = Field(description="Cell center longitude")
    unique_checklists: int = Field(description="Number of unique checklists")
    complete_checklists: int = Field(description="Number of complete checklists")
    total_observations: int = Field(description="Total observation count")
    species_count: int = Field(description="Number of unique species")
    estimated_pack_size_mb: float = Field(description="Estimated pack size in MB")
    recommended_data_resolution: int = Field(description="Recommended H3 data resolution")

    model_config = {"extra": "forbid"}


class RegionPack(BaseModel):
    """A region pack definition containing multiple boundary cells."""

    region_id: str = Field(description="Unique region identifier")
    boundary_cells: list[str] = Field(description="List of boundary cell IDs")
    center_lat: float = Field(default=0.0)
    center_lon: float = Field(default=0.0)

    model_config = {"extra": "forbid"}


class RegionBuildResult(BaseModel):
    """Result of building a region pack."""

    region_id: str
    boundary_cells: list[str]
    boundary_cell_count: int
    data_resolutions: list[int]
    center_lat: float
    center_lon: float
    size_mb: float
    num_cells_res5: int
    num_cells_res4: int
    num_cells_res2: int
    total_species: int
    grid_species_rows: int
    monthly_rows: int

    model_config = {"extra": "forbid"}


class DensityReport(BaseModel):
    """Density report for boundary cells."""

    resolution: int = Field(description="H3 boundary resolution")
    total_cells: int = Field(description="Total number of cells with data")
    total_checklists: int = Field(description="Total checklist count")
    total_observations: int = Field(description="Total observation count")
    cells: list[BoundaryCell] = Field(description="Cell data sorted by checklist count")

    model_config = {"extra": "forbid"}


class SizeManifestCell(BaseModel):
    """Size information for a single boundary cell."""

    boundary_cell: str
    size_mb: float
    source_region: str | None = None

    model_config = {"extra": "forbid"}


class SizeManifest(BaseModel):
    """Size manifest mapping boundary cells to actual pack sizes."""

    version: str = Field(default="1.0")
    description: str = Field(
        default="Size manifest for pack-planner, generated from actual build sizes"
    )
    stats: dict = Field(default_factory=dict)
    cells: list[SizeManifestCell] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class PackManifest(BaseModel):
    """Manifest for all region packs."""

    regions: list[dict] = Field(default_factory=list, description="Region definitions")
    total_regions: int = Field(default=0)
    data_resolutions: list[int] = Field(default_factory=list)
    resolution_penalties: dict[str, float] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}
