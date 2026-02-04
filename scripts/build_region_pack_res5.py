#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "duckdb>=1.0.0",
#   "h3>=3.7.0",
# ]
# ///
"""
Build region pack with H3 resolution 5 (~90km cells) instead of 7 (~5km).

This is a coarser resolution version for testing size targets.
Resolution 5 has ~49x fewer cells than resolution 7.

Trade-offs:
- Much smaller database size
- Less precise location data
- Good for initial filtering, may need fallback refinement
"""

import argparse
import os
import sqlite3
import time
from pathlib import Path

import duckdb


REGIONS = {
    "southern-ontario": {
        "name": "Southern Ontario",
        "lat_min": 42.0,
        "lat_max": 46.0,
        "lon_min": -82.0,
        "lon_max": -74.0,
        "description": "Southern Ontario - H3 resolution 5",
    },
}

H3_RESOLUTION = 5  # Coarser: ~252.9 km² vs ~5.16 km² at res 7

TIER_THRESHOLDS = {"common": 0.10, "uncommon": 0.01, "rare": 0.001, "vagrant": 0.0}
TIER_BOOSTS = {"common": 1.5, "uncommon": 1.2, "rare": 1.0, "vagrant": 0.8}


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
    files = sorted(parquet_dir.glob("*.parquet"))
    return [str(f) for f in files if not f.name.startswith("._")]


def build_region_pack(parquet_dir: Path, output_path: Path, region: dict) -> int:
    print("=" * 60)
    print(f"Building Region Pack (Resolution 5): {region['name']}")
    print("=" * 60)
    print(f"H3 Resolution: {H3_RESOLUTION} (~253 km² cells)")
    print()

    start_time = time.time()

    parquet_files = get_parquet_files(parquet_dir)
    file_list = "[" + ", ".join(f"'{f}'" for f in parquet_files) + "]"

    print("Initializing DuckDB...")
    ddb = duckdb.connect()
    ddb.execute("INSTALL h3 FROM community; LOAD h3")
    ddb.execute("SET memory_limit='8GB'")

    where_clause = f"""
        CAST("LATITUDE" AS DOUBLE) >= {region['lat_min']}
        AND CAST("LATITUDE" AS DOUBLE) < {region['lat_max']}
        AND CAST("LONGITUDE" AS DOUBLE) >= {region['lon_min']}
        AND CAST("LONGITUDE" AS DOUBLE) < {region['lon_max']}
    """

    print("Calculating frequency data...")
    query = f"""
        WITH cell_data AS (
            SELECT
                h3_latlng_to_cell(CAST("LATITUDE" AS DOUBLE), CAST("LONGITUDE" AS DOUBLE), {H3_RESOLUTION}) as h3_cell,
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
            FROM cell_data GROUP BY h3_cell, month
        ),
        species_counts AS (
            SELECT h3_cell, avibase_id, scientific_name, month, COUNT(DISTINCT checklist_id) as species_checklists
            FROM cell_data GROUP BY h3_cell, avibase_id, scientific_name, month
        )
        SELECT sc.h3_cell, sc.avibase_id, sc.scientific_name, sc.month, sc.species_checklists, cmt.total_checklists,
               sc.species_checklists::DOUBLE / cmt.total_checklists::DOUBLE as frequency
        FROM species_counts sc
        JOIN cell_month_totals cmt ON sc.h3_cell = cmt.h3_cell AND sc.month = cmt.month
    """

    result = ddb.execute(query).fetchall()
    print(f"  Raw rows: {len(result):,}")

    # Process data
    cell_species_data = {}
    species_names = {}

    for h3_cell, avibase_id, scientific_name, month, species_count, total_count, frequency in result:
        key = (h3_cell, avibase_id)
        if key not in cell_species_data:
            cell_species_data[key] = {"months": {}, "name": scientific_name}
        cell_species_data[key]["months"][month] = {"freq": frequency, "count": species_count}
        if avibase_id not in species_names:
            species_names[avibase_id] = scientific_name

    print(f"  Unique cell-species: {len(cell_species_data):,}")
    print(f"  Unique species: {len(species_names):,}")

    # Build tables
    monthly = []
    grid_species = []

    for (h3_cell, avibase_id), data in cell_species_data.items():
        freqs = []
        total_count = 0
        for month, md in data["months"].items():
            monthly.append((h3_cell, avibase_id, month, md["freq"], md["count"]))
            freqs.append(md["freq"])
            total_count += md["count"]

        avg_freq = sum(freqs) / len(freqs)
        if avg_freq >= 0.10:
            tier, boost = "common", 1.5
        elif avg_freq >= 0.01:
            tier, boost = "uncommon", 1.2
        elif avg_freq >= 0.001:
            tier, boost = "rare", 1.0
        else:
            tier, boost = "vagrant", 0.8

        grid_species.append((h3_cell, avibase_id, tier, boost, avg_freq, min(1.0, total_count / 100)))

    species = [(aid, name, None) for aid, name in species_names.items()]

    print(f"  Monthly rows: {len(monthly):,}")
    print(f"  Grid species rows: {len(grid_species):,}")

    # Create database
    print(f"\nCreating SQLite database...")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    conn = sqlite3.connect(output_path)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")

    conn.executescript("""
        CREATE TABLE grid_species (
            h3_cell INTEGER NOT NULL, avibase_id TEXT NOT NULL,
            confidence_tier TEXT NOT NULL, confidence_boost REAL NOT NULL,
            yearly_frequency REAL NOT NULL, quality_score REAL NOT NULL DEFAULT 0.5,
            PRIMARY KEY (h3_cell, avibase_id)
        );
        CREATE TABLE grid_species_monthly (
            h3_cell INTEGER NOT NULL, avibase_id TEXT NOT NULL, month INTEGER NOT NULL,
            frequency REAL NOT NULL, checklist_count INTEGER NOT NULL,
            PRIMARY KEY (h3_cell, avibase_id, month)
        );
        CREATE TABLE species_lookup (
            avibase_id TEXT PRIMARY KEY, scientific_name TEXT NOT NULL, common_name TEXT
        );
        CREATE TABLE pack_metadata (key TEXT PRIMARY KEY, value TEXT);
    """)

    conn.executemany("INSERT INTO grid_species VALUES (?,?,?,?,?,?)", grid_species)
    conn.executemany("INSERT INTO grid_species_monthly VALUES (?,?,?,?,?)", monthly)
    conn.executemany("INSERT INTO species_lookup VALUES (?,?,?)", species)

    import datetime
    conn.executemany("INSERT INTO pack_metadata VALUES (?,?)", [
        ("region_name", region["name"]),
        ("h3_resolution", str(H3_RESOLUTION)),
        ("build_date", datetime.datetime.now().isoformat()),
        ("species_count", str(len(species))),
        ("cell_count", str(len(set(r[0] for r in grid_species)))),
    ])

    conn.executescript("""
        CREATE INDEX idx_grid_species_cell ON grid_species(h3_cell);
        CREATE INDEX idx_species_monthly_cell ON grid_species_monthly(h3_cell);
        CREATE INDEX idx_species_lookup_name ON species_lookup(scientific_name);
    """)

    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("VACUUM")
    conn.execute("ANALYZE")
    conn.commit()
    conn.close()

    elapsed = time.time() - start_time
    file_size = os.path.getsize(output_path)

    print()
    print("=" * 60)
    print("BUILD COMPLETE (Resolution 5)")
    print("=" * 60)
    print(f"  Output: {output_path}")
    print(f"  Size: {format_size(file_size)}")
    print(f"  Time: {format_duration(elapsed)}")
    print(f"  Species: {len(species):,}")
    print(f"  Cells: {len(set(r[0] for r in grid_species)):,}")
    print()

    target = 200 * 1024 * 1024
    if file_size < target:
        print(f"SIZE CHECK: PASS (< 200 MB target)")
    else:
        print(f"SIZE CHECK: {format_size(file_size)} (target: 200 MB)")

    return 0


def main():
    parser = argparse.ArgumentParser(description="Build region pack with H3 resolution 5")
    parser.add_argument("--region", choices=list(REGIONS.keys()), required=True)
    parser.add_argument("--parquet-dir", type=Path, default=Path("/Volumes/Lightroom/ebird_by_location"))
    parser.add_argument("--output-dir", type=Path, default=Path("output"))

    args = parser.parse_args()
    if not args.parquet_dir.exists():
        return 1

    region = REGIONS[args.region]
    output_path = args.output_dir / f"{args.region.replace('-', '_')}_res5.db"
    return build_region_pack(args.parquet_dir, output_path, region)


if __name__ == "__main__":
    exit(main())
