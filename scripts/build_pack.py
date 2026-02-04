#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "duckdb>=1.0.0",
#   "h3>=3.7.0",
# ]
# ///
"""
Build a single region pack for an H3 boundary cell.

This implements the dual-resolution architecture from ebird-region-pack-strategy.md:
- Boundary resolution (coarse): Defines geographic extent (e.g., res 4 = ~22km)
- Data resolution (fine): Internal hexagon granularity (e.g., res 7 = ~1.2km)

The pack is self-contained and matches the manifest format for upload/discovery.

Usage:
    # Build pack for Toronto area (H3 res-4 cell)
    uv run build_pack.py --boundary-cell 842b9adffffffff --data-resolution 7

    # Auto-detect boundary cell from lat/lon
    uv run build_pack.py --lat 43.65 --lon -79.38 --boundary-resolution 4 --data-resolution 7
"""

import argparse
import json
import os
import sqlite3
import time
from pathlib import Path

import duckdb
import h3


# Confidence tier thresholds (reporting frequency)
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


def get_boundary_bbox(boundary_cell: str) -> dict:
    """Get bounding box for an H3 boundary cell."""
    boundary = h3.cell_to_boundary(boundary_cell)
    lats = [lat for lat, _ in boundary]
    lons = [lon for _, lon in boundary]
    return {
        "lat_min": min(lats),
        "lat_max": max(lats),
        "lon_min": min(lons),
        "lon_max": max(lons),
    }


def get_data_cells(boundary_cell: str, data_resolution: int) -> set[str]:
    """Get all data-resolution cells within a boundary cell."""
    boundary_res = h3.get_resolution(boundary_cell)
    if data_resolution <= boundary_res:
        raise ValueError(f"Data resolution {data_resolution} must be > boundary resolution {boundary_res}")

    # Get all children at data resolution
    return set(h3.cell_to_children(boundary_cell, data_resolution))


def get_parquet_files(parquet_dir: Path) -> list[str]:
    """Get list of parquet files, excluding macOS extended attribute files."""
    files = sorted(parquet_dir.glob("*.parquet"))
    return [str(f) for f in files if not f.name.startswith("._")]


def create_schema(conn: sqlite3.Connection) -> None:
    """Create pack schema matching BirdNET-Pi expectations."""
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

        -- Monthly frequency data
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

        -- Pack metadata (matches manifest format)
        CREATE TABLE pack_metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    conn.commit()


def build_pack(
    parquet_dir: Path,
    output_dir: Path,
    boundary_cell: str,
    data_resolution: int,
    memory_limit: str = "8GB",
) -> dict:
    """Build a single region pack."""
    boundary_res = h3.get_resolution(boundary_cell)
    center_lat, center_lon = h3.cell_to_latlng(boundary_cell)
    bbox = get_boundary_bbox(boundary_cell)

    pack_id = f"h3-r{boundary_res}-{boundary_cell}-data-r{data_resolution}"
    output_path = output_dir / f"{pack_id}.db"

    print("=" * 60)
    print(f"Building Pack: {pack_id}")
    print("=" * 60)
    print(f"  Boundary cell: {boundary_cell} (res {boundary_res})")
    print(f"  Data resolution: {data_resolution}")
    print(f"  Center: ({center_lat:.4f}, {center_lon:.4f})")
    print(f"  BBox: lat [{bbox['lat_min']:.2f}, {bbox['lat_max']:.2f}], "
          f"lon [{bbox['lon_min']:.2f}, {bbox['lon_max']:.2f}]")
    print()

    start_time = time.time()

    # Get parquet files
    parquet_files = get_parquet_files(parquet_dir)
    if not parquet_files:
        raise ValueError(f"No parquet files found in {parquet_dir}")

    print(f"Found {len(parquet_files)} parquet files")

    # Initialize DuckDB
    print("Initializing DuckDB...")
    ddb = duckdb.connect()
    ddb.execute("INSTALL h3 FROM community; LOAD h3")
    ddb.execute(f"SET memory_limit='{memory_limit}'")

    file_list = "[" + ", ".join(f"'{f}'" for f in parquet_files) + "]"

    # Get data cells within boundary
    data_cells = get_data_cells(boundary_cell, data_resolution)
    print(f"Data cells within boundary: {len(data_cells)}")

    # Build WHERE clause using bounding box (more efficient than cell list)
    # Add small buffer to ensure we capture boundary cells
    buffer = 0.5  # degrees
    where_clause = f"""
        CAST("LATITUDE" AS DOUBLE) >= {bbox['lat_min'] - buffer}
        AND CAST("LATITUDE" AS DOUBLE) <= {bbox['lat_max'] + buffer}
        AND CAST("LONGITUDE" AS DOUBLE) >= {bbox['lon_min'] - buffer}
        AND CAST("LONGITUDE" AS DOUBLE) <= {bbox['lon_max'] + buffer}
    """

    # Query species frequency at data resolution, then filter to boundary
    print("Calculating species frequency data...")
    query = f"""
        WITH cell_data AS (
            SELECT
                h3_latlng_to_cell(
                    CAST("LATITUDE" AS DOUBLE),
                    CAST("LONGITUDE" AS DOUBLE),
                    {data_resolution}
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
        -- Filter to cells within our boundary
        filtered_cells AS (
            SELECT * FROM cell_data
            WHERE h3_cell_to_parent(h3_cell, {boundary_res}) = h3_latlng_to_cell(
                {center_lat}, {center_lon}, {boundary_res}
            )
        ),
        cell_month_totals AS (
            SELECT h3_cell, month, COUNT(DISTINCT checklist_id) as total_checklists
            FROM filtered_cells
            GROUP BY h3_cell, month
        ),
        species_counts AS (
            SELECT h3_cell, avibase_id, scientific_name, month,
                   COUNT(DISTINCT checklist_id) as species_checklists
            FROM filtered_cells
            GROUP BY h3_cell, avibase_id, scientific_name, month
        )
        SELECT
            sc.h3_cell, sc.avibase_id, sc.scientific_name, sc.month,
            sc.species_checklists, cmt.total_checklists,
            sc.species_checklists::DOUBLE / cmt.total_checklists::DOUBLE as frequency
        FROM species_counts sc
        JOIN cell_month_totals cmt ON sc.h3_cell = cmt.h3_cell AND sc.month = cmt.month
    """

    query_start = time.time()
    result = ddb.execute(query).fetchall()
    print(f"  Query completed in {format_duration(time.time() - query_start)}")
    print(f"  Raw rows: {len(result):,}")

    if not result:
        print("ERROR: No data found for boundary cell!")
        return None

    # Process data
    print("Processing frequency data...")
    cell_species_data = {}
    species_names = {}
    unique_cells = set()

    for h3_cell, avibase_id, scientific_name, month, species_count, total_count, frequency in result:
        key = (h3_cell, avibase_id)
        unique_cells.add(h3_cell)

        if key not in cell_species_data:
            cell_species_data[key] = {"months": {}, "name": scientific_name}

        cell_species_data[key]["months"][month] = {
            "freq": frequency,
            "count": species_count,
        }

        if avibase_id not in species_names:
            species_names[avibase_id] = scientific_name

    print(f"  Unique data cells with observations: {len(unique_cells)}")
    print(f"  Unique species: {len(species_names)}")
    print(f"  Cell-species combinations: {len(cell_species_data)}")

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

        if avg_freq >= TIER_THRESHOLDS["common"]:
            tier, boost = "common", 1.5
        elif avg_freq >= TIER_THRESHOLDS["uncommon"]:
            tier, boost = "uncommon", 1.2
        elif avg_freq >= TIER_THRESHOLDS["rare"]:
            tier, boost = "rare", 1.0
        else:
            tier, boost = "vagrant", 0.8

        quality = min(1.0, total_count / 100)
        grid_species.append((h3_cell, avibase_id, tier, boost, avg_freq, quality))

    species = [(aid, name, None) for aid, name in species_names.items()]

    print(f"  Monthly rows: {len(monthly):,}")
    print(f"  Grid species rows: {len(grid_species):,}")

    # Create database
    print(f"\nCreating SQLite database...")
    output_dir.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    conn = sqlite3.connect(output_path)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")

    create_schema(conn)

    # Insert data
    conn.executemany(
        "INSERT INTO grid_species VALUES (?,?,?,?,?,?)",
        grid_species,
    )
    conn.executemany(
        "INSERT INTO grid_species_monthly VALUES (?,?,?,?,?)",
        monthly,
    )
    conn.executemany(
        "INSERT INTO species_lookup VALUES (?,?,?)",
        species,
    )

    # Insert metadata matching manifest format
    import datetime
    metadata = [
        ("pack_id", pack_id),
        ("boundary_cell", boundary_cell),
        ("boundary_resolution", str(boundary_res)),
        ("data_resolution", str(data_resolution)),
        ("center_lat", str(center_lat)),
        ("center_lon", str(center_lon)),
        ("bbox_lat_min", str(bbox["lat_min"])),
        ("bbox_lat_max", str(bbox["lat_max"])),
        ("bbox_lon_min", str(bbox["lon_min"])),
        ("bbox_lon_max", str(bbox["lon_max"])),
        ("species_count", str(len(species))),
        ("data_cell_count", str(len(unique_cells))),
        ("build_date", datetime.datetime.now().isoformat()),
    ]
    conn.executemany("INSERT INTO pack_metadata VALUES (?,?)", metadata)

    # Create indexes
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

    # Build manifest entry
    manifest_entry = {
        "pack_id": pack_id,
        "boundary_cell": boundary_cell,
        "boundary_resolution": boundary_res,
        "data_resolution": data_resolution,
        "center_lat": center_lat,
        "center_lon": center_lon,
        "estimated_size_mb": file_size / (1024 * 1024),
        "num_data_hexagons": len(unique_cells),
        "total_species": len(species),
        "total_checklists": sum(md["count"] for data in cell_species_data.values() for md in data["months"].values()),
    }

    # Write manifest entry
    manifest_path = output_dir / f"{pack_id}.manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest_entry, f, indent=2)

    print()
    print("=" * 60)
    print("BUILD COMPLETE")
    print("=" * 60)
    print(f"  Pack ID: {pack_id}")
    print(f"  Output: {output_path}")
    print(f"  Size: {format_size(file_size)}")
    print(f"  Time: {format_duration(elapsed)}")
    print(f"  Species: {len(species)}")
    print(f"  Data cells: {len(unique_cells)}")
    print(f"  Manifest: {manifest_path}")
    print()

    return manifest_entry


def main():
    parser = argparse.ArgumentParser(
        description="Build a single region pack for an H3 boundary cell",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Build pack for a specific H3 boundary cell
    uv run build_pack.py --boundary-cell 842b9adffffffff --data-resolution 7

    # Auto-detect boundary cell from coordinates (Toronto)
    uv run build_pack.py --lat 43.65 --lon -79.38 --boundary-resolution 4 --data-resolution 7

    # Build coarser pack for sparse area
    uv run build_pack.py --lat 45.0 --lon -80.0 --boundary-resolution 3 --data-resolution 6
        """,
    )

    # Location specification (mutually exclusive)
    location = parser.add_mutually_exclusive_group(required=True)
    location.add_argument(
        "--boundary-cell",
        type=str,
        help="H3 boundary cell ID (hex string)",
    )
    location.add_argument(
        "--lat",
        type=float,
        help="Latitude for auto-detecting boundary cell",
    )

    parser.add_argument(
        "--lon",
        type=float,
        help="Longitude (required with --lat)",
    )
    parser.add_argument(
        "--boundary-resolution",
        type=int,
        default=4,
        help="H3 resolution for boundary cell (default: 4, ~22km)",
    )
    parser.add_argument(
        "--data-resolution",
        type=int,
        required=True,
        help="H3 resolution for data cells (e.g., 7 for ~1.2km)",
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
        default=Path("output/packs"),
        help="Directory for output pack",
    )
    parser.add_argument(
        "--memory-limit",
        default="8GB",
        help="DuckDB memory limit",
    )

    args = parser.parse_args()

    # Determine boundary cell
    if args.boundary_cell:
        boundary_cell = args.boundary_cell
    else:
        if args.lon is None:
            parser.error("--lon is required when using --lat")
        boundary_cell = h3.latlng_to_cell(args.lat, args.lon, args.boundary_resolution)
        print(f"Auto-detected boundary cell: {boundary_cell}")

    # Validate
    if not args.parquet_dir.exists():
        print(f"Error: Parquet directory not found: {args.parquet_dir}")
        return 1

    boundary_res = h3.get_resolution(boundary_cell)
    if args.data_resolution <= boundary_res:
        print(f"Error: Data resolution ({args.data_resolution}) must be > boundary resolution ({boundary_res})")
        return 1

    result = build_pack(
        args.parquet_dir,
        args.output_dir,
        boundary_cell,
        args.data_resolution,
        args.memory_limit,
    )

    return 0 if result else 1


if __name__ == "__main__":
    exit(main())
