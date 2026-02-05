"""Pipeline configuration models."""

from pathlib import Path

from pydantic import BaseModel, Field


class PipelineConfig(BaseModel):
    """Configuration for the EBD pack building pipeline."""

    # Input/output paths
    input_tarball: Path | None = Field(
        default=None, description="Path to input eBird tarball (.tar)"
    )
    parquet_dir: Path | None = Field(default=None, description="Directory for converted parquet")
    sorted_dir: Path | None = Field(
        default=None, description="Directory for geographically sorted parquet"
    )
    partitioned_dir: Path | None = Field(
        default=None, description="Directory for H3-partitioned parquet"
    )
    packs_dir: Path | None = Field(
        default=None, description="Directory for output SQLite packs"
    )

    # Step parameters
    chunk_size: int = Field(default=1_000_000, description="Rows per parquet chunk")
    memory_limit: str = Field(default="24GB", description="DuckDB memory limit")
    max_temp_size: str = Field(default="200GiB", description="Max temp directory size")
    boundary_resolution: int = Field(default=4, description="H3 resolution for boundary cells")
    total_workers: int = Field(default=1, description="Total parallel workers for builds")
    worker_id: int = Field(default=0, description="This worker's ID (0-indexed)")

    # State management
    state_dir: Path | None = Field(default=None, description="Directory for pipeline state")
    pipeline_id: str = Field(default="ebd-pipeline", description="Unique pipeline identifier")

    model_config = {"extra": "forbid"}


# Frequency thresholds for confidence tiers
TIER_THRESHOLDS = {
    "common": 0.10,
    "uncommon": 0.01,
    "rare": 0.001,
    "vagrant": 0.0,
}

# Base confidence boosts by tier
TIER_BOOSTS = {
    "common": 1.5,
    "uncommon": 1.2,
    "rare": 1.0,
    "vagrant": 0.8,
}

# Resolution penalty multipliers (coarser = less confident)
RESOLUTION_PENALTIES = {
    5: 1.0,  # No penalty - finest resolution
    4: 0.8,  # 20% penalty - medium resolution
    2: 0.5,  # 50% penalty - coarse fallback
}

# Data resolutions to compute (finest to coarsest)
DATA_RESOLUTIONS = [5, 4, 2]
