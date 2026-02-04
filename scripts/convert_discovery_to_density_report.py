#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "h3>=3.7.0",
# ]
# ///
"""
Convert partition discovery output to density report format for pack-planner.

This bridges the partition_by_boundary.py discovery output to the
pack-planner input format, enabling the existing manifest pipeline.

Usage:
    uv run convert_discovery_to_density_report.py \
        --input /Volumes/Lightroom/ebird_partitioned/boundary_cells.json \
        --output /Volumes/Lightroom/ebird_partitioned/density_report_res4.json
"""

import argparse
import json
from pathlib import Path

import h3


def estimate_pack_size_mb(checklist_count: int, species_count: int) -> float:
    """
    Estimate pack size based on checklist and species counts.

    Based on Toronto pack benchmark:
    - 551,739 checklists, 710 species → 26.56 MB
    - Primary driver is checklist count (monthly frequency data)

    Formula: base + (checklists * species * bytes_per_entry) / 1MB
    Simplified: ~0.05 MB per 1000 checklists (empirical)
    """
    # Empirical formula based on Toronto pack
    # Toronto: 551K checklists → 26.56 MB → ~0.048 MB per 1000 checklists
    base_size = 0.5  # Minimum pack overhead
    size_per_1k_checklists = 0.05

    estimated = base_size + (checklist_count / 1000) * size_per_1k_checklists

    # Cap at reasonable maximum (very dense areas)
    return min(estimated, 200.0)


def convert_to_density_report(input_path: Path, output_path: Path) -> dict:
    """Convert boundary_cells.json to density report format."""

    with open(input_path) as f:
        discovery = json.load(f)

    cells = []
    for cell_data in discovery["cells"]:
        h3_cell = cell_data["boundary_cell"]

        # Get center coordinates from H3
        center_lat, center_lon = h3.cell_to_latlng(h3_cell)

        # Calculate estimated pack size
        estimated_size = estimate_pack_size_mb(
            cell_data["checklist_count"],
            cell_data["species_count"]
        )

        # Determine recommended data resolution based on density
        # Higher density → higher resolution for more detail
        checklists = cell_data["checklist_count"]
        if checklists >= 100000:
            recommended_res = 7
        elif checklists >= 10000:
            recommended_res = 6
        elif checklists >= 1000:
            recommended_res = 5
        else:
            recommended_res = 4

        cells.append({
            "h3_cell": h3_cell,
            "center_lat": center_lat,
            "center_lon": center_lon,
            "unique_checklists": cell_data["checklist_count"],
            "complete_checklists": cell_data["checklist_count"],  # Used by pack-planner
            "total_observations": cell_data["observation_count"],
            "species_count": cell_data["species_count"],
            "estimated_pack_size_mb": round(estimated_size, 3),
            "recommended_data_resolution": recommended_res,
        })

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

    return density_report


def main():
    parser = argparse.ArgumentParser(
        description="Convert partition discovery to density report format",
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Input boundary_cells.json from partition discovery",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output density report JSON",
    )

    args = parser.parse_args()

    if not args.input.exists():
        print(f"Error: Input file not found: {args.input}")
        return 1

    print(f"Converting {args.input} to density report format...")
    report = convert_to_density_report(args.input, args.output)

    print(f"\nDensity Report Summary:")
    print(f"  Total cells: {report['total_cells']:,}")
    print(f"  Total checklists: {report['total_checklists']:,}")
    print(f"  Total observations: {report['total_observations']:,}")
    print(f"  Output: {args.output}")

    # Coverage statistics
    cells_with_1k = sum(1 for c in report["cells"] if c["unique_checklists"] >= 1000)
    cells_with_10k = sum(1 for c in report["cells"] if c["unique_checklists"] >= 10000)
    cells_with_100k = sum(1 for c in report["cells"] if c["unique_checklists"] >= 100000)

    print(f"\nCoverage by checklist threshold:")
    print(f"  >= 1,000 checklists: {cells_with_1k:,} cells")
    print(f"  >= 10,000 checklists: {cells_with_10k:,} cells")
    print(f"  >= 100,000 checklists: {cells_with_100k:,} cells")

    # Estimated total size
    total_size_mb = sum(c["estimated_pack_size_mb"] for c in report["cells"])
    print(f"\nEstimated total pack size: {total_size_mb / 1024:.2f} GB")

    return 0


if __name__ == "__main__":
    exit(main())
