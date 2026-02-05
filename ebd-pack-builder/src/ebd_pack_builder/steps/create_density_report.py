"""Create density report from partition discovery output.

Bridges the partition_by_boundary.py discovery output to the
pack-planner input format.
"""

import json
from pathlib import Path

import h3


def estimate_pack_size_mb(checklist_count: int, species_count: int) -> float:
    """Estimate pack size based on checklist and species counts.

    Based on Toronto pack benchmark:
    - 551,739 checklists, 710 species -> 26.56 MB
    - Primary driver is checklist count (monthly frequency data)

    Formula: base + (checklists * species * bytes_per_entry) / 1MB
    Simplified: ~0.05 MB per 1000 checklists (empirical)
    """
    # Empirical formula based on Toronto pack
    # Toronto: 551K checklists -> 26.56 MB -> ~0.048 MB per 1000 checklists
    base_size = 0.5  # Minimum pack overhead
    size_per_1k_checklists = 0.05

    estimated = base_size + (checklist_count / 1000) * size_per_1k_checklists

    # Cap at reasonable maximum (very dense areas)
    return min(estimated, 200.0)


def create_density_report(
    boundary_cells_path: Path,
    output_path: Path,
) -> dict:
    """Create density report from boundary cells discovery file.

    Args:
        boundary_cells_path: Path to boundary_cells.json from partition discovery
        output_path: Output path for density report JSON

    Returns:
        The density report dict
    """
    with open(boundary_cells_path) as f:
        discovery = json.load(f)

    cells = []
    for cell_data in discovery["cells"]:
        h3_cell = cell_data["boundary_cell"]

        # Get center coordinates from H3
        center_lat, center_lon = h3.cell_to_latlng(h3_cell)

        # Calculate estimated pack size
        estimated_size = estimate_pack_size_mb(
            cell_data["checklist_count"], cell_data["species_count"]
        )

        # Data resolution is always 5 (finest tier in DATA_RESOLUTIONS)
        # The database uses fixed tiers [5, 4, 2] with fallback, not per-cell resolution
        recommended_res = 5

        cells.append(
            {
                "h3_cell": h3_cell,
                "center_lat": center_lat,
                "center_lon": center_lon,
                "unique_checklists": cell_data["checklist_count"],
                "complete_checklists": cell_data["checklist_count"],
                "total_observations": cell_data["observation_count"],
                "species_count": cell_data["species_count"],
                "estimated_pack_size_mb": round(estimated_size, 3),
                "recommended_data_resolution": recommended_res,
            }
        )

    # Sort by checklist count descending (most data first)
    cells.sort(key=lambda x: x["unique_checklists"], reverse=True)

    density_report = {
        "resolution": 4,
        "total_cells": len(cells),
        "total_checklists": sum(c["unique_checklists"] for c in cells),
        "total_observations": sum(c["total_observations"] for c in cells),
        "cells": cells,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(density_report, f, indent=2)

    # Print summary
    print(f"Density Report Summary:")
    print(f"  Total cells: {density_report['total_cells']:,}")
    print(f"  Total checklists: {density_report['total_checklists']:,}")
    print(f"  Total observations: {density_report['total_observations']:,}")
    print(f"  Output: {output_path}")

    # Coverage statistics
    cells_with_1k = sum(1 for c in cells if c["unique_checklists"] >= 1000)
    cells_with_10k = sum(1 for c in cells if c["unique_checklists"] >= 10000)
    cells_with_100k = sum(1 for c in cells if c["unique_checklists"] >= 100000)

    print(f"\nCoverage by checklist threshold:")
    print(f"  >= 1,000 checklists: {cells_with_1k:,} cells")
    print(f"  >= 10,000 checklists: {cells_with_10k:,} cells")
    print(f"  >= 100,000 checklists: {cells_with_100k:,} cells")

    # Estimated total size
    total_size_mb = sum(c["estimated_pack_size_mb"] for c in cells)
    print(f"\nEstimated total pack size: {total_size_mb / 1024:.2f} GB")

    return density_report
