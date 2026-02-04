#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "duckdb>=1.0.0",
# ]
# ///
"""
Partition eBird data by H3 boundary cells for efficient pack building.

This is a preprocessing step that enables fast pack generation:
1. Single pass through all parquet files (~6 hours)
2. Writes one parquet file per boundary cell with data
3. Pack building then reads only its partition (~10 seconds per pack)

Output structure:
    partitioned/
    ├── boundary_842b9bdffffffff.parquet  (Toronto area)
    ├── boundary_842b9adffffffff.parquet  (Adjacent cell)
    └── ...

Usage:
    uv run partition_by_boundary.py \
        --input /Volumes/Lightroom/ebird_by_location \
        --output /Volumes/Lightroom/ebird_partitioned \
        --boundary-resolution 4
"""

import argparse
import json
import shutil
import time
from pathlib import Path

import duckdb


def format_size(bytes_size: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_size < 1024:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024
    return f"{bytes_size:.2f} TB"


def format_duration(seconds: float) -> str:
    hours, rem = divmod(int(seconds), 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def get_parquet_files(parquet_dir: Path) -> list[str]:
    """Get list of parquet files, excluding macOS extended attribute files."""
    files = sorted(parquet_dir.glob("*.parquet"))
    return [str(f) for f in files if not f.name.startswith("._")]


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
        cells.append({
            "boundary_cell": format(row[0], 'x'),  # Convert to hex string
            "boundary_cell_int": row[0],
            "observation_count": row[1],
            "checklist_count": row[2],
            "species_count": row[3],
            "lat_min": row[4],
            "lat_max": row[5],
            "lon_min": row[6],
            "lon_max": row[7],
        })

    print(f"  Found {len(cells):,} boundary cells with data")
    print(f"  Discovery took {format_duration(elapsed)}")

    # Statistics
    total_obs = sum(c["observation_count"] for c in cells)
    total_checklists = sum(c["checklist_count"] for c in cells)
    print(f"  Total observations: {total_obs:,}")
    print(f"  Total checklists: {total_checklists:,}")

    if cells:
        top_cells = cells[:5]
        print(f"  Top 5 cells by checklists:")
        for c in top_cells:
            print(f"    {c['boundary_cell']}: {c['checklist_count']:,} checklists, {c['species_count']} species")

    return cells


def partition_data(
    ddb: duckdb.DuckDBPyConnection,
    parquet_files: list[str],
    output_dir: Path,
    boundary_resolution: int,
    cells: list[dict],
    batch_size: int = 100,
) -> dict:
    """Partition data by boundary cell, processing in batches."""
    print(f"\nPartitioning data into {len(cells):,} boundary cells...")
    print(f"  Batch size: {batch_size} cells per query")

    file_list = "[" + ", ".join(f"'{f}'" for f in parquet_files) + "]"
    output_dir.mkdir(parents=True, exist_ok=True)

    stats = {
        "cells_written": 0,
        "total_rows": 0,
        "total_size_bytes": 0,
        "errors": [],
    }

    start_time = time.time()

    # Process cells in batches
    for batch_start in range(0, len(cells), batch_size):
        batch_end = min(batch_start + batch_size, len(cells))
        batch = cells[batch_start:batch_end]
        batch_num = batch_start // batch_size + 1
        total_batches = (len(cells) + batch_size - 1) // batch_size

        print(f"\n  Batch {batch_num}/{total_batches} ({len(batch)} cells)...")

        # Build cell list for IN clause
        cell_ints = [c["boundary_cell_int"] for c in batch]
        cell_list = ", ".join(str(c) for c in cell_ints)

        # Query to get data for this batch of cells
        query = f"""
            SELECT
                h3_latlng_to_cell(
                    CAST("LATITUDE" AS DOUBLE),
                    CAST("LONGITUDE" AS DOUBLE),
                    {boundary_resolution}
                ) as boundary_cell,
                *
            FROM read_parquet({file_list})
            WHERE "LATITUDE" IS NOT NULL
                AND "LONGITUDE" IS NOT NULL
                AND "TAXON CONCEPT ID" IS NOT NULL
                AND h3_latlng_to_cell(
                    CAST("LATITUDE" AS DOUBLE),
                    CAST("LONGITUDE" AS DOUBLE),
                    {boundary_resolution}
                ) IN ({cell_list})
        """

        # Fetch all data for this batch
        batch_start_time = time.time()
        try:
            batch_data = ddb.execute(query).fetchall()
        except Exception as e:
            print(f"    ERROR: {e}")
            stats["errors"].append(str(e))
            continue

        batch_elapsed = time.time() - batch_start_time
        print(f"    Fetched {len(batch_data):,} rows in {format_duration(batch_elapsed)}")

        # Group by boundary cell
        cell_data = {}
        for row in batch_data:
            bc = row[0]  # boundary_cell is first column
            if bc not in cell_data:
                cell_data[bc] = []
            cell_data[bc].append(row[1:])  # Skip boundary_cell column

        # Write each cell's data to a separate parquet file
        for cell_int, rows in cell_data.items():
            cell_hex = format(cell_int, 'x')
            output_file = output_dir / f"boundary_{cell_hex}.parquet"

            try:
                # Create a table from the rows and write to parquet
                # Get column names from the original query (excluding boundary_cell)
                col_query = f"SELECT * FROM read_parquet({file_list}) LIMIT 0"
                col_result = ddb.execute(col_query)
                col_names = [desc[0] for desc in col_result.description]

                # Register the data as a table
                ddb.execute("DROP TABLE IF EXISTS temp_partition")
                ddb.execute(f"""
                    CREATE TABLE temp_partition AS
                    SELECT * FROM read_parquet({file_list})
                    WHERE h3_latlng_to_cell(
                        CAST("LATITUDE" AS DOUBLE),
                        CAST("LONGITUDE" AS DOUBLE),
                        {boundary_resolution}
                    ) = {cell_int}
                """)

                # Write to parquet
                ddb.execute(f"""
                    COPY temp_partition TO '{output_file}'
                    (FORMAT PARQUET, COMPRESSION 'ZSTD')
                """)

                ddb.execute("DROP TABLE temp_partition")

                file_size = output_file.stat().st_size
                stats["cells_written"] += 1
                stats["total_rows"] += len(rows)
                stats["total_size_bytes"] += file_size

            except Exception as e:
                print(f"    ERROR writing {cell_hex}: {e}")
                stats["errors"].append(f"{cell_hex}: {e}")

        # Progress update
        elapsed = time.time() - start_time
        cells_done = min(batch_end, len(cells))
        rate = cells_done / elapsed if elapsed > 0 else 0
        eta = (len(cells) - cells_done) / rate if rate > 0 else 0

        print(f"    Progress: {cells_done}/{len(cells)} cells, "
              f"{format_size(stats['total_size_bytes'])} written, "
              f"ETA: {format_duration(eta)}")

    return stats


def partition_data_single_pass(
    ddb: duckdb.DuckDBPyConnection,
    parquet_files: list[str],
    output_dir: Path,
    boundary_resolution: int,
) -> dict:
    """
    Partition data in a single pass using COPY with PARTITION_BY.

    This is more efficient than batch processing - DuckDB handles
    the partitioning internally.
    """
    print(f"\nPartitioning data (single-pass mode)...")

    file_list = "[" + ", ".join(f"'{f}'" for f in parquet_files) + "]"
    output_dir.mkdir(parents=True, exist_ok=True)

    start_time = time.time()

    # Use DuckDB's COPY with PARTITION_BY for efficient partitioning
    # This writes one file per unique boundary_cell value
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

    stats = {
        "cells_written": len(partition_dirs),
        "total_files": total_files,
        "total_size_bytes": total_size,
        "elapsed_seconds": elapsed,
    }

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Partition eBird data by H3 boundary cells",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This preprocessing step enables fast pack generation:
1. Run once: partitions all data by boundary cell (~6 hours)
2. Build packs: each reads only its partition (~10 seconds)

Output structure (hive-style partitioning):
    output_dir/
    ├── boundary_cell=842b9bdffffffff/
    │   └── data_0.parquet
    ├── boundary_cell=842b9adffffffff/
    │   └── data_0.parquet
    └── ...
        """,
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Directory with sorted eBird parquet files",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output directory for partitioned data",
    )
    parser.add_argument(
        "--boundary-resolution",
        type=int,
        default=4,
        help="H3 resolution for boundary cells (default: 4)",
    )
    parser.add_argument(
        "--memory-limit",
        default="16GB",
        help="DuckDB memory limit (default: 16GB)",
    )
    parser.add_argument(
        "--temp-dir",
        type=Path,
        default=None,
        help="Temp directory for DuckDB (default: output/temp)",
    )
    parser.add_argument(
        "--discover-only",
        action="store_true",
        help="Only discover boundary cells, don't partition",
    )

    args = parser.parse_args()

    if not args.input.exists():
        print(f"Error: Input directory not found: {args.input}")
        return 1

    # Get parquet files
    parquet_files = get_parquet_files(args.input)
    if not parquet_files:
        print(f"Error: No parquet files found in {args.input}")
        return 1

    print("=" * 60)
    print("eBird Data Partitioner")
    print("=" * 60)
    print(f"Input: {args.input}")
    print(f"Output: {args.output}")
    print(f"Boundary resolution: {args.boundary_resolution}")
    print(f"Parquet files: {len(parquet_files)}")
    print()

    # Initialize DuckDB
    print("Initializing DuckDB...")
    ddb = duckdb.connect()
    ddb.execute("INSTALL h3 FROM community; LOAD h3")
    ddb.execute(f"SET memory_limit='{args.memory_limit}'")

    temp_dir = args.temp_dir or (args.output / "temp")
    temp_dir.mkdir(parents=True, exist_ok=True)
    ddb.execute(f"SET temp_directory='{temp_dir}'")

    # Discover boundary cells
    cells = discover_boundary_cells(ddb, parquet_files, args.boundary_resolution)

    if args.discover_only:
        # Write discovery results
        manifest_path = args.output / "boundary_cells.json"
        args.output.mkdir(parents=True, exist_ok=True)
        with open(manifest_path, "w") as f:
            json.dump({"cells": cells}, f, indent=2)
        print(f"\nDiscovery results written to: {manifest_path}")
        return 0

    # Partition data
    stats = partition_data_single_pass(
        ddb, parquet_files, args.output, args.boundary_resolution
    )

    # Clean up temp
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)

    # Write manifest
    manifest = {
        "boundary_resolution": args.boundary_resolution,
        "cells_count": stats["cells_written"],
        "total_size_bytes": stats["total_size_bytes"],
        "source_files": len(parquet_files),
    }

    manifest_path = args.output / "partition_manifest.json"
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
    print("Next step: Run build_packs_from_partitions.py")

    return 0


if __name__ == "__main__":
    exit(main())
