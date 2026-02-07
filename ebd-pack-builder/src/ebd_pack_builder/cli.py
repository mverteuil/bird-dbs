"""Click CLI for EBD pack builder pipeline."""

from pathlib import Path

import click

from ebd_pack_builder import __version__


@click.group()
@click.version_option(version=__version__)
def cli():
    """eBird Basic Dataset pack builder for BirdNET-Pi region packs.

    Build SQLite region packs from eBird observation data for use with
    BirdNET-Pi's location-based species filtering.
    """
    pass


@cli.command()
@click.option(
    "--input",
    "input_path",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Input tarball (.tar) containing eBird data",
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    required=True,
    help="Output directory for Parquet files",
)
@click.option(
    "--chunk-size",
    type=int,
    default=1_000_000,
    help="Number of rows per chunk (default: 1,000,000)",
)
def convert(input_path: Path, output_dir: Path, chunk_size: int):
    """Convert eBird tarball to Parquet format.

    Streams data directly from the tarball without extracting to disk.
    """
    from ebd_pack_builder.steps.convert_to_parquet import convert_tarball_to_parquet

    if not input_path.suffix == ".tar":
        raise click.BadParameter(f"Input must be a .tar file, got: {input_path}")

    result = convert_tarball_to_parquet(input_path, output_dir, chunk_size)
    click.echo(f"\nTotal rows: {result['total_rows']:,}")


@cli.command()
@click.option(
    "--input-dir",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Directory with unsorted Parquet files",
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    required=True,
    help="Directory for sorted Parquet files",
)
@click.option(
    "--sort-order",
    type=click.Choice(["location", "date", "taxon"]),
    default="location",
    help="Sort order preset (default: location)",
)
@click.option(
    "--memory-limit",
    default="24GB",
    help="DuckDB memory limit (default: 24GB)",
)
@click.option(
    "--max-temp-size",
    default="800GiB",
    help="Max temp size per partition (default: 800GiB)",
)
@click.option(
    "--threads",
    type=int,
    default=2,
    help="Number of DuckDB threads (default: 2, use 1 for memory-constrained systems)",
)
@click.option(
    "--skip-existing",
    is_flag=True,
    help="Skip partitions that already have valid output files",
)
def sort(
    input_dir: Path,
    output_dir: Path,
    sort_order: str,
    memory_limit: str,
    max_temp_size: str,
    threads: int,
    skip_existing: bool,
):
    """Sort Parquet data by geographic location.

    Partitions data by latitude bands and sorts each partition separately,
    using much less temp space than a full sort.

    Use --skip-existing to resume after a failure - valid completed partitions
    will be skipped, and invalid/incomplete ones will be re-processed.
    """
    from ebd_pack_builder.steps.sort_by_location import sort_chunked

    result = sort_chunked(
        input_dir, output_dir, sort_order, memory_limit, max_temp_size, threads, skip_existing
    )
    click.echo(f"\nTotal rows: {result['total_rows']:,}")


@cli.command()
@click.option(
    "--input-dir",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Directory with sorted eBird parquet files",
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    required=True,
    help="Output directory for partitioned data",
)
@click.option(
    "--boundary-resolution",
    type=int,
    default=4,
    help="H3 resolution for boundary cells (default: 4)",
)
@click.option(
    "--memory-limit",
    default="16GB",
    help="DuckDB memory limit (default: 16GB)",
)
@click.option(
    "--temp-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Temp directory for DuckDB (default: output/temp)",
)
@click.option(
    "--discover-only",
    is_flag=True,
    help="Only discover boundary cells, don't partition",
)
def partition(
    input_dir: Path,
    output_dir: Path,
    boundary_resolution: int,
    memory_limit: str,
    temp_dir: Path | None,
    discover_only: bool,
):
    """Partition data by H3 boundary cells.

    Preprocessing step that enables fast pack generation by partitioning
    all data by boundary cell.
    """
    from ebd_pack_builder.steps.partition_by_h3 import partition_by_h3

    partition_by_h3(
        input_dir,
        output_dir,
        boundary_resolution,
        memory_limit,
        temp_dir,
        discover_only,
    )


@cli.command("density-report")
@click.option(
    "--boundary-cells",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Input boundary_cells.json from partition discovery",
)
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    required=True,
    help="Output density report JSON",
)
def density_report(boundary_cells: Path, output: Path):
    """Create density report from partition discovery.

    Converts boundary_cells.json to density report format for pack-planner.
    """
    from ebd_pack_builder.steps.create_density_report import create_density_report

    create_density_report(boundary_cells, output)


@cli.command()
@click.option(
    "--density-report",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Input density_report.json from density-report command",
)
@click.option(
    "--output-manifest",
    type=click.Path(path_type=Path),
    required=True,
    help="Output pack manifest JSON for build command",
)
@click.option(
    "--output-registry",
    type=click.Path(path_type=Path),
    default=None,
    help="Optional output registry JSON for client lookups",
)
@click.option(
    "--max-region-size-mb",
    type=float,
    default=500.0,
    help="Maximum size per region in MB (default: 500)",
)
@click.option(
    "--grouping-resolution",
    type=int,
    default=2,
    help="H3 resolution for grouping cells (default: 2, lower = larger regions)",
)
@click.option(
    "--min-checklists",
    type=int,
    default=100,
    help="Minimum checklists to include a cell (default: 100, filters noise)",
)
def plan(
    density_report: Path,
    output_manifest: Path,
    output_registry: Path | None,
    max_region_size_mb: float,
    grouping_resolution: int,
    min_checklists: int,
):
    """Plan region packs from density report.

    Groups boundary cells into downloadable regions optimized for
    distribution. Creates pack manifest for the build command.
    """
    from ebd_pack_builder.steps.plan_regions import plan_regions

    plan_regions(
        density_report,
        output_manifest,
        output_registry,
        max_region_size_mb,
        grouping_resolution,
        min_checklists,
    )


@cli.command("size-manifest")
@click.option(
    "--packs-dir",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Directory containing built .db pack files",
)
@click.option(
    "--pack-manifest",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Pack manifest JSON with region -> boundary cell mappings",
)
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    required=True,
    help="Output path for size manifest JSON",
)
def size_manifest(packs_dir: Path, pack_manifest: Path, output: Path):
    """Create size manifest from built region packs.

    Extracts actual sizes from built packs for pack-planner size-aware partitioning.
    """
    from ebd_pack_builder.steps.create_size_manifest import create_size_manifest

    create_size_manifest(packs_dir, pack_manifest, output)


@cli.command()
@click.option(
    "--partitioned-dir",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Directory with partitioned data from partition command",
)
@click.option(
    "--manifest",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Pack manifest JSON from pack-planner",
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    required=True,
    help="Output directory for region pack databases",
)
@click.option(
    "--region",
    type=str,
    default=None,
    help="Build only this specific region",
)
@click.option(
    "--worker",
    type=int,
    default=0,
    help="Worker ID for parallel execution (0-indexed)",
)
@click.option(
    "--total-workers",
    type=int,
    default=1,
    help="Total number of parallel workers",
)
@click.option(
    "--skip-existing",
    is_flag=True,
    help="Skip regions that already exist",
)
def build(
    partitioned_dir: Path,
    manifest: Path,
    output_dir: Path,
    region: str | None,
    worker: int,
    total_workers: int,
    skip_existing: bool,
):
    """Build region packs from partitioned data.

    Each region produces one SQLite pack containing data for all boundary
    cells in that region, with multi-resolution fallback.
    """
    from ebd_pack_builder.steps.build_region_packs import build_region_packs

    build_region_packs(
        partitioned_dir,
        manifest,
        output_dir,
        region,
        worker,
        total_workers,
        skip_existing,
    )


@cli.command()
@click.option(
    "--packs-dir",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Directory containing built .db pack files",
)
@click.option(
    "--registry",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Pack registry JSON (from build command)",
)
@click.option(
    "--compression-level",
    type=int,
    default=6,
    help="Gzip compression level 1-9 (default: 6)",
)
def package(packs_dir: Path, registry: Path, compression_level: int):
    """Package built packs for release.

    Gzips all .db files with release-compatible naming for the release-publisher tool.
    """
    from ebd_pack_builder.steps.package_packs import package_packs

    package_packs(packs_dir, registry, compression_level)


@cli.command()
@click.argument(
    "directories",
    type=click.Path(exists=True, path_type=Path),
    nargs=-1,
    required=True,
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="Show per-file details",
)
def verify(directories: tuple[Path, ...], verbose: bool):
    """Verify integrity of Parquet datasets.

    Checks file readability, row counts, and schema consistency.
    Can compare multiple directories.
    """
    from ebd_pack_builder.steps.verify_integrity import verify_parquet_integrity

    result = verify_parquet_integrity(list(directories), verbose)
    if not result["passed"]:
        raise SystemExit(1)


@cli.command()
@click.option(
    "--state-dir",
    type=click.Path(path_type=Path),
    default=Path("."),
    help="Directory containing pipeline state (default: current directory)",
)
def status(state_dir: Path):
    """Show current pipeline status.

    Displays the completion status of each pipeline step.
    """
    from ebd_pack_builder.pipeline import PipelineManager

    manager = PipelineManager(state_dir)
    manager.print_status()


@cli.command("run-all")
@click.option(
    "--input",
    "input_path",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Input tarball (.tar) containing eBird data",
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    required=True,
    help="Base output directory for all pipeline outputs",
)
@click.option(
    "--pack-manifest",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Pack manifest JSON (optional - will be generated by plan step if not provided)",
)
@click.option(
    "--from-step",
    type=click.Choice(["convert", "sort", "partition", "density_report", "plan", "build", "verify"]),
    default=None,
    help="Resume from this step (skips earlier steps)",
)
@click.option(
    "--state-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Directory for pipeline state (default: output-dir/.state)",
)
@click.option(
    "--force",
    is_flag=True,
    help="Force re-run of completed steps",
)
@click.option(
    "--memory-limit",
    default="24GB",
    help="DuckDB memory limit (default: 24GB)",
)
@click.option(
    "--chunk-size",
    type=int,
    default=1_000_000,
    help="Rows per parquet chunk (default: 1,000,000)",
)
@click.option(
    "--boundary-resolution",
    type=int,
    default=4,
    help="H3 resolution for boundary cells (default: 4)",
)
def run_all(
    input_path: Path,
    output_dir: Path,
    pack_manifest: Path | None,
    from_step: str | None,
    state_dir: Path | None,
    force: bool,
    memory_limit: str,
    chunk_size: int,
    boundary_resolution: int,
):
    """Run the complete EBD pipeline.

    Executes all steps from tarball to SQLite packs:
    1. convert - Tarball to Parquet
    2. sort - Geographic sorting
    3. partition - H3 boundary partitioning
    4. density_report - Create density report
    5. plan - Plan region packs
    6. build - Build region packs
    7. verify - Verify output integrity
    """
    from ebd_pack_builder.pipeline import PipelineManager
    from ebd_pack_builder.steps.build_region_packs import build_region_packs
    from ebd_pack_builder.steps.convert_to_parquet import convert_tarball_to_parquet
    from ebd_pack_builder.steps.create_density_report import create_density_report
    from ebd_pack_builder.steps.partition_by_h3 import partition_by_h3
    from ebd_pack_builder.steps.plan_regions import plan_regions
    from ebd_pack_builder.steps.sort_by_location import sort_chunked
    from ebd_pack_builder.steps.verify_integrity import verify_parquet_integrity

    # Setup directories
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    parquet_dir = output_dir / "parquet"
    sorted_dir = output_dir / "sorted"
    partitioned_dir = output_dir / "partitioned"
    packs_dir = output_dir / "packs"
    actual_state_dir = state_dir or (output_dir / ".state")

    # Initialize pipeline manager
    manager = PipelineManager(actual_state_dir, "ebd-pipeline")

    # Get steps to run
    steps = manager.get_steps_from(from_step)

    click.echo("=" * 60)
    click.echo("EBD Pack Builder Pipeline")
    click.echo("=" * 60)
    click.echo(f"Input: {input_path}")
    click.echo(f"Output: {output_dir}")
    click.echo(f"Steps: {', '.join(steps)}")
    click.echo()

    # Step 1: Convert
    if "convert" in steps:
        if manager.should_skip("convert", force):
            click.echo("[SKIP] convert: already completed")
        else:
            click.echo("[RUN] convert: Tarball -> Parquet")
            manager.start_step("convert")
            try:
                result = convert_tarball_to_parquet(input_path, parquet_dir, chunk_size)
                manager.complete_step("convert", parquet_dir, result)
            except Exception as e:
                manager.fail_step("convert", str(e))
                raise click.ClickException(f"Convert failed: {e}")

    # Step 2: Sort
    if "sort" in steps:
        if manager.should_skip("sort", force):
            click.echo("[SKIP] sort: already completed")
        else:
            click.echo("[RUN] sort: Geographic sorting")
            manager.start_step("sort")
            try:
                result = sort_chunked(
                    parquet_dir, sorted_dir, "location", memory_limit, "800GiB", 2, False
                )
                manager.complete_step("sort", sorted_dir, result)
            except Exception as e:
                manager.fail_step("sort", str(e))
                raise click.ClickException(f"Sort failed: {e}")

    # Step 3: Partition
    if "partition" in steps:
        if manager.should_skip("partition", force):
            click.echo("[SKIP] partition: already completed")
        else:
            click.echo("[RUN] partition: H3 boundary partitioning")
            manager.start_step("partition")
            try:
                result = partition_by_h3(
                    sorted_dir,
                    partitioned_dir,
                    boundary_resolution,
                    memory_limit,
                )
                manager.complete_step("partition", partitioned_dir, result)
            except Exception as e:
                manager.fail_step("partition", str(e))
                raise click.ClickException(f"Partition failed: {e}")

    # Step 4: Density report
    if "density_report" in steps:
        if manager.should_skip("density_report", force):
            click.echo("[SKIP] density_report: already completed")
        else:
            # First run partition in discover-only mode to get boundary cells
            boundary_cells_path = partitioned_dir / "boundary_cells.json"
            if not boundary_cells_path.exists():
                click.echo("[RUN] partition --discover-only: Discovering boundary cells")
                partition_by_h3(
                    sorted_dir, partitioned_dir, boundary_resolution, memory_limit, discover_only=True
                )

            click.echo("[RUN] density_report: Creating density report")
            manager.start_step("density_report")
            try:
                density_report_path = partitioned_dir / "density_report.json"
                create_density_report(boundary_cells_path, density_report_path)
                manager.complete_step("density_report", density_report_path)
            except Exception as e:
                manager.fail_step("density_report", str(e))
                raise click.ClickException(f"Density report failed: {e}")

    # Step 5: Plan regions
    manifest_path = pack_manifest or (partitioned_dir / "pack_manifest.json")
    if "plan" in steps:
        if manager.should_skip("plan", force):
            click.echo("[SKIP] plan: already completed")
        else:
            click.echo("[RUN] plan: Planning region packs")
            manager.start_step("plan")
            try:
                density_report_path = partitioned_dir / "density_report.json"
                registry_path = partitioned_dir / "pack_registry.json"
                result = plan_regions(
                    density_report_path,
                    manifest_path,
                    registry_path,
                    max_region_size_mb=500.0,
                    grouping_resolution=2,
                )
                manager.complete_step("plan", manifest_path, result)
            except Exception as e:
                manager.fail_step("plan", str(e))
                raise click.ClickException(f"Plan failed: {e}")

    # Step 6: Build packs
    if "build" in steps:
        if manager.should_skip("build", force):
            click.echo("[SKIP] build: already completed")
        else:
            click.echo("[RUN] build: Building region packs")
            manager.start_step("build")
            try:
                result = build_region_packs(partitioned_dir, manifest_path, packs_dir)
                manager.complete_step("build", packs_dir, result)
            except Exception as e:
                manager.fail_step("build", str(e))
                raise click.ClickException(f"Build failed: {e}")

    # Step 7: Verify
    if "verify" in steps:
        if manager.should_skip("verify", force):
            click.echo("[SKIP] verify: already completed")
        else:
            click.echo("[RUN] verify: Verifying output integrity")
            manager.start_step("verify")
            try:
                result = verify_parquet_integrity([parquet_dir, sorted_dir])
                if not result["passed"]:
                    raise ValueError("Verification failed")
                manager.complete_step("verify", None, result)
            except Exception as e:
                manager.fail_step("verify", str(e))
                raise click.ClickException(f"Verify failed: {e}")

    click.echo()
    click.echo("=" * 60)
    click.echo("PIPELINE COMPLETE")
    click.echo("=" * 60)
    manager.print_status()


if __name__ == "__main__":
    cli()
