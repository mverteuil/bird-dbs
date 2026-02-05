"""Partition eBird data by H3 boundary cells for efficient pack building.

This preprocessing step enables fast pack generation:
1. Single pass through all parquet files
2. Writes one parquet file per boundary cell with data
3. Pack building then reads only its partition
"""

import json
import shutil
import time
from pathlib import Path

import duckdb

from ebd_pack_builder.utils.formatting import format_duration, format_size
from ebd_pack_builder.utils.parquet_utils import get_parquet_files


def discover_boundary_cells(
    ddb: duckdb.DuckDBPyConnection,
    parquet_files: list[str],
    boundary_resolution: int,
) -> list[dict]:
    """Discover all boundary cells with data and their statistics."""
    print("Discovering boundary cells with data...")

    file_list = "[" + ", ".join(f"'{f}'" for f in parquet_files) + "]"

    query = f"""
        SELECT
            h3_latlng_to_cell(
                CAST("LATITUDE" AS DOUBLE),
                CAST("LONGITUDE" AS DOUBLE),
                {boundary_resolution}
            ) as boundary_cell,
            COUNT(*) as observation_count,
            COUNT(DISTINCT "SAMPLING EVENT IDENTIFIER") as checklist_count,
            COUNT(DISTINCT "TAXON CONCEPT ID") as species_count,
            MIN(CAST("LATITUDE" AS DOUBLE)) as lat_min,
            MAX(CAST("LATITUDE" AS DOUBLE)) as lat_max,
            MIN(CAST("LONGITUDE" AS DOUBLE)) as lon_min,
            MAX(CAST("LONGITUDE" AS DOUBLE)) as lon_max
        FROM read_parquet({file_list})
        WHERE "LATITUDE" IS NOT NULL
            AND "LONGITUDE" IS NOT NULL
            AND "TAXON CONCEPT ID" IS NOT NULL
        GROUP BY boundary_cell
        ORDER BY checklist_count DESC
    """

    start = time.time()
    result = ddb.execute(query).fetchall()
    elapsed = time.time() - start

    cells = []
    for row in result:
        cells.append(
            {
                "boundary_cell": format(row[0], "x"),  # Convert to hex string
                "boundary_cell_int": row[0],
                "observation_count": row[1],
                "checklist_count": row[2],
                "species_count": row[3],
                "lat_min": row[4],
                "lat_max": row[5],
                "lon_min": row[6],
                "lon_max": row[7],
            }
        )

    print(f"  Found {len(cells):,} boundary cells with data")
    print(f"  Discovery took {format_duration(elapsed)}")

    # Statistics
    total_obs = sum(c["observation_count"] for c in cells)
    total_checklists = sum(c["checklist_count"] for c in cells)
    print(f"  Total observations: {total_obs:,}")
    print(f"  Total checklists: {total_checklists:,}")

    if cells:
        top_cells = cells[:5]
        print("  Top 5 cells by checklists:")
        for c in top_cells:
            print(f"    {c['boundary_cell']}: {c['checklist_count']:,} checklists, {c['species_count']} species")

    return cells


def partition_data_single_pass(
    ddb: duckdb.DuckDBPyConnection,
    parquet_files: list[str],
    output_dir: Path,
    boundary_resolution: int,
) -> dict:
    """Partition data in a single pass using COPY with PARTITION_BY.

    This is efficient - DuckDB handles the partitioning internally.
    """
    print("\nPartitioning data (single-pass mode)...")

    file_list = "[" + ", ".join(f"'{f}'" for f in parquet_files) + "]"
    output_dir.mkdir(parents=True, exist_ok=True)

    start_time = time.time()

    # Use DuckDB's COPY with PARTITION_BY for efficient partitioning
    query = f"""
        COPY (
            SELECT
                printf('%x', h3_latlng_to_cell(
                    CAST("LATITUDE" AS DOUBLE),
                    CAST("LONGITUDE" AS DOUBLE),
                    {boundary_resolution}
                )) as boundary_cell,
                *
            FROM read_parquet({file_list})
            WHERE "LATITUDE" IS NOT NULL
                AND "LONGITUDE" IS NOT NULL
                AND "TAXON CONCEPT ID" IS NOT NULL
        ) TO '{output_dir}'
        (FORMAT PARQUET, PARTITION_BY (boundary_cell), COMPRESSION 'ZSTD', OVERWRITE_OR_IGNORE)
    """

    print("  Executing partitioned COPY (this will take a while)...")
    ddb.execute(query)

    elapsed = time.time() - start_time
    print(f"  Partitioning completed in {format_duration(elapsed)}")

    # Count output files and total size
    partition_dirs = list(output_dir.glob("boundary_cell=*"))
    total_size = 0
    total_files = 0

    for pdir in partition_dirs:
        for f in pdir.glob("*.parquet"):
            total_size += f.stat().st_size
            total_files += 1

    return {
        "cells_written": len(partition_dirs),
        "total_files": total_files,
        "total_size_bytes": total_size,
        "elapsed_seconds": elapsed,
    }


def partition_by_h3(
    input_dir: Path,
    output_dir: Path,
    boundary_resolution: int = 4,
    memory_limit: str = "16GB",
    temp_dir: Path | None = None,
    discover_only: bool = False,
) -> dict:
    """Partition eBird data by H3 boundary cells.

    Args:
        input_dir: Directory with sorted eBird parquet files
        output_dir: Output directory for partitioned data
        boundary_resolution: H3 resolution for boundary cells
        memory_limit: DuckDB memory limit
        temp_dir: Temp directory for DuckDB
        discover_only: Only discover boundary cells, don't partition

    Returns:
        Dict with metrics (cells_written, total_size_bytes, etc.)
    """
    # Get parquet files
    parquet_files = get_parquet_files(input_dir)
    if not parquet_files:
        raise ValueError(f"No parquet files found in {input_dir}")

    print("=" * 60)
    print("eBird Data Partitioner")
    print("=" * 60)
    print(f"Input: {input_dir}")
    print(f"Output: {output_dir}")
    print(f"Boundary resolution: {boundary_resolution}")
    print(f"Parquet files: {len(parquet_files)}")
    print()

    # Initialize DuckDB
    print("Initializing DuckDB...")
    ddb = duckdb.connect()
    ddb.execute("INSTALL h3 FROM community; LOAD h3")
    ddb.execute(f"SET memory_limit='{memory_limit}'")

    actual_temp_dir = temp_dir or (output_dir / "temp")
    actual_temp_dir.mkdir(parents=True, exist_ok=True)
    ddb.execute(f"SET temp_directory='{actual_temp_dir}'")

    # Discover boundary cells
    cells = discover_boundary_cells(ddb, parquet_files, boundary_resolution)

    if discover_only:
        # Write discovery results
        manifest_path = output_dir / "boundary_cells.json"
        output_dir.mkdir(parents=True, exist_ok=True)
        with open(manifest_path, "w") as f:
            json.dump({"cells": cells}, f, indent=2)
        print(f"\nDiscovery results written to: {manifest_path}")
        return {
            "cells_discovered": len(cells),
            "output_path": str(manifest_path),
        }

    # Partition data
    stats = partition_data_single_pass(ddb, parquet_files, output_dir, boundary_resolution)

    # Clean up temp
    if actual_temp_dir.exists():
        shutil.rmtree(actual_temp_dir, ignore_errors=True)

    # Write manifest
    manifest = {
        "boundary_resolution": boundary_resolution,
        "cells_count": stats["cells_written"],
        "total_size_bytes": stats["total_size_bytes"],
        "source_files": len(parquet_files),
    }

    manifest_path = output_dir / "partition_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print()
    print("=" * 60)
    print("PARTITIONING COMPLETE")
    print("=" * 60)
    print(f"  Boundary cells: {stats['cells_written']:,}")
    print(f"  Total size: {format_size(stats['total_size_bytes'])}")
    print(f"  Time: {format_duration(stats['elapsed_seconds'])}")
    print(f"  Manifest: {manifest_path}")
    print()

    return {
        "cells_written": stats["cells_written"],
        "total_size_bytes": stats["total_size_bytes"],
        "duration_seconds": stats["elapsed_seconds"],
    }
