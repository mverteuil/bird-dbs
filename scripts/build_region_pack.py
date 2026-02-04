#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "duckdb>=1.0.0",
#   "h3>=3.7.0",
# ]
# ///
"""
Build a region pack SQLite database from eBird Parquet data.

This script generates a complete, working region pack for a given region:
1. Aggregates Parquet data to the pack schema
2. Calculates confidence tiers from frequency distribution
3. Exports to SQLite with proper indexes
4. Validates against BirdNET-Pi expectations

Usage:
    uv run build_region_pack.py --region southern-ontario

Output:
    output/southern_ontario.db (~100-200 MB)
"""

import argparse
import os
import sqlite3
import time
from pathlib import Path

import duckdb


# Region definitions
REGIONS = {
    "southern-ontario": {
        "name": "Southern Ontario",
        "lat_min": 42.0,
        "lat_max": 46.0,
        "lon_min": -82.0,
        "lon_max": -74.0,
        "description": "Southern Ontario, Canada - prototype region pack",
    },
    "toronto-metro": {
        "name": "Toronto Metro",
        "lat_min": 43.4,
        "lat_max": 44.0,
        "lon_min": -79.8,
        "lon_max": -79.0,
        "description": "Greater Toronto Area - smaller test region",
    },
}

# H3 resolution for the grid
H3_RESOLUTION = 7  # ~5.16 km² per cell

# Confidence tier thresholds (based on reporting frequency)
TIER_THRESHOLDS = {
    "common": 0.10,      # 10%+ of checklists
    "uncommon": 0.01,    # 1-10% of checklists
    "rare": 0.001,       # 0.1-1% of checklists
    "vagrant": 0.0,      # <0.1% of checklists
}

# Confidence boost values per tier
TIER_BOOSTS = {
    "common": 1.5,
    "uncommon": 1.2,
    "rare": 1.0,
    "vagrant": 0.8,
}


def format_size(bytes_size: int) -> str:
    """Format bytes as human-readable size."""
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_size < 1024:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024
    return f"{bytes_size:.2f} TB"


def format_duration(seconds: float) -> str:
    """Format seconds as human-readable duration."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"


def create_schema(conn: sqlite3.Connection) -> None:
    """Create the region pack schema matching BirdNET-Pi expectations."""
    conn.executescript("""
        -- Core species data per cell (main lookup table)
        CREATE TABLE grid_species (
            h3_cell INTEGER NOT NULL,
            avibase_id TEXT NOT NULL,
            confidence_tier TEXT NOT NULL,
            confidence_boost REAL NOT NULL,
            yearly_frequency REAL NOT NULL,
            quality_score REAL NOT NULL DEFAULT 0.5,
            PRIMARY KEY (h3_cell, avibase_id)
        );

        -- Monthly frequency data
        CREATE TABLE grid_species_monthly (
            h3_cell INTEGER NOT NULL,
            avibase_id TEXT NOT NULL,
            month INTEGER NOT NULL,
            frequency REAL NOT NULL,
            checklist_count INTEGER NOT NULL,
            PRIMARY KEY (h3_cell, avibase_id, month)
        );

        -- Quarterly frequency data (aggregated from monthly)
        CREATE TABLE grid_species_quarterly (
            h3_cell INTEGER NOT NULL,
            avibase_id TEXT NOT NULL,
            quarter INTEGER NOT NULL,
            frequency REAL NOT NULL,
            checklist_count INTEGER NOT NULL,
            PRIMARY KEY (h3_cell, avibase_id, quarter)
        );

        -- Yearly frequency data (aggregated)
        CREATE TABLE grid_species_yearly (
            h3_cell INTEGER NOT NULL,
            avibase_id TEXT NOT NULL,
            frequency REAL NOT NULL,
            checklist_count INTEGER NOT NULL,
            PRIMARY KEY (h3_cell, avibase_id)
        );

        -- Species lookup (avibase_id → names)
        CREATE TABLE species_lookup (
            avibase_id TEXT PRIMARY KEY,
            scientific_name TEXT NOT NULL,
            common_name TEXT
        );

        -- Pack metadata
        CREATE TABLE pack_metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    conn.commit()


def create_indexes(conn: sqlite3.Connection) -> None:
    """Create indexes after bulk data load for better performance."""
    print("Creating indexes...")
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_grid_species_cell ON grid_species(h3_cell);
        CREATE INDEX IF NOT EXISTS idx_species_monthly_cell ON grid_species_monthly(h3_cell);
        CREATE INDEX IF NOT EXISTS idx_species_monthly_cell_month ON grid_species_monthly(h3_cell, month);
        CREATE INDEX IF NOT EXISTS idx_species_quarterly_cell ON grid_species_quarterly(h3_cell);
        CREATE INDEX IF NOT EXISTS idx_species_yearly_cell ON grid_species_yearly(h3_cell);
        CREATE INDEX IF NOT EXISTS idx_species_lookup_name ON species_lookup(scientific_name);
    """)
    conn.commit()


def get_parquet_files(parquet_dir: Path) -> list[str]:
    """Get list of parquet files, excluding macOS extended attribute files."""
    files = sorted(parquet_dir.glob("*.parquet"))
    # Filter out macOS extended attribute files (._*)
    files = [str(f) for f in files if not f.name.startswith("._")]
    return files


def calculate_frequency_data(
    ddb: duckdb.DuckDBPyConnection,
    parquet_dir: Path,
    region: dict,
    sampling_parquet: Path | None = None,
) -> tuple:
    """
    Calculate species frequency data from Parquet.

    Returns:
        Tuple of (monthly_data, species_set, cell_checklist_counts)
    """
    # Get clean file list (excluding macOS ._ files)
    parquet_files = get_parquet_files(parquet_dir)
    if not parquet_files:
        raise ValueError(f"No parquet files found in {parquet_dir}")

    print(f"  Found {len(parquet_files)} parquet files")

    # Create a file list for DuckDB
    file_list = "[" + ", ".join(f"'{f}'" for f in parquet_files) + "]"

    where_clause = f"""
        CAST("LATITUDE" AS DOUBLE) >= {region['lat_min']}
        AND CAST("LATITUDE" AS DOUBLE) < {region['lat_max']}
        AND CAST("LONGITUDE" AS DOUBLE) >= {region['lon_min']}
        AND CAST("LONGITUDE" AS DOUBLE) < {region['lon_max']}
    """

    print("Calculating species frequency data...")
    print("  (This may take several minutes for large regions)")

    # Main query: Calculate frequency per cell/month/species
    query = f"""
        WITH cell_data AS (
            SELECT
                h3_latlng_to_cell(
                    CAST("LATITUDE" AS DOUBLE),
                    CAST("LONGITUDE" AS DOUBLE),
                    {H3_RESOLUTION}
                ) as h3_cell,
                "TAXON CONCEPT ID" as avibase_id,
                "SCIENTIFIC NAME" as scientific_name,
                CAST(SUBSTR("OBSERVATION DATE", 6, 2) AS INTEGER) as month,
                "SAMPLING EVENT IDENTIFIER" as checklist_id
            FROM read_parquet({file_list})
            WHERE {where_clause}
                AND "TAXON CONCEPT ID" IS NOT NULL
                AND "OBSERVATION DATE" IS NOT NULL
        ),
        -- Total checklists per cell/month
        cell_month_totals AS (
            SELECT
                h3_cell,
                month,
                COUNT(DISTINCT checklist_id) as total_checklists
            FROM cell_data
            GROUP BY h3_cell, month
        ),
        -- Species checklists per cell/month
        species_counts AS (
            SELECT
                h3_cell,
                avibase_id,
                scientific_name,
                month,
                COUNT(DISTINCT checklist_id) as species_checklists
            FROM cell_data
            GROUP BY h3_cell, avibase_id, scientific_name, month
        )
        SELECT
            sc.h3_cell,
            sc.avibase_id,
            sc.scientific_name,
            sc.month,
            sc.species_checklists,
            cmt.total_checklists,
            sc.species_checklists::DOUBLE / cmt.total_checklists::DOUBLE as frequency
        FROM species_counts sc
        JOIN cell_month_totals cmt
            ON sc.h3_cell = cmt.h3_cell AND sc.month = cmt.month
        ORDER BY sc.h3_cell, sc.avibase_id, sc.month
    """

    start = time.time()
    result = ddb.execute(query).fetchall()
    elapsed = time.time() - start
    print(f"  Query completed in {format_duration(elapsed)}")
    print(f"  Raw rows: {len(result):,}")

    return result


def process_frequency_data(raw_data: list) -> dict:
    """
    Process raw frequency data into structured tables.

    Returns dict with:
        - monthly: list of (h3_cell, avibase_id, month, frequency, count)
        - quarterly: list of (h3_cell, avibase_id, quarter, frequency, count)
        - yearly: list of (h3_cell, avibase_id, frequency, count)
        - grid_species: list of (h3_cell, avibase_id, tier, boost, yearly_freq, quality)
        - species: list of (avibase_id, scientific_name, common_name)
    """
    print("Processing frequency data...")

    # Organize by cell/species
    cell_species_data = {}  # (h3_cell, avibase_id) -> {months: {}, scientific_name: str}
    species_names = {}  # avibase_id -> scientific_name

    for h3_cell, avibase_id, scientific_name, month, species_count, total_count, frequency in raw_data:
        key = (h3_cell, avibase_id)

        if key not in cell_species_data:
            cell_species_data[key] = {"months": {}, "scientific_name": scientific_name}

        cell_species_data[key]["months"][month] = {
            "frequency": frequency,
            "species_count": species_count,
            "total_count": total_count,
        }

        if avibase_id not in species_names:
            species_names[avibase_id] = scientific_name

    print(f"  Unique cell-species combinations: {len(cell_species_data):,}")
    print(f"  Unique species: {len(species_names):,}")

    # Build output tables
    monthly = []
    quarterly_agg = {}  # (h3_cell, avibase_id, quarter) -> (freq_sum, count_sum, n)
    yearly_agg = {}  # (h3_cell, avibase_id) -> (freq_sum, count_sum, n)

    for (h3_cell, avibase_id), data in cell_species_data.items():
        for month, month_data in data["months"].items():
            freq = month_data["frequency"]
            count = month_data["species_count"]

            # Monthly
            monthly.append((h3_cell, avibase_id, month, freq, count))

            # Quarterly aggregation
            quarter = ((month - 1) // 3) + 1
            q_key = (h3_cell, avibase_id, quarter)
            if q_key not in quarterly_agg:
                quarterly_agg[q_key] = [0.0, 0, 0]
            quarterly_agg[q_key][0] += freq
            quarterly_agg[q_key][1] += count
            quarterly_agg[q_key][2] += 1

            # Yearly aggregation
            y_key = (h3_cell, avibase_id)
            if y_key not in yearly_agg:
                yearly_agg[y_key] = [0.0, 0, 0]
            yearly_agg[y_key][0] += freq
            yearly_agg[y_key][1] += count
            yearly_agg[y_key][2] += 1

    # Convert aggregations to lists
    quarterly = [
        (k[0], k[1], k[2], v[0] / v[2], v[1])  # avg frequency
        for k, v in quarterly_agg.items()
    ]

    yearly = [
        (k[0], k[1], v[0] / v[2], v[1])
        for k, v in yearly_agg.items()
    ]

    # Calculate confidence tiers and build grid_species
    grid_species = []
    for (h3_cell, avibase_id), agg in yearly_agg.items():
        avg_freq = agg[0] / agg[2]

        # Determine tier based on frequency
        if avg_freq >= TIER_THRESHOLDS["common"]:
            tier = "common"
        elif avg_freq >= TIER_THRESHOLDS["uncommon"]:
            tier = "uncommon"
        elif avg_freq >= TIER_THRESHOLDS["rare"]:
            tier = "rare"
        else:
            tier = "vagrant"

        boost = TIER_BOOSTS[tier]

        # Quality score based on total observations (simple heuristic)
        total_obs = agg[1]
        quality = min(1.0, total_obs / 100)  # Cap at 1.0 for 100+ observations

        grid_species.append((h3_cell, avibase_id, tier, boost, avg_freq, quality))

    # Species lookup
    species = [
        (avibase_id, scientific_name, None)  # common_name filled from IOC later
        for avibase_id, scientific_name in species_names.items()
    ]

    print(f"  Monthly rows: {len(monthly):,}")
    print(f"  Quarterly rows: {len(quarterly):,}")
    print(f"  Yearly rows: {len(yearly):,}")
    print(f"  Grid species rows: {len(grid_species):,}")
    print(f"  Species lookup rows: {len(species):,}")

    return {
        "monthly": monthly,
        "quarterly": quarterly,
        "yearly": yearly,
        "grid_species": grid_species,
        "species": species,
    }


def populate_database(conn: sqlite3.Connection, data: dict, region: dict) -> None:
    """Populate the database with processed data."""
    print("Populating database...")

    # Insert grid_species
    print(f"  Inserting {len(data['grid_species']):,} grid_species rows...")
    conn.executemany(
        """INSERT INTO grid_species
           (h3_cell, avibase_id, confidence_tier, confidence_boost, yearly_frequency, quality_score)
           VALUES (?, ?, ?, ?, ?, ?)""",
        data["grid_species"],
    )

    # Insert monthly data
    print(f"  Inserting {len(data['monthly']):,} monthly rows...")
    conn.executemany(
        """INSERT INTO grid_species_monthly
           (h3_cell, avibase_id, month, frequency, checklist_count)
           VALUES (?, ?, ?, ?, ?)""",
        data["monthly"],
    )

    # Insert quarterly data
    print(f"  Inserting {len(data['quarterly']):,} quarterly rows...")
    conn.executemany(
        """INSERT INTO grid_species_quarterly
           (h3_cell, avibase_id, quarter, frequency, checklist_count)
           VALUES (?, ?, ?, ?, ?)""",
        data["quarterly"],
    )

    # Insert yearly data
    print(f"  Inserting {len(data['yearly']):,} yearly rows...")
    conn.executemany(
        """INSERT INTO grid_species_yearly
           (h3_cell, avibase_id, frequency, checklist_count)
           VALUES (?, ?, ?, ?)""",
        data["yearly"],
    )

    # Insert species lookup
    print(f"  Inserting {len(data['species']):,} species rows...")
    conn.executemany(
        """INSERT INTO species_lookup (avibase_id, scientific_name, common_name)
           VALUES (?, ?, ?)""",
        data["species"],
    )

    # Insert metadata
    import datetime
    metadata = [
        ("region_name", region["name"]),
        ("region_description", region["description"]),
        ("lat_min", str(region["lat_min"])),
        ("lat_max", str(region["lat_max"])),
        ("lon_min", str(region["lon_min"])),
        ("lon_max", str(region["lon_max"])),
        ("h3_resolution", str(H3_RESOLUTION)),
        ("build_date", datetime.datetime.now().isoformat()),
        ("species_count", str(len(data["species"]))),
        ("cell_count", str(len(set(r[0] for r in data["grid_species"])))),
    ]
    conn.executemany(
        "INSERT INTO pack_metadata (key, value) VALUES (?, ?)",
        metadata,
    )

    conn.commit()


def validate_database(conn: sqlite3.Connection) -> dict:
    """Validate the database structure and data."""
    print("Validating database...")

    results = {}

    # Check row counts
    tables = ["grid_species", "grid_species_monthly", "grid_species_quarterly",
              "grid_species_yearly", "species_lookup", "pack_metadata"]

    for table in tables:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        results[f"{table}_count"] = count
        print(f"  {table}: {count:,} rows")

    # Check confidence tier distribution
    tier_dist = conn.execute("""
        SELECT confidence_tier, COUNT(*) as cnt
        FROM grid_species
        GROUP BY confidence_tier
        ORDER BY cnt DESC
    """).fetchall()

    print("  Confidence tier distribution:")
    for tier, count in tier_dist:
        print(f"    {tier}: {count:,}")

    # Check for missing species lookups
    missing = conn.execute("""
        SELECT COUNT(DISTINCT gs.avibase_id)
        FROM grid_species gs
        LEFT JOIN species_lookup sl ON gs.avibase_id = sl.avibase_id
        WHERE sl.avibase_id IS NULL
    """).fetchone()[0]

    if missing > 0:
        print(f"  WARNING: {missing} species in grid_species without lookup entry")
    else:
        print("  All species have lookup entries")

    results["valid"] = missing == 0

    return results


def build_region_pack(
    parquet_dir: Path,
    output_path: Path,
    region: dict,
    memory_limit: str = "8GB",
) -> int:
    """Build a complete region pack database."""
    print("=" * 60)
    print(f"Building Region Pack: {region['name']}")
    print("=" * 60)
    print(f"Parquet source: {parquet_dir}")
    print(f"Output: {output_path}")
    print(f"Bounds: lat [{region['lat_min']}, {region['lat_max']}], "
          f"lon [{region['lon_min']}, {region['lon_max']}]")
    print()

    start_time = time.time()

    # Initialize DuckDB
    print("Initializing DuckDB...")
    ddb = duckdb.connect()
    ddb.execute("INSTALL h3 FROM community; LOAD h3")
    ddb.execute(f"SET memory_limit='{memory_limit}'")
    ddb.execute("SET preserve_insertion_order=false")

    # Calculate frequency data
    raw_data = calculate_frequency_data(ddb, parquet_dir, region)

    if not raw_data:
        print("ERROR: No data found for region!")
        return 1

    # Process into tables
    data = process_frequency_data(raw_data)

    # Create SQLite database
    print(f"\nCreating SQLite database at {output_path}...")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Remove existing database
    if output_path.exists():
        output_path.unlink()

    conn = sqlite3.connect(output_path)

    # Optimize for bulk insert
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA cache_size=100000")

    # Create schema and populate
    create_schema(conn)
    populate_database(conn, data, region)
    create_indexes(conn)

    # Re-enable journaling for production use
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    # Validate
    validation = validate_database(conn)

    # Optimize
    print("Running VACUUM...")
    conn.execute("VACUUM")
    conn.execute("ANALYZE")
    conn.commit()
    conn.close()

    # Final stats
    elapsed = time.time() - start_time
    file_size = os.path.getsize(output_path)

    print()
    print("=" * 60)
    print("BUILD COMPLETE")
    print("=" * 60)
    print(f"  Output: {output_path}")
    print(f"  Size: {format_size(file_size)}")
    print(f"  Time: {format_duration(elapsed)}")
    print(f"  Species: {validation['species_lookup_count']:,}")
    print(f"  Cells: {len(set(r[0] for r in data['grid_species'])):,}")
    print(f"  Grid species rows: {validation['grid_species_count']:,}")
    print(f"  Monthly rows: {validation['grid_species_monthly_count']:,}")
    print()

    if file_size < 200 * 1024 * 1024:
        print("SIZE CHECK: PASS (< 200 MB target)")
    else:
        print(f"SIZE CHECK: WARNING ({format_size(file_size)} > 200 MB target)")

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Build a region pack SQLite database from eBird Parquet data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Available regions:
  southern-ontario  Southern Ontario, Canada (prototype)
  toronto-metro     Greater Toronto Area (smaller test)

Example:
  uv run build_region_pack.py --region southern-ontario
  uv run build_region_pack.py --region toronto-metro --output-dir ./test
        """,
    )
    parser.add_argument(
        "--region",
        choices=list(REGIONS.keys()),
        required=True,
        help="Region to build pack for",
    )
    parser.add_argument(
        "--parquet-dir",
        type=Path,
        default=Path("/Volumes/Lightroom/ebird_by_location"),
        help="Directory with sorted Parquet files",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="Directory for output database",
    )
    parser.add_argument(
        "--memory-limit",
        default="8GB",
        help="DuckDB memory limit (default: 8GB)",
    )

    args = parser.parse_args()

    if not args.parquet_dir.exists():
        print(f"Error: Parquet directory not found: {args.parquet_dir}")
        return 1

    region = REGIONS[args.region]
    output_name = args.region.replace("-", "_") + ".db"
    output_path = args.output_dir / output_name

    return build_region_pack(
        args.parquet_dir,
        output_path,
        region,
        args.memory_limit,
    )


if __name__ == "__main__":
    exit(main())
