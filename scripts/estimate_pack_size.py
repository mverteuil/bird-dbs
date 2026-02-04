#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "duckdb>=1.0.0",
#   "h3>=3.7.0",
# ]
# ///
"""
Estimate region pack SQLite database sizes.

Creates a test SQLite database with the proposed schema, generates sample data
for a subset of cells, measures actual row sizes with indexes, and extrapolates
to full region and global estimates.

Southern Ontario data extent:
- Bounding box: lat 42-46, lon -82 to -74
- Observations: 95M
- Checklists: 8.3M
- Species: 918
- H3 res-7 cells: 39,132
- Sparse matrix rows: 33.7M (cell × month × species with data)
"""

import argparse
import os
import sqlite3
import tempfile
import time
from pathlib import Path

import duckdb


# Southern Ontario bounding box
SOUTHERN_ONTARIO = {
    "name": "Southern Ontario",
    "lat_min": 42.0,
    "lat_max": 46.0,
    "lon_min": -82.0,
    "lon_max": -74.0,
}


def format_size(bytes_size: int) -> str:
    """Format bytes as human-readable size."""
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_size < 1024:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024
    return f"{bytes_size:.2f} TB"


def create_schema(conn: sqlite3.Connection) -> None:
    """Create the region pack schema matching BirdNET-Pi expectations."""
    conn.executescript("""
        -- Core frequency table (matches BirdNET-Pi expectations)
        CREATE TABLE grid_species (
            h3_cell INTEGER,          -- H3 cell as integer (smaller than text)
            avibase_id TEXT,
            confidence_tier TEXT,     -- vagrant/rare/uncommon/common
            confidence_boost REAL,
            yearly_frequency REAL,
            quality_score REAL,
            PRIMARY KEY (h3_cell, avibase_id)
        );

        CREATE TABLE grid_species_monthly (
            h3_cell INTEGER,
            avibase_id TEXT,
            month INTEGER,
            frequency REAL,           -- 0.0-1.0
            checklist_count INTEGER,
            PRIMARY KEY (h3_cell, avibase_id, month)
        );

        CREATE TABLE grid_species_quarterly (
            h3_cell INTEGER,
            avibase_id TEXT,
            quarter INTEGER,          -- 1-4
            frequency REAL,
            checklist_count INTEGER,
            PRIMARY KEY (h3_cell, avibase_id, quarter)
        );

        CREATE TABLE grid_species_yearly (
            h3_cell INTEGER,
            avibase_id TEXT,
            frequency REAL,
            checklist_count INTEGER,
            PRIMARY KEY (h3_cell, avibase_id)
        );

        CREATE TABLE species_lookup (
            avibase_id TEXT PRIMARY KEY,
            scientific_name TEXT,
            common_name TEXT
        );

        -- Indexes for query patterns
        CREATE INDEX idx_grid_species_cell ON grid_species(h3_cell);
        CREATE INDEX idx_species_monthly_cell ON grid_species_monthly(h3_cell);
        CREATE INDEX idx_species_quarterly_cell ON grid_species_quarterly(h3_cell);
        CREATE INDEX idx_species_yearly_cell ON grid_species_yearly(h3_cell);
        CREATE INDEX idx_species_lookup_name ON species_lookup(scientific_name);
    """)
    conn.commit()


def get_region_stats(
    ddb: duckdb.DuckDBPyConnection,
    parquet_dir: Path,
    region: dict,
) -> dict:
    """Get statistics for a region from Parquet data."""
    print(f"Analyzing {region['name']}...")

    # Build WHERE clause for region bounds
    where_clause = f"""
        CAST("LATITUDE" AS DOUBLE) >= {region['lat_min']}
        AND CAST("LATITUDE" AS DOUBLE) < {region['lat_max']}
        AND CAST("LONGITUDE" AS DOUBLE) >= {region['lon_min']}
        AND CAST("LONGITUDE" AS DOUBLE) < {region['lon_max']}
    """

    # Count unique checklists, observations, and species
    stats_query = f"""
        SELECT
            COUNT(*) as observations,
            COUNT(DISTINCT "SAMPLING EVENT IDENTIFIER") as checklists,
            COUNT(DISTINCT "TAXON CONCEPT ID") as species
        FROM read_parquet('{parquet_dir}/*.parquet')
        WHERE {where_clause}
    """

    result = ddb.execute(stats_query).fetchone()
    observations, checklists, species = result

    # Count H3 cells at resolution 7
    h3_query = f"""
        SELECT COUNT(DISTINCT h3_latlng_to_cell(
            CAST("LATITUDE" AS DOUBLE),
            CAST("LONGITUDE" AS DOUBLE),
            7
        )) as cells
        FROM read_parquet('{parquet_dir}/*.parquet')
        WHERE {where_clause}
    """

    h3_cells = ddb.execute(h3_query).fetchone()[0]

    return {
        "observations": observations,
        "checklists": checklists,
        "species": species,
        "h3_cells": h3_cells,
    }


def sample_cells_data(
    ddb: duckdb.DuckDBPyConnection,
    parquet_dir: Path,
    region: dict,
    sample_cells: int = 1000,
) -> tuple[list, list, list, list, list]:
    """Sample data for a subset of cells to measure actual sizes."""
    print(f"Sampling {sample_cells} cells from {region['name']}...")

    where_clause = f"""
        CAST("LATITUDE" AS DOUBLE) >= {region['lat_min']}
        AND CAST("LATITUDE" AS DOUBLE) < {region['lat_max']}
        AND CAST("LONGITUDE" AS DOUBLE) >= {region['lon_min']}
        AND CAST("LONGITUDE" AS DOUBLE) < {region['lon_max']}
    """

    # Get frequency data for sampled cells
    # Calculate species frequency per cell/month
    freq_query = f"""
        WITH cell_data AS (
            SELECT
                h3_latlng_to_cell(
                    CAST("LATITUDE" AS DOUBLE),
                    CAST("LONGITUDE" AS DOUBLE),
                    7
                ) as h3_cell,
                "TAXON CONCEPT ID" as avibase_id,
                CAST(SUBSTR("OBSERVATION DATE", 6, 2) AS INTEGER) as month,
                "SAMPLING EVENT IDENTIFIER" as checklist_id
            FROM read_parquet('{parquet_dir}/*.parquet')
            WHERE {where_clause}
        ),
        -- Get subset of cells
        sampled_cells AS (
            SELECT DISTINCT h3_cell
            FROM cell_data
            ORDER BY h3_cell
            LIMIT {sample_cells}
        ),
        -- Total checklists per cell/month
        cell_month_totals AS (
            SELECT
                cd.h3_cell,
                cd.month,
                COUNT(DISTINCT cd.checklist_id) as total_checklists
            FROM cell_data cd
            JOIN sampled_cells sc ON cd.h3_cell = sc.h3_cell
            GROUP BY cd.h3_cell, cd.month
        ),
        -- Species checklists per cell/month
        species_counts AS (
            SELECT
                cd.h3_cell,
                cd.avibase_id,
                cd.month,
                COUNT(DISTINCT cd.checklist_id) as species_checklists
            FROM cell_data cd
            JOIN sampled_cells sc ON cd.h3_cell = sc.h3_cell
            GROUP BY cd.h3_cell, cd.avibase_id, cd.month
        )
        SELECT
            sc.h3_cell,
            sc.avibase_id,
            sc.month,
            sc.species_checklists,
            cmt.total_checklists,
            sc.species_checklists::DOUBLE / cmt.total_checklists::DOUBLE as frequency
        FROM species_counts sc
        JOIN cell_month_totals cmt ON sc.h3_cell = cmt.h3_cell AND sc.month = cmt.month
    """

    print("  Executing frequency query (this may take a while)...")
    start = time.time()
    result = ddb.execute(freq_query).fetchall()
    elapsed = time.time() - start
    print(f"  Query completed in {elapsed:.1f}s, got {len(result):,} rows")

    # Organize data for insertion
    grid_species = {}  # (h3_cell, avibase_id) -> aggregated data
    monthly_data = []  # (h3_cell, avibase_id, month, frequency, count)
    quarterly_data = {}  # (h3_cell, avibase_id, quarter) -> (freq_sum, count_sum, n)
    yearly_data = {}  # (h3_cell, avibase_id) -> (freq_sum, count_sum, n)
    species_set = set()

    for h3_cell, avibase_id, month, species_count, total_count, frequency in result:
        species_set.add(avibase_id)

        # Monthly data
        monthly_data.append((h3_cell, avibase_id, month, frequency, species_count))

        # Quarterly aggregation
        quarter = ((month - 1) // 3) + 1
        key = (h3_cell, avibase_id, quarter)
        if key not in quarterly_data:
            quarterly_data[key] = [0.0, 0, 0]
        quarterly_data[key][0] += frequency
        quarterly_data[key][1] += species_count
        quarterly_data[key][2] += 1

        # Yearly aggregation
        key = (h3_cell, avibase_id)
        if key not in yearly_data:
            yearly_data[key] = [0.0, 0, 0]
        yearly_data[key][0] += frequency
        yearly_data[key][1] += species_count
        yearly_data[key][2] += 1

        # Grid species (main table)
        if key not in grid_species:
            grid_species[key] = {"yearly_freq": 0.0, "count": 0, "n": 0}
        grid_species[key]["yearly_freq"] += frequency
        grid_species[key]["count"] += species_count
        grid_species[key]["n"] += 1

    # Convert aggregated data to lists
    quarterly_list = [
        (k[0], k[1], k[2], v[0] / v[2], v[1])  # avg frequency
        for k, v in quarterly_data.items()
    ]

    yearly_list = [
        (k[0], k[1], v[0] / v[2], v[1])
        for k, v in yearly_data.items()
    ]

    # Calculate confidence tiers based on yearly frequency
    grid_species_list = []
    for (h3_cell, avibase_id), data in grid_species.items():
        avg_freq = data["yearly_freq"] / data["n"]

        # Confidence tier based on frequency
        if avg_freq >= 0.10:
            tier = "common"
            boost = 1.5
        elif avg_freq >= 0.01:
            tier = "uncommon"
            boost = 1.2
        elif avg_freq >= 0.001:
            tier = "rare"
            boost = 1.0
        else:
            tier = "vagrant"
            boost = 0.8

        grid_species_list.append((
            h3_cell, avibase_id, tier, boost, avg_freq, 0.5  # quality_score placeholder
        ))

    # Species lookup
    species_list = [
        (aid, aid.replace("avibase-", "Genus species"), "Common Name")
        for aid in species_set
    ]

    return grid_species_list, monthly_data, quarterly_list, yearly_list, species_list


def populate_database(
    conn: sqlite3.Connection,
    grid_species: list,
    monthly: list,
    quarterly: list,
    yearly: list,
    species: list,
) -> None:
    """Populate the database with sample data."""
    print("Populating database...")

    conn.executemany(
        """INSERT INTO grid_species
           (h3_cell, avibase_id, confidence_tier, confidence_boost, yearly_frequency, quality_score)
           VALUES (?, ?, ?, ?, ?, ?)""",
        grid_species,
    )

    conn.executemany(
        """INSERT INTO grid_species_monthly
           (h3_cell, avibase_id, month, frequency, checklist_count)
           VALUES (?, ?, ?, ?, ?)""",
        monthly,
    )

    conn.executemany(
        """INSERT INTO grid_species_quarterly
           (h3_cell, avibase_id, quarter, frequency, checklist_count)
           VALUES (?, ?, ?, ?, ?)""",
        quarterly,
    )

    conn.executemany(
        """INSERT INTO grid_species_yearly
           (h3_cell, avibase_id, frequency, checklist_count)
           VALUES (?, ?, ?, ?)""",
        yearly,
    )

    conn.executemany(
        """INSERT INTO species_lookup (avibase_id, scientific_name, common_name)
           VALUES (?, ?, ?)""",
        species,
    )

    conn.commit()


def analyze_sizes(conn: sqlite3.Connection, db_path: Path) -> dict:
    """Analyze actual sizes of database tables."""
    # Get row counts
    counts = {}
    for table in ["grid_species", "grid_species_monthly", "grid_species_quarterly",
                  "grid_species_yearly", "species_lookup"]:
        result = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        counts[table] = result[0]

    # Vacuum to get accurate file size
    conn.execute("VACUUM")
    conn.commit()

    total_size = os.path.getsize(db_path)

    return {
        "row_counts": counts,
        "total_size": total_size,
    }


def estimate_full_region(
    sample_size: dict,
    sample_cells: int,
    total_cells: int,
    sample_species: int,
    total_species: int,
) -> dict:
    """Extrapolate from sample to full region size."""
    # Scale factors
    cell_scale = total_cells / sample_cells
    species_scale = total_species / sample_species

    # Monthly data scales with cells and species
    monthly_rows_estimate = sample_size["row_counts"]["grid_species_monthly"] * cell_scale

    # Grid species scales similarly
    grid_species_estimate = sample_size["row_counts"]["grid_species"] * cell_scale

    # Quarterly/yearly are aggregated
    quarterly_estimate = sample_size["row_counts"]["grid_species_quarterly"] * cell_scale
    yearly_estimate = sample_size["row_counts"]["grid_species_yearly"] * cell_scale

    # Size estimate based on average bytes per row
    sample_total_rows = sum(sample_size["row_counts"].values())
    bytes_per_row = sample_size["total_size"] / sample_total_rows

    estimated_total_rows = (
        monthly_rows_estimate + grid_species_estimate +
        quarterly_estimate + yearly_estimate + total_species
    )

    estimated_size = bytes_per_row * estimated_total_rows

    return {
        "estimated_rows": {
            "grid_species": int(grid_species_estimate),
            "grid_species_monthly": int(monthly_rows_estimate),
            "grid_species_quarterly": int(quarterly_estimate),
            "grid_species_yearly": int(yearly_estimate),
            "species_lookup": total_species,
        },
        "total_rows": int(estimated_total_rows),
        "bytes_per_row": bytes_per_row,
        "estimated_size": estimated_size,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Estimate region pack SQLite database sizes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--parquet-dir",
        type=Path,
        default=Path("/Volumes/Lightroom/ebird_by_location"),
        help="Directory with sorted Parquet files",
    )
    parser.add_argument(
        "--sample-cells",
        type=int,
        default=1000,
        help="Number of cells to sample for size estimation",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for output database (default: temp directory)",
    )
    parser.add_argument(
        "--skip-analysis",
        action="store_true",
        help="Skip Parquet analysis, use hardcoded Southern Ontario stats",
    )

    args = parser.parse_args()

    if not args.parquet_dir.exists():
        print(f"Error: Parquet directory not found: {args.parquet_dir}")
        return 1

    # Initialize DuckDB
    print("Initializing DuckDB...")
    ddb = duckdb.connect()
    ddb.execute("INSTALL h3 FROM community; LOAD h3")
    ddb.execute("SET memory_limit='8GB'")

    region = SOUTHERN_ONTARIO

    # Get or use cached region stats
    if args.skip_analysis:
        print("Using cached Southern Ontario statistics...")
        region_stats = {
            "observations": 95_000_000,
            "checklists": 8_300_000,
            "species": 918,
            "h3_cells": 39_132,
        }
    else:
        region_stats = get_region_stats(ddb, args.parquet_dir, region)

    print(f"\n{region['name']} Statistics:")
    print(f"  Observations: {region_stats['observations']:,}")
    print(f"  Checklists: {region_stats['checklists']:,}")
    print(f"  Species: {region_stats['species']:,}")
    print(f"  H3 res-7 cells: {region_stats['h3_cells']:,}")
    print()

    # Sample cells and measure actual sizes
    grid_species, monthly, quarterly, yearly, species = sample_cells_data(
        ddb, args.parquet_dir, region, args.sample_cells
    )

    # Create test database
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        db_path = args.output_dir / "size_test.db"
    else:
        tmp_dir = tempfile.mkdtemp()
        db_path = Path(tmp_dir) / "size_test.db"

    print(f"\nCreating test database at {db_path}...")

    conn = sqlite3.connect(db_path)
    create_schema(conn)
    populate_database(conn, grid_species, monthly, quarterly, yearly, species)

    # Analyze sizes
    sample_sizes = analyze_sizes(conn, db_path)
    conn.close()

    print(f"\nSample Database ({args.sample_cells} cells):")
    print(f"  Total size: {format_size(sample_sizes['total_size'])}")
    print("  Row counts:")
    for table, count in sample_sizes["row_counts"].items():
        print(f"    {table}: {count:,}")

    # Extrapolate to full region
    estimates = estimate_full_region(
        sample_sizes,
        args.sample_cells,
        region_stats["h3_cells"],
        len(species),
        region_stats["species"],
    )

    print(f"\n{region['name']} Full Estimate ({region_stats['h3_cells']:,} cells):")
    print(f"  Bytes per row: {estimates['bytes_per_row']:.1f}")
    print(f"  Total rows: {estimates['total_rows']:,}")
    print(f"  Estimated size: {format_size(int(estimates['estimated_size']))}")
    print("  Row estimates:")
    for table, count in estimates["estimated_rows"].items():
        print(f"    {table}: {count:,}")

    # Global extrapolation (rough estimate)
    # Assume 10x cells globally, similar species density
    global_multiplier = 10  # Very rough estimate
    global_estimate = estimates["estimated_size"] * global_multiplier

    print(f"\nGlobal Rough Estimate (~{region_stats['h3_cells'] * global_multiplier:,} cells):")
    print(f"  Estimated size: {format_size(int(global_estimate))}")

    print("\n" + "=" * 60)
    print("SIZE ESTIMATION COMPLETE")
    print("=" * 60)
    print(f"\nSouthern Ontario target: < 200 MB")
    print(f"Current estimate: {format_size(int(estimates['estimated_size']))}")

    if estimates["estimated_size"] < 200 * 1024 * 1024:
        print("PASS: Within target size!")
    else:
        print("NOTE: Above target size, but SQLite compression may help")

    return 0


if __name__ == "__main__":
    exit(main())
