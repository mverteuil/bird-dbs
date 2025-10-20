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
    "--min-checklists-per-region",
    type=int,
    default=6000000,
    help="Minimum checklists per region (default: 6,000,000)",
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
    "--verbose",
    is_flag=True,
    help="Enable verbose logging",
)
def main(
    density_reports: Path,
    min_checklists_per_region: int,
    output_manifest: Path,
    output_registry: Path,
    verbose: bool,
):
    """
    Create regional boundaries for eBird pack distribution.

    Reads density reports from ebird-density-analyzer and partitions packs into
    geographic regions based on observation density (checklist counts).

    Aggressively merges regions to meet minimum threshold (~60 regions globally).
    """
    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info("Pack Planner (Simplified) v0.2.0")
    logger.info("=" * 60)

    # Load density reports
    logger.info("Loading density reports from: %s", density_reports)
    density_data = load_density_reports(density_reports)

    logger.info("Found %d cells across all resolutions", len(density_data))

    # Create pack list from density data
    logger.info("Creating pack definitions from density data...")
    packs = create_packs_from_density(density_data)

    logger.info(
        "Created %d packs with %d total checklists",
        len(packs),
        sum(p["total_checklists"] for p in packs),
    )

    # Partition into regions based on observation density
    logger.info(
        "Partitioning packs into regions (min checklists per region: %d)...",
        min_checklists_per_region,
    )

    partitioner = RegionPartitioner(min_checklists_per_region=min_checklists_per_region)
    regions = partitioner.partition(packs)

    logger.info("Created %d regions", len(regions))

    # Generate region names
    logger.info("Generating region names...")

    namer = RegionNamer()
    for region in regions:
        region["region_id"] = namer.name_region(region)
        region["release_name"] = f"{region['region_id']}-2025.08"

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
    logger.info("Total checklists: %d", registry.get("total_checklists", 0))


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


def create_packs_from_density(density_data: list[dict]) -> list[dict]:
    """
    Create pack definitions from density data.

    Uses each cell's recommended data resolution without size-based subdivision.

    Args:
        density_data: List of cell density data across all resolutions

    Returns:
        List of pack definitions
    """
    packs = []

    # Group cells by resolution
    cells_by_resolution = {}
    for cell in density_data:
        # Skip cells with insufficient data
        if cell.get("complete_checklists", 0) < 100:
            continue

        res = cell.get("resolution", 4)
        if res not in cells_by_resolution:
            cells_by_resolution[res] = {}

        cells_by_resolution[res][cell["h3_cell"]] = cell

    logger.info(
        "Cells by resolution: %s", {r: len(cells) for r, cells in cells_by_resolution.items()}
    )

    # Use resolution 2 as boundary cells (coarse geographic regions)
    if 2 in cells_by_resolution:
        for cell_data in cells_by_resolution[2].values():
            pack = {
                "pack_id": f"h3-r2-{cell_data['h3_cell']}-data-r{cell_data['recommended_data_resolution']}",
                "boundary_cell": cell_data["h3_cell"],
                "boundary_resolution": 2,
                "data_resolution": cell_data["recommended_data_resolution"],
                "center_lat": cell_data["center_lat"],
                "center_lon": cell_data["center_lon"],
                "total_checklists": cell_data.get(
                    "total_complete_checklists_sampled", cell_data.get("complete_checklists", 0)
                ),
            }
            packs.append(pack)

    logger.info("Created %d packs from resolution 2 cells", len(packs))

    return packs


if __name__ == "__main__":
    main()
