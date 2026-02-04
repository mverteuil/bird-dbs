#!/usr/bin/env -S uv run
# /// script
# dependencies = []
# ///
"""
Create size manifest from built region packs.

This script extracts actual sizes from built packs and creates a manifest
that maps each boundary cell to its proportional size. This manifest is
required by pack-planner for size-aware region partitioning.

Workflow:
1. Run build_packs_from_partitions.py with initial (oversized) regions
2. Run this script to create size manifest from actual build sizes
3. Re-run pack-planner with --size-manifest to create properly sized regions
4. Rebuild packs with new regions

Usage:
    uv run create_size_manifest.py \
        --packs-dir /Volumes/Lightroom/region_packs \
        --pack-manifest /Volumes/Lightroom/ebird_partitioned/pack_manifest.json \
        --output /Volumes/Lightroom/ebird_partitioned/size_manifest.json
"""

import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Create size manifest from built region packs"
    )
    parser.add_argument(
        "--packs-dir",
        type=Path,
        required=True,
        help="Directory containing built .db pack files",
    )
    parser.add_argument(
        "--pack-manifest",
        type=Path,
        required=True,
        help="Pack manifest JSON with region -> boundary cell mappings",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output path for size manifest JSON",
    )

    args = parser.parse_args()

    # Load pack manifest to get boundary cells per region
    print(f"Loading pack manifest from: {args.pack_manifest}")
    with open(args.pack_manifest) as f:
        manifest = json.load(f)

    # Calculate size per boundary cell from actual builds
    cells = []
    total_size_mb = 0
    regions_processed = 0
    cells_processed = 0

    for region in manifest.get("regions", []):
        region_id = region["region_id"]
        db_path = args.packs_dir / f"{region_id}.db"

        if not db_path.exists():
            print(f"  Warning: {region_id}.db not found, skipping")
            continue

        # Get actual size
        actual_size_mb = os.path.getsize(db_path) / (1024 * 1024)

        # Get boundary cells from packs
        boundary_cells = [p["boundary_cell"] for p in region.get("packs", [])]
        cell_count = len(boundary_cells)

        if cell_count == 0:
            continue

        # Distribute size evenly across cells
        size_per_cell = actual_size_mb / cell_count

        for cell in boundary_cells:
            cells.append({
                "boundary_cell": cell,
                "size_mb": size_per_cell,
                "source_region": region_id,
            })

        total_size_mb += actual_size_mb
        regions_processed += 1
        cells_processed += cell_count

    # Build output
    output = {
        "version": "1.0",
        "description": "Size manifest for pack-planner, generated from actual build sizes",
        "stats": {
            "total_cells": len(cells),
            "total_size_mb": round(total_size_mb, 2),
            "average_size_mb_per_cell": round(total_size_mb / len(cells), 4) if cells else 0,
            "regions_processed": regions_processed,
        },
        "cells": cells,
    }

    # Write output
    print(f"Writing size manifest to: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)

    print()
    print("=" * 60)
    print("SIZE MANIFEST CREATED")
    print("=" * 60)
    print(f"  Regions processed: {regions_processed}")
    print(f"  Cells mapped: {len(cells)}")
    print(f"  Total size: {total_size_mb:.1f} MB ({total_size_mb/1024:.2f} GB)")
    print(f"  Average per cell: {total_size_mb/len(cells):.2f} MB")
    print(f"  Output: {args.output}")


if __name__ == "__main__":
    main()
