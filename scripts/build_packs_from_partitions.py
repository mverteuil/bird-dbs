#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "duckdb>=1.0.0",
#   "h3>=3.7.0",
# ]
# ///
"""
Build region packs from pre-partitioned eBird data.

Each region (from pack_manifest.json) produces ONE SQLite pack containing
data for all boundary cells in that region, with multi-resolution fallback.

Usage:
    # Build all region packs
    uv run build_packs_from_partitions.py \
        --partitioned-dir /Volumes/Lightroom/ebird_partitioned \
        --manifest /Volumes/Lightroom/ebird_partitioned/pack_manifest.json \
        --output-dir /Volumes/Lightroom/region_packs

    # Build specific region
    uv run build_packs_from_partitions.py \
        --partitioned-dir /Volumes/Lightroom/ebird_partitioned \
        --manifest /Volumes/Lightroom/ebird_partitioned/pack_manifest.json \
        --output-dir /Volumes/Lightroom/region_packs \
        --region north-america-southern-ontario

    # Parallel execution
    uv run build_packs_from_partitions.py ... --worker 0 --total-workers 4
"""

import argparse
import datetime
import json
import os
import sqlite3
import time
from pathlib import Path

import duckdb
import h3


# Frequency thresholds for confidence tiers
TIER_THRESHOLDS = {"common": 0.10, "uncommon": 0.01, "rare": 0.001, "vagrant": 0.0}

# Base confidence boosts by tier
TIER_BOOSTS = {"common": 1.5, "uncommon": 1.2, "rare": 1.0, "vagrant": 0.8}

# Resolution penalty multipliers (coarser = less confident)
RESOLUTION_PENALTIES = {
    5: 1.0,   # No penalty - finest resolution
    4: 0.8,   # 20% penalty - medium resolution
    2: 0.5,   # 50% penalty - coarse fallback
}

# Data resolutions to compute (finest to coarsest)
DATA_RESOLUTIONS = [5, 4, 2]


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


def create_schema(conn: sqlite3.Connection) -> None:
    """Create pack schema with multi-resolution support."""
    conn.executescript("""
        -- Main species presence table with resolution for fallback queries
        CREATE TABLE grid_species (
            h3_cell INTEGER NOT NULL,
            resolution INTEGER NOT NULL,
            avibase_id TEXT NOT NULL,
            confidence_tier TEXT NOT NULL,
            confidence_boost REAL NOT NULL,
            yearly_frequency REAL NOT NULL,
            quality_score REAL NOT NULL DEFAULT 0.5,
            PRIMARY KEY (h3_cell, resolution, avibase_id)
        );

        -- Monthly frequency data with resolution
        CREATE TABLE grid_species_monthly (
            h3_cell INTEGER NOT NULL,
            resolution INTEGER NOT NULL,
            avibase_id TEXT NOT NULL,
            month INTEGER NOT NULL,
            frequency REAL NOT NULL,
            checklist_count INTEGER NOT NULL,
            PRIMARY KEY (h3_cell, resolution, avibase_id, month)
        );

        -- Species lookup (resolution-independent)
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


def compute_frequency_at_resolution(
    ddb: duckdb.DuckDBPyConnection,
    file_list: str,
    resolution: int,
) -> list:
    """Compute species frequency data at a specific H3 resolution."""
    query = f"""
        WITH cell_data AS (
            SELECT
                h3_latlng_to_cell(
                    CAST("LATITUDE" AS DOUBLE),
                    CAST("LONGITUDE" AS DOUBLE),
                    {resolution}
                ) as h3_cell,
                "TAXON CONCEPT ID" as avibase_id,
                "SCIENTIFIC NAME" as scientific_name,
                CAST(SUBSTR("OBSERVATION DATE", 6, 2) AS INTEGER) as month,
                "SAMPLING EVENT IDENTIFIER" as checklist_id
            FROM read_parquet({file_list})
            WHERE "TAXON CONCEPT ID" IS NOT NULL
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
    """
    return ddb.execute(query).fetchall()


def build_region_pack(
    region: dict,
    partitioned_dir: Path,
    output_dir: Path,
) -> dict | None:
    """Build a single region pack containing all cells in the region."""
    region_id = region["region_id"]
    center = region.get("center", {"lat": 0, "lon": 0})
    packs = region.get("packs", [])

    if not packs:
        return None

    # Get all boundary cells in this region
    boundary_cells = [p["boundary_cell"] for p in packs if p.get("boundary_cell")]

    # Collect all parquet files from all partition directories
    all_parquet_files = []
    missing_partitions = []

    for cell in boundary_cells:
        partition_dir = partitioned_dir / f"boundary_cell={cell}"
        if partition_dir.exists():
            files = [f for f in partition_dir.glob("*.parquet") if not f.name.startswith("._")]
            all_parquet_files.extend(files)
        else:
            missing_partitions.append(cell)

    if not all_parquet_files:
        print(f"  Warning: No parquet files found for region {region_id}")
        return None

    if missing_partitions:
        print(f"  Warning: {len(missing_partitions)} partitions missing for region {region_id}")

    file_list = "[" + ", ".join(f"'{f}'" for f in all_parquet_files) + "]"

    # Initialize DuckDB
    ddb = duckdb.connect()
    ddb.execute("INSTALL h3 FROM community; LOAD h3")

    # Collect data at all resolutions
    all_monthly = []
    all_grid_species = []
    species_names = {}
    cells_by_resolution = {res: set() for res in DATA_RESOLUTIONS}

    for resolution in DATA_RESOLUTIONS:
        print(f"    Processing resolution {resolution}...")
        result = compute_frequency_at_resolution(ddb, file_list, resolution)

        if not result:
            continue

        # Process data for this resolution
        cell_species_data = {}

        for h3_cell, avibase_id, scientific_name, month, species_count, total_count, frequency in result:
            key = (h3_cell, avibase_id)
            cells_by_resolution[resolution].add(h3_cell)

            if key not in cell_species_data:
                cell_species_data[key] = {"months": {}, "name": scientific_name}

            cell_species_data[key]["months"][month] = {
                "freq": frequency,
                "count": species_count,
            }

            if avibase_id not in species_names:
                species_names[avibase_id] = scientific_name

        # Build tables for this resolution
        resolution_penalty = RESOLUTION_PENALTIES.get(resolution, 1.0)

        for (h3_cell, avibase_id), data in cell_species_data.items():
            freqs = []
            total_count = 0

            for month, md in data["months"].items():
                all_monthly.append((
                    h3_cell, resolution, avibase_id, month, md["freq"], md["count"]
                ))
                freqs.append(md["freq"])
                total_count += md["count"]

            avg_freq = sum(freqs) / len(freqs)

            # Determine tier from frequency
            if avg_freq >= TIER_THRESHOLDS["common"]:
                tier = "common"
            elif avg_freq >= TIER_THRESHOLDS["uncommon"]:
                tier = "uncommon"
            elif avg_freq >= TIER_THRESHOLDS["rare"]:
                tier = "rare"
            else:
                tier = "vagrant"

            # Apply resolution penalty to boost
            base_boost = TIER_BOOSTS[tier]
            penalized_boost = base_boost * resolution_penalty

            quality = min(1.0, total_count / 100)
            all_grid_species.append((
                h3_cell, resolution, avibase_id, tier, penalized_boost, avg_freq, quality
            ))

    ddb.close()

    if not all_grid_species:
        return None

    species = [(aid, name, None) for aid, name in species_names.items()]

    # Create database
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{region_id}.db"

    if output_path.exists():
        output_path.unlink()

    conn = sqlite3.connect(output_path)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")

    create_schema(conn)

    # Batch insert for performance
    print(f"    Inserting {len(all_grid_species):,} grid_species rows...")
    conn.executemany(
        "INSERT INTO grid_species VALUES (?,?,?,?,?,?,?)",
        all_grid_species
    )

    print(f"    Inserting {len(all_monthly):,} monthly rows...")
    conn.executemany(
        "INSERT INTO grid_species_monthly VALUES (?,?,?,?,?,?)",
        all_monthly
    )

    conn.executemany("INSERT INTO species_lookup VALUES (?,?,?)", species)

    # Metadata
    metadata = [
        ("region_id", region_id),
        ("boundary_cells", ",".join(boundary_cells)),
        ("boundary_cell_count", str(len(boundary_cells))),
        ("data_resolutions", ",".join(str(r) for r in DATA_RESOLUTIONS)),
        ("center_lat", str(center.get("lat", 0))),
        ("center_lon", str(center.get("lon", 0))),
        ("species_count", str(len(species))),
        ("data_cell_count_res5", str(len(cells_by_resolution.get(5, set())))),
        ("data_cell_count_res4", str(len(cells_by_resolution.get(4, set())))),
        ("data_cell_count_res2", str(len(cells_by_resolution.get(2, set())))),
        ("build_date", datetime.datetime.now().isoformat()),
    ]
    conn.executemany("INSERT INTO pack_metadata VALUES (?,?)", metadata)

    # Create indexes
    print("    Creating indexes...")
    conn.executescript("""
        CREATE INDEX idx_grid_species_cell_res ON grid_species(h3_cell, resolution);
        CREATE INDEX idx_grid_species_avibase ON grid_species(avibase_id);
        CREATE INDEX idx_species_monthly_cell_res ON grid_species_monthly(h3_cell, resolution);
        CREATE INDEX idx_species_lookup_name ON species_lookup(scientific_name);
    """)

    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("VACUUM")
    conn.execute("ANALYZE")
    conn.commit()
    conn.close()

    file_size = os.path.getsize(output_path)

    # Build manifest entry
    manifest_entry = {
        "region_id": region_id,
        "boundary_cells": boundary_cells,
        "boundary_cell_count": len(boundary_cells),
        "data_resolutions": DATA_RESOLUTIONS,
        "center_lat": center.get("lat", 0),
        "center_lon": center.get("lon", 0),
        "size_mb": file_size / (1024 * 1024),
        "num_cells_res5": len(cells_by_resolution.get(5, set())),
        "num_cells_res4": len(cells_by_resolution.get(4, set())),
        "num_cells_res2": len(cells_by_resolution.get(2, set())),
        "total_species": len(species),
        "grid_species_rows": len(all_grid_species),
        "monthly_rows": len(all_monthly),
    }

    # Write manifest
    manifest_path = output_dir / f"{region_id}.manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest_entry, f, indent=2)

    return manifest_entry


def main():
    parser = argparse.ArgumentParser(
        description="Build region packs from pre-partitioned eBird data",
    )
    parser.add_argument(
        "--partitioned-dir",
        type=Path,
        required=True,
        help="Directory with partitioned data from partition_by_boundary.py",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Pack manifest JSON from pack-planner",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Output directory for region pack databases",
    )
    parser.add_argument(
        "--region",
        type=str,
        default=None,
        help="Build only this specific region",
    )
    parser.add_argument(
        "--worker",
        type=int,
        default=0,
        help="Worker ID for parallel execution (0-indexed)",
    )
    parser.add_argument(
        "--total-workers",
        type=int,
        default=1,
        help="Total number of parallel workers",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip regions that already exist",
    )

    args = parser.parse_args()

    if not args.partitioned_dir.exists():
        print(f"Error: Partitioned directory not found: {args.partitioned_dir}")
        return 1

    if not args.manifest.exists():
        print(f"Error: Manifest not found: {args.manifest}")
        return 1

    # Load manifest
    with open(args.manifest) as f:
        manifest = json.load(f)

    regions = manifest.get("regions", [])

    if not regions:
        print("Error: No regions found in manifest")
        return 1

    # Filter to specific region if requested
    if args.region:
        regions = [r for r in regions if r.get("region_id") == args.region]
        if not regions:
            print(f"Error: Region not found: {args.region}")
            return 1

    # Filter for this worker
    if args.total_workers > 1:
        regions = [
            r for i, r in enumerate(regions)
            if i % args.total_workers == args.worker
        ]

    print("=" * 60)
    print("Building Region Packs from Partitioned Data")
    print("=" * 60)
    print(f"Regions to process: {len(regions)}")
    print(f"Data resolutions: {DATA_RESOLUTIONS} (with fallback)")
    print(f"Resolution penalties: {RESOLUTION_PENALTIES}")
    if args.total_workers > 1:
        print(f"Worker: {args.worker + 1}/{args.total_workers}")
    print()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    start_time = time.time()
    completed = 0
    skipped = 0
    failed = 0
    all_manifests = []

    for i, region in enumerate(regions, 1):
        region_id = region.get("region_id", "unknown")
        output_path = args.output_dir / f"{region_id}.db"

        if args.skip_existing and output_path.exists():
            skipped += 1
            print(f"[{i}/{len(regions)}] {region_id}: SKIPPED (exists)")
            continue

        region_start = time.time()
        print(f"[{i}/{len(regions)}] {region_id}: Building...")

        try:
            result = build_region_pack(
                region,
                args.partitioned_dir,
                args.output_dir,
            )

            if result:
                completed += 1
                all_manifests.append(result)
                elapsed = time.time() - region_start

                # Progress
                total_elapsed = time.time() - start_time
                rate = completed / total_elapsed if total_elapsed > 0 else 0
                remaining = len(regions) - i
                eta = remaining / rate if rate > 0 else 0

                print(f"  -> {result['total_species']} species, "
                      f"res5={result['num_cells_res5']}/res4={result['num_cells_res4']}/res2={result['num_cells_res2']} cells, "
                      f"{format_size(int(result['size_mb'] * 1024 * 1024))}, "
                      f"{elapsed:.1f}s (ETA: {format_duration(eta)})")
            else:
                failed += 1
                print(f"  -> No data")

        except Exception as e:
            failed += 1
            print(f"  -> ERROR: {e}")
            import traceback
            traceback.print_exc()

    # Write combined manifest
    combined_manifest = {
        "regions": all_manifests,
        "total_regions": len(all_manifests),
        "data_resolutions": DATA_RESOLUTIONS,
        "resolution_penalties": RESOLUTION_PENALTIES,
    }

    manifest_path = args.output_dir / f"regions_manifest_worker{args.worker}.json"
    with open(manifest_path, "w") as f:
        json.dump(combined_manifest, f, indent=2)

    elapsed = time.time() - start_time

    print()
    print("=" * 60)
    print("BUILD COMPLETE")
    print("=" * 60)
    print(f"  Completed: {completed}")
    print(f"  Skipped: {skipped}")
    print(f"  Failed: {failed}")
    print(f"  Time: {format_duration(elapsed)}")
    if elapsed > 0 and completed > 0:
        print(f"  Rate: {completed / elapsed * 60:.1f} regions/minute")
    print(f"  Manifest: {manifest_path}")

    return 0


if __name__ == "__main__":
    exit(main())
