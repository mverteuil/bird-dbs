"""Chunked geographic sort for large Parquet datasets.

Partitions data by latitude bands, sorts each partition separately, and writes
sorted partition files. Uses much less temp space than sorting entire dataset.
"""

import shutil
import time
from pathlib import Path

import duckdb

from ebd_pack_builder.utils.formatting import format_duration


# Partition configurations for each sort order
PARTITION_CONFIGS = {
    "location": {
        "description": "Geographic queries - partitioned by latitude bands",
        "partition_column": "LATITUDE",
        # 18 bands of 10 degrees each from -90 to 90, last band inclusive of 90
        "partition_ranges": [
            (-90, -80),
            (-80, -70),
            (-70, -60),
            (-60, -50),
            (-50, -40),
            (-40, -30),
            (-30, -20),
            (-20, -10),
            (-10, 0),
            (0, 10),
            (10, 20),
            (20, 30),
            (30, 40),
            (40, 50),
            (50, 60),
            (60, 70),
            (70, 80),
            (80, 91),  # 91 to include lat=90
        ],
        "sort_columns": [
            '"LATITUDE"',
            '"LONGITUDE"',
            '"GROUP IDENTIFIER" NULLS LAST',
            '"SAMPLING EVENT IDENTIFIER"',
            '"TAXON CONCEPT ID"',
            '"OBSERVATION DATE"',
        ],
    },
    "date": {
        "description": "Temporal queries - smart date partitioning",
        "partition_column": "OBSERVATION DATE",
        "partition_ranges": "DATE_SMART",
        "sort_columns": [
            '"OBSERVATION DATE"',
            '"LATITUDE"',
            '"LONGITUDE"',
            '"TAXON CONCEPT ID"',
        ],
    },
    "taxon": {
        "description": "Species queries - partitioned by taxon prefix",
        "partition_column": "TAXON CONCEPT ID",
        "partition_ranges": "PREFIX",
        "sort_columns": [
            '"TAXON CONCEPT ID"',
            '"OBSERVATION DATE"',
            '"LATITUDE"',
            '"LONGITUDE"',
        ],
    },
}

# Threshold above which a decade gets split into individual years
DATE_SMART_THRESHOLD = 100_000_000  # 100M rows


def get_date_smart_partitions(
    con: duckdb.DuckDBPyConnection, input_dir: Path
) -> list[tuple[int, int, str]]:
    """Smart date partitioning: group small decades, split large ones by year."""
    print("Discovering decade sizes...")
    decades = con.execute(
        f"""
        SELECT
            CAST(SUBSTR("OBSERVATION DATE", 1, 3) || '0' AS INTEGER) AS decade,
            COUNT(*) as cnt
        FROM read_parquet('{input_dir}/*.parquet')
        WHERE "OBSERVATION DATE" IS NOT NULL
        GROUP BY decade
        ORDER BY decade
    """
    ).fetchall()

    partitions: list[tuple[int, int, str]] = []
    small_decades: list[tuple[int, int]] = []

    for decade, cnt in decades:
        if cnt >= DATE_SMART_THRESHOLD:
            # Flush accumulated small decades as one batch
            if small_decades:
                first = small_decades[0][0]
                last = small_decades[-1][0]
                total = sum(d[1] for d in small_decades)
                label = f"pre_{last + 10}" if last + 10 <= 2100 else f"decades_{first}_{last}"
                print(f"  Batch {label}: decades {first}-{last + 9}, ~{total:,} rows")
                partitions.append((first, last + 10, label))
                small_decades = []

            # Split this decade into individual years
            print(f"  Decade {decade}s: {cnt:,} rows -> splitting by year")
            year_counts = con.execute(
                f"""
                SELECT
                    CAST(SUBSTR("OBSERVATION DATE", 1, 4) AS INTEGER) AS year,
                    COUNT(*) as cnt
                FROM read_parquet('{input_dir}/*.parquet')
                WHERE "OBSERVATION DATE" IS NOT NULL
                  AND CAST(SUBSTR("OBSERVATION DATE", 1, 3) || '0' AS INTEGER) = {decade}
                GROUP BY year
                ORDER BY year
            """
            ).fetchall()
            for year, ycnt in year_counts:
                label = f"year_{year}"
                print(f"    {year}: {ycnt:,} rows")
                partitions.append((year, year + 1, label))
        else:
            small_decades.append((decade, cnt))

    # Flush remaining small decades
    if small_decades:
        first = small_decades[0][0]
        last = small_decades[-1][0]
        total = sum(d[1] for d in small_decades)
        label = f"pre_{last + 10}" if last + 10 <= 2100 else f"decades_{first}_{last}"
        print(f"  Batch {label}: decades {first}-{last + 9}, ~{total:,} rows")
        partitions.append((first, last + 10, label))

    print(f"\n  Total partitions: {len(partitions)}")
    return partitions


def get_taxon_prefixes(con: duckdb.DuckDBPyConnection, input_dir: Path) -> list[str]:
    """Get list of unique taxon ID prefixes."""
    print("Discovering taxon prefixes...")
    result = con.execute(
        f"""
        SELECT DISTINCT SUBSTR("TAXON CONCEPT ID", 1, 10) as prefix
        FROM read_parquet('{input_dir}/*.parquet')
        WHERE "TAXON CONCEPT ID" IS NOT NULL
        ORDER BY prefix
    """
    ).fetchall()
    prefixes = [r[0] for r in result if r[0] is not None]
    print(f"  Found {len(prefixes)} unique prefixes")
    return prefixes


def sort_partition(
    con: duckdb.DuckDBPyConnection,
    input_dir: Path,
    output_file: Path,
    partition_filter: str,
    sort_columns: list[str],
) -> int:
    """Sort a single partition and write to output file."""
    order_by = ", ".join(sort_columns)

    query = f"""
    COPY (
        SELECT * FROM read_parquet('{input_dir}/*.parquet')
        WHERE {partition_filter}
        ORDER BY {order_by}
    ) TO '{output_file}' (
        FORMAT PARQUET,
        ROW_GROUP_SIZE 100000,
        COMPRESSION 'ZSTD'
    )
    """

    con.execute(query)

    # Count rows in output
    count = con.execute(f"SELECT COUNT(*) FROM read_parquet('{output_file}')").fetchone()
    return count[0] if count else 0


def sort_chunked(
    input_dir: Path,
    output_dir: Path,
    sort_order: str = "location",
    memory_limit: str = "24GB",
    max_temp_size: str = "200GiB",
) -> dict:
    """Sort data in partitions to reduce temp space requirements.

    Args:
        input_dir: Directory with unsorted Parquet files
        output_dir: Directory for sorted output
        sort_order: Sort order preset (location, date, taxon)
        memory_limit: DuckDB memory limit
        max_temp_size: Max temp size per partition

    Returns:
        Dict with metrics (total_rows, partitions, total_size_bytes, duration)
    """
    if sort_order not in PARTITION_CONFIGS:
        raise ValueError(f"Unknown sort order: {sort_order}")

    config = PARTITION_CONFIGS[sort_order]

    print(f"Chunked sort: {sort_order}")
    print(f"Description: {config['description']}")
    print(f"Input directory: {input_dir}")
    print(f"Output directory: {output_dir}")
    print()

    output_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = output_dir / "temp"
    temp_dir.mkdir(exist_ok=True)

    con = duckdb.connect()
    con.execute(f"SET temp_directory='{temp_dir}'")
    con.execute(f"SET memory_limit='{memory_limit}'")
    con.execute(f"SET max_temp_directory_size='{max_temp_size}'")
    con.execute("SET preserve_insertion_order=false")
    con.execute("SET threads=2")

    print("DuckDB configuration:")
    print(f"  Memory limit: {memory_limit}")
    print(f"  Temp directory: {temp_dir}")
    print(f"  Max temp size: {max_temp_size}")
    print(f"  Threads: 2")
    print()

    # Get partition ranges
    start_time = time.time()

    if config["partition_ranges"] == "DATE_SMART":
        partitions = get_date_smart_partitions(con, input_dir)
        partition_type = "date_smart"
    elif config["partition_ranges"] == "PREFIX":
        prefixes = get_taxon_prefixes(con, input_dir)
        partitions = prefixes  # type: ignore
        partition_type = "prefix"
    else:
        partitions = config["partition_ranges"]  # type: ignore
        partition_type = "range"

    print(f"\nProcessing {len(partitions)} partitions...")
    print(f"Sort columns: {', '.join(config['sort_columns'])}")
    print()

    total_rows = 0
    partition_stats = []

    for i, partition in enumerate(partitions, 1):
        partition_start = time.time()

        # Build filter based on partition type
        if partition_type == "date_smart":
            low, high, label = partition  # type: ignore
            partition_filter = (
                f'CAST(SUBSTR("OBSERVATION DATE", 1, 4) AS INTEGER) >= {low} '
                f'AND CAST(SUBSTR("OBSERVATION DATE", 1, 4) AS INTEGER) < {high}'
            )
            partition_name = label
        elif partition_type == "prefix":
            partition_filter = f"SUBSTR(\"TAXON CONCEPT ID\", 1, 10) = '{partition}'"
            partition_name = f"taxon_{partition.replace('-', '_')}"  # type: ignore
        else:  # range (latitude bands)
            low, high = partition  # type: ignore
            col = config["partition_column"]
            partition_filter = f'CAST("{col}" AS DOUBLE) >= {low} AND CAST("{col}" AS DOUBLE) < {high}'
            partition_name = f"lat_{low:+04d}_to_{high:+04d}".replace("+", "p").replace("-", "n")

        output_file = output_dir / f"ebird_{sort_order}_{partition_name}.parquet"

        print(f"[{i}/{len(partitions)}] {partition_name}...", end=" ", flush=True)

        try:
            rows = sort_partition(con, input_dir, output_file, partition_filter, config["sort_columns"])

            partition_time = time.time() - partition_start
            file_size_mb = output_file.stat().st_size / (1024**2)

            print(f"{rows:,} rows, {file_size_mb:.1f} MB ({format_duration(partition_time)})")

            total_rows += rows
            partition_stats.append(
                {
                    "name": partition_name,
                    "rows": rows,
                    "size_mb": file_size_mb,
                    "time": partition_time,
                }
            )

            # Clean temp after each partition
            for f in temp_dir.glob("*"):
                try:
                    f.unlink()
                except OSError:
                    pass

        except Exception as e:
            print(f"FAILED: {e}")
            continue

    # Summary
    total_time = time.time() - start_time
    output_files = [f for f in output_dir.glob("*.parquet") if not f.name.startswith("._")]
    total_size_bytes = sum(f.stat().st_size for f in output_files)
    total_size_gb = total_size_bytes / (1024**3)

    print()
    print("=" * 60)
    print("CHUNKED SORT COMPLETE")
    print("=" * 60)
    print(f"  Total rows: {total_rows:,}")
    print(f"  Partitions: {len(partition_stats)}")
    print(f"  Total size: {total_size_gb:.2f} GB")
    print(f"  Total time: {format_duration(total_time)}")
    print(f"  Output: {output_dir}")
    print()

    # Cleanup temp
    try:
        shutil.rmtree(temp_dir)
        print("  Temp directory cleaned up")
    except Exception as e:
        print(f"  Warning: Could not clean temp: {e}")

    return {
        "total_rows": total_rows,
        "partitions": len(partition_stats),
        "total_size_bytes": total_size_bytes,
        "duration_seconds": total_time,
    }
