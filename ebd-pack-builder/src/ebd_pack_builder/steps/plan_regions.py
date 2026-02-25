"""Plan region packs from density report.

Groups boundary cells into downloadable regions that fit within size constraints.
Uses continental grouping based on H3 parent cells.
"""

import json
from collections import defaultdict
from pathlib import Path

import h3


def get_continent_name(lat: float, lon: float) -> str:
    """Get continent/region name from coordinates."""
    # Iceland, Faroe Islands, and Greenland
    if lat > 60 and -60 < lon < -10:
        return "atlantic"

    # Azores and Madeira
    if 30 < lat < 45 and -35 < lon < -15:
        return "atlantic"

    # Canary Islands and Cabo Verde
    if 10 < lat < 35 and -30 < lon < -10:
        return "atlantic"

    # Aleutian Islands and Bering Sea
    if lat > 45 and lon < -165:
        return "pacific"

    # North America (including Alaska, excluding Central America)
    if lat > 25 and -170 < lon < -50:
        if lat > 50:
            return "na-north"
        elif lon < -100:
            return "na-west"
        else:
            return "na-east"

    # Central America and Caribbean
    if 5 < lat <= 25 and -120 < lon < -55:
        return "central-america"

    # South America
    if lat > -60 and -85 < lon < -30:
        if lat > 0:
            return "sa-north"
        else:
            return "sa-south"

    # Galapagos
    if -5 < lat < 5 and -95 < lon < -85:
        return "pacific"

    # Europe (including UK, excluding Iceland)
    if lat > 35 and -15 < lon < 60:
        return "europe"

    # Middle East and Arabian Peninsula
    if 10 < lat < 45 and 30 < lon < 75:
        return "middle-east"

    # Asia
    if lat > -10 and 60 < lon < 150:
        if lat > 20:
            return "asia-east" if lon > 100 else "asia-south"
        else:
            return "se-asia"

    # Africa
    if -40 < lat < 40 and -20 < lon < 55:
        return "africa"

    # Australia and New Zealand
    if lat < -10 and 110 < lon < 180:
        return "oceania"

    # Pacific islands (Hawaii, Easter Island, etc.) and remote Pacific
    if lon > 150 or lon < -100:
        return "pacific"

    # Indian Ocean islands (Mauritius, Seychelles, Maldives, Christmas Island)
    if -40 < lat < 30 and 40 < lon < 120:
        return "indian"

    # Sub-Antarctic islands
    if lat < -40:
        return "sub-antarctic"

    # Remote/misc
    return "remote"


def plan_regions(
    density_report_path: Path,
    output_manifest_path: Path,
    output_registry_path: Path | None = None,
    max_region_size_mb: float = 500.0,
    grouping_resolution: int = 2,
    min_checklists: int = 100,
) -> dict:
    """Plan region packs from density report.

    Args:
        density_report_path: Path to density_report.json from density-report step
        output_manifest_path: Output path for pack manifest JSON
        output_registry_path: Optional output path for region registry JSON
        max_region_size_mb: Maximum size per region in MB
        grouping_resolution: H3 resolution for grouping cells (lower = larger regions)
        min_checklists: Minimum checklists required to include a cell (filters noise)

    Returns:
        Dict with planning statistics
    """
    # Load density report
    with open(density_report_path) as f:
        density = json.load(f)

    all_cells = density.get("cells", [])
    boundary_resolution = density.get("resolution", 4)

    # Filter out cells below minimum checklist threshold
    cells = [c for c in all_cells if c.get("unique_checklists", 0) >= min_checklists]
    filtered_count = len(all_cells) - len(cells)

    print("=" * 60)
    print("Region Planner")
    print("=" * 60)
    print(f"Input: {density_report_path}")
    print(f"Total boundary cells: {len(all_cells):,}")
    print(f"Min checklists filter: {min_checklists:,}")
    print(f"Filtered out: {filtered_count:,} cells (below threshold)")
    print(f"Cells to plan: {len(cells):,}")
    print(f"Boundary resolution: {boundary_resolution}")
    print(f"Grouping resolution: {grouping_resolution}")
    print(f"Max region size: {max_region_size_mb:.0f} MB")
    print()

    # Group cells by continent first, then by H3 parent within continent
    # This prevents dateline-crossing H3 cells from mixing regions
    continent_groups: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))

    for cell in cells:
        # Determine continent for this specific cell
        continent = get_continent_name(cell["center_lat"], cell["center_lon"])

        # Get H3 parent for sub-grouping within continent
        h3_cell = cell["h3_cell"]
        try:
            parent = h3.cell_to_parent(h3_cell, grouping_resolution)
            parent_hex = format(parent, "x")
        except Exception:
            parent_hex = "default"

        continent_groups[continent][parent_hex].append(cell)

    # Flatten to continent-level groups (merge H3 parents within same continent)
    groups: dict[str, list[dict]] = {}
    for continent, h3_groups in continent_groups.items():
        # Merge all H3 groups within this continent
        all_cells = []
        for cells_list in h3_groups.values():
            all_cells.extend(cells_list)
        groups[continent] = all_cells

    print(f"Initial groups (by continent): {len(groups)}")
    for continent, group_cells in sorted(groups.items()):
        print(f"  {continent}: {len(group_cells)} cells")

    # Build regions, splitting if needed based on size
    regions = []
    region_counter: dict[str, int] = defaultdict(int)

    for continent, group_cells in sorted(groups.items()):
        # Calculate total estimated size
        total_size = sum(c.get("estimated_pack_size_mb", 1.0) for c in group_cells)

        # Split into chunks if too large
        if total_size > max_region_size_mb:
            # Sort geographically (by latitude, then longitude) for spatial coherence
            sorted_cells = sorted(
                group_cells, key=lambda c: (round(c["center_lat"], 0), round(c["center_lon"], 0))
            )
            current_chunk: list[dict] = []
            current_size = 0.0

            for cell in sorted_cells:
                cell_size = cell.get("estimated_pack_size_mb", 1.0)
                if current_size + cell_size > max_region_size_mb and current_chunk:
                    # Save current chunk as region
                    region_counter[continent] += 1
                    region_id = f"{continent}-{region_counter[continent]:03d}"
                    regions.append(_create_region(region_id, current_chunk, boundary_resolution))
                    current_chunk = []
                    current_size = 0.0

                current_chunk.append(cell)
                current_size += cell_size

            # Save remaining cells
            if current_chunk:
                region_counter[continent] += 1
                region_id = f"{continent}-{region_counter[continent]:03d}"
                regions.append(_create_region(region_id, current_chunk, boundary_resolution))
        else:
            # Keep as single region
            region_counter[continent] += 1
            region_id = f"{continent}-{region_counter[continent]:03d}"
            regions.append(_create_region(region_id, group_cells, boundary_resolution))

    # Sort regions by ID
    regions.sort(key=lambda r: r["region_id"])

    # Calculate statistics
    total_packs = sum(len(r["packs"]) for r in regions)
    total_size_mb = sum(r["size_mb"] for r in regions)
    total_checklists = sum(r.get("total_checklists", 0) for r in regions)

    print(f"\nRegions created: {len(regions)}")
    print(f"Total packs: {total_packs:,}")
    print(f"Estimated total size: {total_size_mb:.1f} MB ({total_size_mb / 1024:.2f} GB)")
    print(f"Total checklists: {total_checklists:,}")
    print()

    # Region size distribution
    size_buckets = defaultdict(int)
    for r in regions:
        bucket = int(r["size_mb"] / 100) * 100
        size_buckets[bucket] += 1

    print("Region size distribution:")
    for bucket in sorted(size_buckets.keys()):
        count = size_buckets[bucket]
        print(f"  {bucket}-{bucket + 99} MB: {count} regions")

    # Write manifest
    manifest = {
        "regions": regions,
        "metadata": {
            "boundary_resolution": boundary_resolution,
            "grouping_resolution": grouping_resolution,
            "max_region_size_mb": max_region_size_mb,
            "total_regions": len(regions),
            "total_packs": total_packs,
            "total_size_mb": total_size_mb,
            "total_checklists": total_checklists,
        },
    }

    output_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nManifest written to: {output_manifest_path}")

    # Write registry if requested
    if output_registry_path:
        registry = {
            "version": "2025.02",
            "total_regions": len(regions),
            "total_packs": total_packs,
            "total_size_gb": total_size_mb / 1024,
            "regions": [
                {
                    "region_id": r["region_id"],
                    "release_name": r["release_name"],
                    "h3_cells": [p["boundary_cell"] for p in r["packs"]],
                    "pack_count": len(r["packs"]),
                    "size_mb": r["size_mb"],
                    "center": r["center"],
                }
                for r in regions
            ],
        }
        with open(output_registry_path, "w") as f:
            json.dump(registry, f, indent=2)
        print(f"Registry written to: {output_registry_path}")

    return {
        "total_regions": len(regions),
        "total_packs": total_packs,
        "total_size_mb": total_size_mb,
        "total_checklists": total_checklists,
    }


def _create_region(region_id: str, cells: list[dict], boundary_resolution: int) -> dict:
    """Create a region dict from a list of cells."""
    # Calculate center
    avg_lat = sum(c["center_lat"] for c in cells) / len(cells)
    avg_lon = sum(c["center_lon"] for c in cells) / len(cells)

    # Calculate total size and checklists
    total_size = sum(c.get("estimated_pack_size_mb", 1.0) for c in cells)
    total_checklists = sum(c.get("unique_checklists", 0) for c in cells)

    # Create packs list
    packs = []
    for cell in cells:
        packs.append(
            {
                "pack_id": f"h3-r{boundary_resolution}-{cell['h3_cell']}",
                "boundary_cell": cell["h3_cell"],
                "boundary_resolution": boundary_resolution,
                "data_resolution": cell.get("recommended_data_resolution", 5),
                "center_lat": cell["center_lat"],
                "center_lon": cell["center_lon"],
                "estimated_size_mb": cell.get("estimated_pack_size_mb", 1.0),
                "total_checklists": cell.get("unique_checklists", 0),
            }
        )

    return {
        "region_id": region_id,
        "release_name": f"{region_id}-2025.02",
        "h3_cells": [c["h3_cell"] for c in cells],
        "packs": packs,
        "size_mb": total_size,
        "pack_count": len(packs),
        "total_checklists": total_checklists,
        "center": {"lat": avg_lat, "lon": avg_lon},
    }
