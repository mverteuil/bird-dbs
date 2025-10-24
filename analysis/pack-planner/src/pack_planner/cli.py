"""Command-line interface for pack-planner."""

import json
import logging
from pathlib import Path

import click

from .naming import RegionNamer
from .partition import RegionPartitioner
from .registry import RegistryBuilder

logger = logging.getLogger(__name__)


@click.command()
@click.option(
    "--density-reports",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=True,
    help="Directory containing density report JSON files from ebird-density-analyzer",
)
@click.option(
    "--max-region-size-mb",
    type=float,
    default=1950.0,
    help="Maximum size per region bundle in MB (default: 1950 = 2GB - 50MB buffer)",
)
@click.option(
    "--max-pack-size-mb",
    type=float,
    default=500.0,
    help="Maximum size per individual pack in MB (default: 500MB for fast queries)",
)
@click.option(
    "--output-manifest",
    type=click.Path(path_type=Path),
    required=True,
    help="Output path for pack manifest JSON",
)
@click.option(
    "--output-registry",
    type=click.Path(path_type=Path),
    required=True,
    help="Output path for region registry JSON",
)
@click.option(
    "--method",
    type=click.Choice(["greedy", "monte-carlo", "continental"]),
    default="continental",
    help="Partitioning method (default: continental)",
)
@click.option(
    "--monte-carlo-iterations",
    type=int,
    default=100,
    help="Number of Monte Carlo iterations if using monte-carlo method",
)
@click.option(
    "--min-checklists-per-region",
    type=int,
    default=6000000,
    help="Minimum checklists per region for continental method (default: 6M)",
)
@click.option(
    "--verbose",
    is_flag=True,
    help="Enable verbose logging",
)
def main(
    density_reports: Path,
    max_region_size_mb: float,
    max_pack_size_mb: float,
    output_manifest: Path,
    output_registry: Path,
    method: str,
    monte_carlo_iterations: int,
    min_checklists_per_region: int,
    verbose: bool,
):
    """
    Plan optimal region partitions for eBird pack distribution via GitHub releases.

    Reads density reports from ebird-density-analyzer and partitions packs into
    regions that fit within GitHub's 2GB release limit while maximizing region size.
    """
    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info("Pack Planner v0.1.0")
    logger.info("=" * 60)

    # Load density reports
    logger.info("Loading density reports from: %s", density_reports)
    density_data = load_density_reports(density_reports)

    logger.info("Found %d cells across all resolutions", len(density_data))

    # Create pack manifest from density data using hierarchical selection
    logger.info("Creating pack manifest with hierarchical selection...")
    pack_manifest = create_pack_manifest(density_data, max_pack_size_mb=max_pack_size_mb)

    logger.info(
        "Pack manifest: %d packs",
        len(pack_manifest["packs"]),
    )

    # Partition into regions
    logger.info("Partitioning packs into regions using %s method...", method)

    partitioner = RegionPartitioner(
        max_size_mb=max_region_size_mb, min_checklists=min_checklists_per_region
    )

    if method == "greedy":
        regions = partitioner.partition_greedy(pack_manifest["packs"])
    elif method == "monte-carlo":
        regions = partitioner.partition_monte_carlo(
            pack_manifest["packs"], iterations=monte_carlo_iterations
        )
    else:  # continental
        regions = partitioner.partition_continental(pack_manifest["packs"])

    logger.info("Created %d regions", len(regions))

    # Generate region names
    logger.info("Generating region names...")
    namer = RegionNamer()
    region_counter = {}  # Track region numbers within M49 areas

    for region in regions:
        region["region_id"] = namer.name_region(region, region_counter)
        region["release_name"] = f"{region['region_id']}-2025.08"  # CalVer placeholder

    # Build registry
    logger.info("Building pack registry...")
    registry_builder = RegistryBuilder()
    registry = registry_builder.build_registry(regions)

    # Write outputs
    logger.info("Writing pack manifest to: %s", output_manifest)
    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    with open(output_manifest, "w") as f:
        json.dump({"regions": regions}, f, indent=2)

    logger.info("Writing region registry to: %s", output_registry)
    output_registry.parent.mkdir(parents=True, exist_ok=True)
    with open(output_registry, "w") as f:
        json.dump(registry, f, indent=2)

    logger.info("=" * 60)
    logger.info("Done!")
    logger.info("Total regions: %d", len(regions))


def load_density_reports(reports_dir: Path) -> list[dict]:
    """Load all density report JSON files from directory."""
    density_data = []

    for report_file in reports_dir.glob("global_density_res*.json"):
        logger.debug("Loading: %s", report_file.name)

        with open(report_file) as f:
            report = json.load(f)

        # Inject resolution into each cell from the parent report
        resolution = report.get("resolution")
        for cell in report["cells"]:
            cell["resolution"] = resolution

        density_data.extend(report["cells"])

    return density_data


def create_pack_manifest(density_data: list[dict], max_pack_size_mb: float = 500.0) -> dict:
    """
    Create pack manifest from density data using hierarchical resolution selection.

    Args:
        density_data: List of cell density data across all resolutions
        max_pack_size_mb: Maximum size for individual packs (default: 500MB for fast queries)

    Returns:
        Pack manifest with hierarchically selected optimal cells
    """
    import h3

    # Group cells by resolution for fast lookup
    cells_by_resolution = {}
    for cell in density_data:
        if cell["complete_checklists"] < 100:
            continue  # Skip cells with insufficient data

        res = cell.get("resolution", 4)
        if res not in cells_by_resolution:
            cells_by_resolution[res] = {}

        cells_by_resolution[res][cell["h3_cell"]] = cell

    logger.info(
        "Cells by resolution: %s", {r: len(cells) for r, cells in cells_by_resolution.items()}
    )

    # Start hierarchical selection from coarsest resolution
    min_res = min(cells_by_resolution.keys())
    max_res = max(cells_by_resolution.keys())

    logger.info(
        "Hierarchical selection: res %d to %d, max pack size: %.1f MB",
        min_res,
        max_res,
        max_pack_size_mb,
    )

    selected_packs = []
    to_process = list(cells_by_resolution[min_res].values())

    while to_process:
        cell_data = to_process.pop(0)
        current_res = cell_data.get("resolution", 4)

        # Check if this cell's pack size is acceptable
        if cell_data["estimated_pack_size_mb"] <= max_pack_size_mb or current_res >= max_res:
            # Use this cell as a pack (either fits or we're at max resolution)
            pack = {
                "pack_id": f"h3-r{current_res}-{cell_data['h3_cell']}-data-r{cell_data['recommended_data_resolution']}",  # noqa: E501
                "boundary_cell": cell_data["h3_cell"],
                "boundary_resolution": current_res,
                "data_resolution": cell_data["recommended_data_resolution"],
                "center_lat": cell_data["center_lat"],
                "center_lon": cell_data["center_lon"],
                "estimated_size_mb": -1,  # Placeholder - actual size set by ebird-builder
                "total_checklists": cell_data["complete_checklists"],
            }
            selected_packs.append(pack)
        else:
            # Pack is too large - subdivide to children at next resolution
            next_res = current_res + 1

            if next_res in cells_by_resolution:
                # Get child cells at next resolution
                children = h3.cell_to_children(cell_data["h3_cell"], next_res)

                children_found = 0
                for child_hex in children:
                    if child_hex in cells_by_resolution[next_res]:
                        to_process.append(cells_by_resolution[next_res][child_hex])
                        children_found += 1

                if children_found == 0:
                    # No children available - use current cell anyway
                    logger.warning(
                        "Cell %s at res %d but no children at res %d - using anyway",
                        cell_data["h3_cell"],
                        current_res,
                        next_res,
                    )
                    pack = {
                        "pack_id": f"h3-r{current_res}-{cell_data['h3_cell']}-data-r{cell_data['recommended_data_resolution']}",  # noqa: E501
                        "boundary_cell": cell_data["h3_cell"],
                        "boundary_resolution": current_res,
                        "data_resolution": cell_data["recommended_data_resolution"],
                        "center_lat": cell_data["center_lat"],
                        "center_lon": cell_data["center_lon"],
                        "estimated_size_mb": -1,  # Placeholder - actual size set by ebird-builder
                        "total_checklists": cell_data["complete_checklists"],
                    }
                    selected_packs.append(pack)
            else:
                # No next resolution available - use current cell
                pack = {
                    "pack_id": f"h3-r{current_res}-{cell_data['h3_cell']}-data-r{cell_data['recommended_data_resolution']}",  # noqa: E501
                    "boundary_cell": cell_data["h3_cell"],
                    "boundary_resolution": current_res,
                    "data_resolution": cell_data["recommended_data_resolution"],
                    "center_lat": cell_data["center_lat"],
                    "center_lon": cell_data["center_lon"],
                    "estimated_size_mb": -1,  # Placeholder - actual size set by ebird-builder
                    "total_checklists": cell_data["complete_checklists"],
                }
                selected_packs.append(pack)

    logger.info("Selected %d packs via hierarchical selection", len(selected_packs))

    # Log resolution distribution
    res_distribution = {}
    for pack in selected_packs:
        res = pack["boundary_resolution"]
        res_distribution[res] = res_distribution.get(res, 0) + 1

    logger.info("Resolution distribution: %s", res_distribution)

    return {"packs": selected_packs, "total_packs": len(selected_packs)}


if __name__ == "__main__":
    main()
