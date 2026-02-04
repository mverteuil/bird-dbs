#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "duckdb>=1.0.0",
#   "h3>=3.7.0",
# ]
# ///
"""
Build a COMPACT region pack SQLite database from eBird Parquet data.

This is an optimized version that removes redundant quarterly/yearly tables.
Monthly data can be aggregated at query time with minimal performance impact.

Key differences from full version:
- No grid_species_quarterly table
- No grid_species_yearly table
- ~30-40% smaller file size
- Slightly slower temporal queries (needs aggregation)

Usage:
    uv run build_region_pack_compact.py --region southern-ontario
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
        "description": "Southern Ontario, Canada - compact prototype",
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

H3_RESOLUTION = 7

TIER_THRESHOLDS = {
    "common": 0.10,
    "uncommon": 0.01,
    "rare": 0.001,
    "vagrant": 0.0,
}

TIER_BOOSTS = {
    "common": 1.5,
    "uncommon": 1.2,
    "rare": 1.0,
    "vagrant": 0.8,
}


def format_size(bytes_size: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_size < 1024:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024
    return f"{bytes_size:.2f} TB"


def format_duration(seconds: float) -> str:
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
    """Create compact schema - NO quarterly/yearly tables."""
    conn.executescript("""
        -- Core species data per cell
        CREATE TABLE grid_species (
            h3_cell INTEGER NOT NULL,
            avibase_id TEXT NOT NULL,
            confidence_tier TEXT NOT NULL,
            confidence_boost REAL NOT NULL,
            yearly_frequency REAL NOT NULL,
            quality_score REAL NOT NULL DEFAULT 0.5,
            PRIMARY KEY (h3_cell, avibase_id)
        );

        -- Monthly frequency data (ONLY temporal table)
        CREATE TABLE grid_species_monthly (
            h3_cell INTEGER NOT NULL,
            avibase_id TEXT NOT NULL,
            month INTEGER NOT NULL,
            frequency REAL NOT NULL,
            checklist_count INTEGER NOT NULL,
            PRIMARY KEY (h3_cell, avibase_id, month)
        );

        -- Species lookup
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
    print("Creating indexes...")
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_grid_species_cell ON grid_species(h3_cell);
        CREATE INDEX IF NOT EXISTS idx_species_monthly_cell ON grid_species_monthly(h3_cell);
        CREATE INDEX IF NOT EXISTS idx_species_lookup_name ON species_lookup(scientific_name);
    """)
    conn.commit()


def get_parquet_files(parquet_dir: Path) -> list[str]:
    files = sorted(parquet_dir.glob("*.parquet"))
    files = [str(f) for f in files if not f.name.startswith("._")]
    return files


def calculate_frequency_data(
    ddb: duckdb.DuckDBPyConnection,
    parquet_dir: Path,
    region: dict,
) -> list:
    parquet_files = get_parquet_files(parquet_dir)
    if not parquet_files:
        raise ValueError(f"No parquet files found in {parquet_dir}")

    print(f"  Found {len(parquet_files)} parquet files")
    file_list = "[" + ", ".join(f"'{f}'" for f in parquet_files) + "]"

    where_clause = f"""
        CAST("LATITUDE" AS DOUBLE) >= {region['lat_min']}
        AND CAST("LATITUDE" AS DOUBLE) < {region['lat_max']}
        AND CAST("LONGITUDE" AS DOUBLE) >= {region['lon_min']}
        AND CAST("LONGITUDE" AS DOUBLE) < {region['lon_max']}
    """

    print("Calculating species frequency data...")

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
        cell_month_totals AS (
            SELECT h3_cell, month, COUNT(DISTINCT checklist_id) as total_checklists
            FROM cell_data
            GROUP BY h3_cell, month
        ),
        species_counts AS (
            SELECT h3_cell, avibase_id, scientific_name, month,
                   COUNT(DISTINCT checklist_id) as species_checklists
            FROM cell_data
            GROUP BY h3_cell, avibase_id, scientific_name, month
        )
        SELECT
            sc.h3_cell, sc.avibase_id, sc.scientific_name, sc.month,
            sc.species_checklists, cmt.total_checklists,
            sc.species_checklists::DOUBLE / cmt.total_checklists::DOUBLE as frequency
        FROM species_counts sc
        JOIN cell_month_totals cmt ON sc.h3_cell = cmt.h3_cell AND sc.month = cmt.month
        ORDER BY sc.h3_cell, sc.avibase_id, sc.month
    """

    start = time.time()
    result = ddb.execute(query).fetchall()
    print(f"  Query completed in {format_duration(time.time() - start)}")
    print(f"  Raw rows: {len(result):,}")

    return result


def process_frequency_data(raw_data: list) -> dict:
    """Process into compact format (monthly only, no quarterly/yearly tables)."""
    print("Processing frequency data...")

    cell_species_data = {}
    species_names = {}

    for h3_cell, avibase_id, scientific_name, month, species_count, total_count, frequency in raw_data:
        key = (h3_cell, avibase_id)

        if key not in cell_species_data:
            cell_species_data[key] = {"months": {}, "scientific_name": scientific_name}

        cell_species_data[key]["months"][month] = {
            "frequency": frequency,
            "species_count": species_count,
        }

        if avibase_id not in species_names:
            species_names[avibase_id] = scientific_name

    print(f"  Unique cell-species: {len(cell_species_data):,}")
    print(f"  Unique species: {len(species_names):,}")

    # Build tables
    monthly = []
    yearly_agg = {}

    for (h3_cell, avibase_id), data in cell_species_data.items():
        for month, month_data in data["months"].items():
            freq = month_data["frequency"]
            count = month_data["species_count"]
            monthly.append((h3_cell, avibase_id, month, freq, count))

            y_key = (h3_cell, avibase_id)
            if y_key not in yearly_agg:
                yearly_agg[y_key] = [0.0, 0, 0]
            yearly_agg[y_key][0] += freq
            yearly_agg[y_key][1] += count
            yearly_agg[y_key][2] += 1

    # grid_species with tiers
    grid_species = []
    for (h3_cell, avibase_id), agg in yearly_agg.items():
        avg_freq = agg[0] / agg[2]

        if avg_freq >= TIER_THRESHOLDS["common"]:
            tier = "common"
        elif avg_freq >= TIER_THRESHOLDS["uncommon"]:
            tier = "uncommon"
        elif avg_freq >= TIER_THRESHOLDS["rare"]:
            tier = "rare"
        else:
            tier = "vagrant"

        boost = TIER_BOOSTS[tier]
        quality = min(1.0, agg[1] / 100)

        grid_species.append((h3_cell, avibase_id, tier, boost, avg_freq, quality))

    species = [(aid, name, None) for aid, name in species_names.items()]

    print(f"  Monthly rows: {len(monthly):,}")
    print(f"  Grid species rows: {len(grid_species):,}")
    print(f"  Species lookup rows: {len(species):,}")

    return {"monthly": monthly, "grid_species": grid_species, "species": species}


def populate_database(conn: sqlite3.Connection, data: dict, region: dict) -> None:
    print("Populating database...")

    print(f"  Inserting {len(data['grid_species']):,} grid_species rows...")
    conn.executemany(
        """INSERT INTO grid_species
           (h3_cell, avibase_id, confidence_tier, confidence_boost, yearly_frequency, quality_score)
           VALUES (?, ?, ?, ?, ?, ?)""",
        data["grid_species"],
    )

    print(f"  Inserting {len(data['monthly']):,} monthly rows...")
    conn.executemany(
        """INSERT INTO grid_species_monthly
           (h3_cell, avibase_id, month, frequency, checklist_count)
           VALUES (?, ?, ?, ?, ?)""",
        data["monthly"],
    )

    print(f"  Inserting {len(data['species']):,} species rows...")
    conn.executemany(
        """INSERT INTO species_lookup (avibase_id, scientific_name, common_name)
           VALUES (?, ?, ?)""",
        data["species"],
    )

    import datetime
    metadata = [
        ("region_name", region["name"]),
        ("format", "compact"),
        ("lat_min", str(region["lat_min"])),
        ("lat_max", str(region["lat_max"])),
        ("lon_min", str(region["lon_min"])),
        ("lon_max", str(region["lon_max"])),
        ("h3_resolution", str(H3_RESOLUTION)),
        ("build_date", datetime.datetime.now().isoformat()),
        ("species_count", str(len(data["species"]))),
        ("cell_count", str(len(set(r[0] for r in data["grid_species"])))),
    ]
    conn.executemany("INSERT INTO pack_metadata (key, value) VALUES (?, ?)", metadata)
    conn.commit()


def build_region_pack(parquet_dir: Path, output_path: Path, region: dict, memory_limit: str = "8GB") -> int:
    print("=" * 60)
    print(f"Building COMPACT Region Pack: {region['name']}")
    print("=" * 60)
    print(f"Output: {output_path}")
    print()

    start_time = time.time()

    print("Initializing DuckDB...")
    ddb = duckdb.connect()
    ddb.execute("INSTALL h3 FROM community; LOAD h3")
    ddb.execute(f"SET memory_limit='{memory_limit}'")

    raw_data = calculate_frequency_data(ddb, parquet_dir, region)
    if not raw_data:
        print("ERROR: No data found!")
        return 1

    data = process_frequency_data(raw_data)

    print(f"\nCreating SQLite database...")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    conn = sqlite3.connect(output_path)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")

    create_schema(conn)
    populate_database(conn, data, region)
    create_indexes(conn)

    conn.execute("PRAGMA journal_mode=WAL")
    print("Running VACUUM...")
    conn.execute("VACUUM")
    conn.execute("ANALYZE")
    conn.commit()
    conn.close()

    elapsed = time.time() - start_time
    file_size = os.path.getsize(output_path)

    print()
    print("=" * 60)
    print("BUILD COMPLETE (COMPACT)")
    print("=" * 60)
    print(f"  Output: {output_path}")
    print(f"  Size: {format_size(file_size)}")
    print(f"  Time: {format_duration(elapsed)}")
    print(f"  Species: {len(data['species']):,}")
    print(f"  Cells: {len(set(r[0] for r in data['grid_species'])):,}")
    print()

    if file_size < 500 * 1024 * 1024:
        print("SIZE CHECK: PASS (< 500 MB for compact)")
    else:
        print(f"SIZE NOTE: {format_size(file_size)}")

    return 0


def main():
    parser = argparse.ArgumentParser(description="Build compact region pack")
    parser.add_argument("--region", choices=list(REGIONS.keys()), required=True)
    parser.add_argument("--parquet-dir", type=Path, default=Path("/Volumes/Lightroom/ebird_by_location"))
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--memory-limit", default="8GB")

    args = parser.parse_args()

    if not args.parquet_dir.exists():
        print(f"Error: Parquet directory not found: {args.parquet_dir}")
        return 1

    region = REGIONS[args.region]
    output_name = args.region.replace("-", "_") + "_compact.db"
    output_path = args.output_dir / output_name

    return build_region_pack(args.parquet_dir, output_path, region, args.memory_limit)


if __name__ == "__main__":
    exit(main())
